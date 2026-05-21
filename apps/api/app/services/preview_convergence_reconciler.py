from __future__ import annotations

import re
import time
from typing import Any, Callable


ProbeFn = Callable[[str, str], dict[str, Any]]

_VALID_JS_MIME_TYPES = {
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "text/ecmascript",
    "application/ecmascript",
}


def looks_like_javascript_content_type(content_type: str) -> bool:
    lower = (content_type or "").strip().lower()
    base = lower.split(";", 1)[0].strip()
    if base in _VALID_JS_MIME_TYPES:
        return True
    return any(marker in base for marker in ("javascript", "ecmascript", "typescript"))


def extract_root_module_entry_path(root_html: str) -> str:
    match = re.search(
        r'<script[^>]*type=["\']module["\'][^>]*src=["\']([^"\']+)["\']',
        root_html,
        flags=re.IGNORECASE,
    )
    if not match:
        return "/src/main.ts"
    raw = str(match.group(1) or "").strip()
    if not raw or raw.startswith(("http://", "https://")):
        return "/src/main.ts"
    return raw if raw.startswith("/") else f"/{raw}"


def _probe_vite_runtime(url: str, *, probe_fn: ProbeFn) -> dict[str, Any]:
    root_probe = probe_fn(url, "/")
    client_probe = probe_fn(url, "/@vite/client")
    root_sample_raw = str(root_probe.get("body_sample") or "")
    entry_path = extract_root_module_entry_path(root_sample_raw)
    entry_probe = probe_fn(url, entry_path)

    root_sample = root_sample_raw.lower()
    client_sample = str(client_probe.get("body_sample") or "").lower()
    entry_sample = str(entry_probe.get("body_sample") or "").lower()

    root_ok = bool(root_probe.get("ok")) and "<script" in root_sample and "type='module'" in root_sample.replace('"', "'")
    client_ok = (
        bool(client_probe.get("ok"))
        and looks_like_javascript_content_type(str(client_probe.get("content_type") or ""))
        and "import" in client_sample
    )
    entry_looks_like_html_fallback = "<!doctype html" in entry_sample or "<html" in entry_sample or "<body" in entry_sample
    entry_ok = (
        bool(entry_probe.get("ok"))
        and looks_like_javascript_content_type(str(entry_probe.get("content_type") or ""))
        and not entry_looks_like_html_fallback
    )
    browser_renderable = root_ok and client_ok and entry_ok
    return {
        "runtime_validation": "vite_dev",
        "root_probe": root_probe,
        "vite_client_probe": client_probe,
        "entry_probe": entry_probe,
        "entry_path": entry_path,
        "root_html_ok": root_ok,
        "vite_client_ok": client_ok,
        "entry_mime_ok": entry_ok,
        "browser_renderable_app_confirmed": browser_renderable,
        "mime_validation_passed": browser_renderable,
    }


def reconcile_vite_preview_convergence(
    *,
    url: str,
    probe_fn: ProbeFn,
    stabilization_window_seconds: float = 0.8,
) -> dict[str, Any]:
    first = _probe_vite_runtime(url, probe_fn=probe_fn)
    time.sleep(stabilization_window_seconds)
    second = _probe_vite_runtime(url, probe_fn=probe_fn)
    healthy = bool(second.get("mime_validation_passed"))
    failed_checks = ", ".join(
        check
        for check, ok in (
            ("root_html_ok", bool(second.get("root_html_ok"))),
            ("vite_client_ok", bool(second.get("vite_client_ok"))),
            ("entry_mime_ok", bool(second.get("entry_mime_ok"))),
        )
        if not ok
    ) or "unknown"
    entry_probe = second.get("entry_probe") if isinstance(second.get("entry_probe"), dict) else {}
    verification_note = None
    if not healthy:
        verification_note = (
            f"Vite preview started, but module asset validation failed for {second.get('entry_path') or '/src/main.ts'}. "
            f"Observed Content-Type: {str(entry_probe.get('content_type') or 'missing')}. "
            f"Failed checks: {failed_checks}."
        )
    return {
        "healthy": healthy,
        "verification_note": verification_note,
        "preview_launch_state": {
            "phase": "launch",
            "probe_count": 1,
            "checks": first,
        },
        "preview_runtime_state": {
            "phase": "stabilizing",
            "probe_count": 2,
            "checks": second,
            "stabilization_window_seconds": stabilization_window_seconds,
        },
        "preview_terminal_state": {
            "phase": "terminal",
            "status": "READY" if healthy else "FAILED",
            "authoritative": True,
            "failed_checks": failed_checks if not healthy else "",
        },
    }
