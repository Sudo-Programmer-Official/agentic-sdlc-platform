from __future__ import annotations

import hashlib
import html
import re
import uuid
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Artifact


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


@dataclass
class IngestedReference:
    url: str
    domain: str
    title: str
    content_type: str
    status_code: int
    fetched_bytes: int
    content_sha256: str
    sanitized_text: str
    summary: str
    token_estimate: int


def _token_estimate(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def _strip_html(text: str) -> str:
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", text)
    without_tags = _TAG_RE.sub(" ", without_scripts)
    decoded = html.unescape(without_tags)
    cleaned = "".join(ch for ch in decoded if ch.isprintable() or ch in "\n\t")
    return _WS_RE.sub(" ", cleaned).strip()


def _summarize(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _normalize_domain(domain: str | None) -> str:
    value = (domain or "").strip().lower()
    if value.startswith("www."):
        value = value[4:]
    return value


def _domain_allowed(domain: str, allowlist: list[str]) -> bool:
    if not domain:
        return False
    for item in allowlist:
        allowed = _normalize_domain(item)
        if not allowed:
            continue
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def _allowlist() -> list[str]:
    cfg = get_settings()
    raw = str(cfg.external_reference_domain_allowlist or "")
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return values


def _sanitize_url(raw_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(raw_url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    domain = _normalize_domain(parsed.hostname)
    if not domain:
        raise ValueError("URL must include a valid hostname")
    if not _domain_allowed(domain, _allowlist()):
        raise ValueError(f"Domain '{domain}' is not allowed")
    normalized = urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc, parsed.path, "", parsed.query, ""))
    return normalized, domain


def ingest_external_url(url: str) -> IngestedReference:
    cfg = get_settings()
    normalized_url, domain = _sanitize_url(url)
    timeout = max(2, int(cfg.external_reference_fetch_timeout_seconds))
    max_bytes = max(1, int(cfg.external_reference_max_content_bytes))
    max_text_chars = max(256, int(cfg.external_reference_max_sanitized_chars))
    max_summary_chars = max(128, int(cfg.external_reference_max_summary_chars))

    req = urllib.request.Request(
        normalized_url,
        headers={"User-Agent": "AgenticSDLCExternalReference/1.0", "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status_code = int(getattr(resp, "status", 200) or 200)
        content_type = str(resp.headers.get("Content-Type") or "application/octet-stream")
        raw = resp.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Content exceeds configured byte limit")

    text = raw.decode("utf-8", errors="replace")
    sanitized = _strip_html(text)
    if len(sanitized) > max_text_chars:
        sanitized = sanitized[:max_text_chars].rstrip()
    summary = _summarize(sanitized, max_summary_chars)
    return IngestedReference(
        url=normalized_url,
        domain=domain,
        title=domain,
        content_type=content_type,
        status_code=status_code,
        fetched_bytes=len(raw),
        content_sha256=hashlib.sha256(raw).hexdigest(),
        sanitized_text=sanitized,
        summary=summary,
        token_estimate=_token_estimate(sanitized),
    )


async def persist_external_reference(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    source_url: str,
    run_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    work_item_id: uuid.UUID | None = None,
    requirement_id: str | None = None,
    label: str | None = None,
) -> Artifact:
    ingested = ingest_external_url(source_url)
    artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        task_id=task_id,
        work_item_id=work_item_id,
        requirement_id=requirement_id,
        type="external_reference",
        uri=ingested.url,
        extra_metadata={
            "label": (label or ingested.title),
            "domain": ingested.domain,
            "summary": ingested.summary,
            "sanitized_text": ingested.sanitized_text,
            "token_estimate": ingested.token_estimate,
            "fetched_bytes": ingested.fetched_bytes,
            "content_type": ingested.content_type,
            "status_code": ingested.status_code,
            "content_sha256": ingested.content_sha256,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "trust_score": 0.8,
            "used_in_execution_count": 0,
            "source_kind": "url",
            "ingestion_mode": "bounded_single_fetch",
            "replay_key": f"{ingested.url}:{ingested.content_sha256}",
        },
    )
    session.add(artifact)
    await session.flush()
    return artifact
