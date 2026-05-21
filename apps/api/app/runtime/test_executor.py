from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.runtime.executor import TaskExecutor, TaskResult
from app.runtime.context import RunContext
from app.db.models import WorkItem
from app.services.frontend_composition_integrity import (
    reconcile_frontend_runtime_shell,
    validate_frontend_composition_integrity,
)
from app.services.workspace_supervisor import workspace_uri
from app.services.workspace_commands import run_workspace_command_async


class TestExecutor(TaskExecutor):
    __test__ = False
    name = "test"

    def __init__(self, repo_root: Path | None = None):
        self.settings = get_settings()
        self.repo_root = repo_root or Path.cwd()

    def _command_env(self) -> dict[str, str]:
        python_bin = str(Path(sys.executable).resolve().parent)
        current_path = os.environ.get("PATH", "")
        path_parts = [part for part in current_path.split(os.pathsep) if part and part != python_bin]
        path_parts.insert(0, python_bin)
        return {"PATH": os.pathsep.join(path_parts) if path_parts else python_bin}

    def _normalize_test_command(self, command: list[str]) -> list[str]:
        if not command:
            return command
        executable = Path(command[0]).name
        if executable == "pytest":
            return [sys.executable, "-m", "pytest", *command[1:]]
        return command

    @staticmethod
    def _is_pytest_command(command: list[str]) -> bool:
        if not command:
            return False
        executable = Path(command[0]).name
        if executable == "pytest":
            return True
        return len(command) >= 3 and command[1] == "-m" and command[2] == "pytest"

    @staticmethod
    def _scoped_test_files(work_item: WorkItem) -> list[str]:
        payload = work_item.payload or {}
        scoped: list[str] = []
        for key in ("target_files", "files", "expected_files"):
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str):
                    continue
                path = value.strip()
                if not path:
                    continue
                name = Path(path).name
                if Path(path).suffix == ".py" and name.startswith("test_"):
                    scoped.append(path)
        return list(dict.fromkeys(scoped))

    @staticmethod
    def _infer_static_frontend_test_targets(work_item: WorkItem, repo_root: Path) -> list[str]:
        payload = work_item.payload or {}
        referenced_files: list[str] = []
        for key in ("target_files", "files", "expected_files"):
            values = payload.get(key)
            if isinstance(values, list):
                referenced_files.extend(value for value in values if isinstance(value, str))
        normalized = [value.strip().lower() for value in referenced_files if value.strip()]
        layout_touched = any(
            path.endswith((".html", ".css", ".js", ".ts", ".tsx", ".vue"))
            or "nav" in path
            or "header" in path
            or "layout" in path
            for path in normalized
        )
        if not layout_touched:
            return []
        static_test = repo_root / "test_index_html.py"
        return ["test_index_html.py"] if static_test.exists() else []

    @staticmethod
    def _pytest_has_explicit_targets(command: list[str]) -> bool:
        if not command:
            return False
        args = command[1:] if Path(command[0]).name == "pytest" else command[3:]
        return any(arg and not arg.startswith("-") for arg in args)

    def _resolve_test_command(self, work_item: WorkItem, context: RunContext, repo_root: Path) -> list[str]:
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        package_affinity = str(payload.get("package_affinity") or "").strip().lower()
        if package_affinity.startswith("apps/web"):
            web_pkg = repo_root / "apps" / "web" / "package.json"
            if web_pkg.exists():
                return ["npm", "-C", "apps/web", "run", "test"]
        # Fallback router: infer frontend package affinity from payload scope/text.
        web_pkg = repo_root / "apps" / "web" / "package.json"
        if web_pkg.exists():
            referenced: list[str] = []
            for key in ("target_files", "files", "expected_files"):
                values = payload.get(key)
                if isinstance(values, list):
                    referenced.extend(value for value in values if isinstance(value, str))
            if any("apps/web/" in path.replace("\\", "/").lower() for path in referenced):
                return ["npm", "-C", "apps/web", "run", "test"]
            text_blob = " ".join(str(payload.get(k) or "") for k in ("task_title", "goal", "task_description")).lower()
            if any(token in text_blob for token in ("vue", "vite", ".vue", "landingpage", "testimonialssection")):
                return ["npm", "-C", "apps/web", "run", "test"]
        configured = (
            context.execution_contract.test_command
            if context.execution_contract is not None and context.execution_contract.test_command
            else self.settings.test_command
        )
        command = self._normalize_test_command(shlex.split(configured))
        if self._is_pytest_command(command) and not self._pytest_has_explicit_targets(command):
            scoped_files = self._scoped_test_files(work_item)
            if not scoped_files:
                scoped_files = self._infer_static_frontend_test_targets(work_item, repo_root)
            if scoped_files:
                command = [*command, *scoped_files]
        return command

    def _resolve_preview_validate_command(self, context: RunContext, repo_root: Path) -> list[str]:
        configured = (
            context.execution_contract.preview_command
            if context.execution_contract is not None and context.execution_contract.preview_command
            else ""
        )
        if isinstance(configured, str) and configured.strip():
            return shlex.split(configured)
        web_pkg = repo_root / "apps" / "web" / "package.json"
        if web_pkg.exists():
            return ["npm", "-C", "apps/web", "run", "build"]
        root_pkg = repo_root / "package.json"
        if root_pkg.exists():
            return ["npm", "run", "build"]
        index_html = repo_root / "index.html"
        if index_html.exists():
            return [sys.executable, "-c", "import pathlib,sys;sys.exit(0 if pathlib.Path('index.html').exists() else 1)"]
        return self._normalize_test_command(shlex.split(self.settings.test_command))

    @staticmethod
    def _is_missing_vite_binary(*, command: list[str], stderr: str, stdout: str, exit_code: int | None) -> bool:
        if exit_code != 127:
            return False
        command_text = " ".join(command).lower()
        if "apps/web" not in command_text:
            return False
        combined = f"{stdout}\n{stderr}".lower()
        return ("vite: command not found" in combined) or ("sh: vite: command not found" in combined)

    @staticmethod
    def _frontend_dependency_hydration_command(repo_root: Path) -> list[str] | None:
        web_pkg = repo_root / "apps" / "web" / "package.json"
        if not web_pkg.exists():
            return None
        # Deterministic install path for preview runtime dependency hydration.
        return ["npm", "-C", "apps/web", "install", "--no-audit", "--no-fund"]

    @staticmethod
    def _detect_stack_test_strategy_mismatch(
        *,
        work_item: WorkItem,
        command: list[str],
        stdout: str,
        stderr: str,
        repo_root: Path | None = None,
    ) -> tuple[bool, str | None]:
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        package_affinity = str(payload.get("package_affinity") or "").strip().lower()
        inferred_frontend_scope = package_affinity.startswith("apps/web")
        if not inferred_frontend_scope and repo_root is not None:
            inferred_frontend_scope = (repo_root / "apps" / "web" / "package.json").exists()
        if not inferred_frontend_scope:
            return False, None
        command_text = " ".join(command).lower()
        combined = f"{stdout}\n{stderr}".lower()
        if "vue_test_utils" in combined or "python test generated for vue" in combined:
            return True, "python_test_for_vue"
        if ("pytest" in command_text or " -m pytest" in command_text) and (
            "vitest" in combined or "vue" in combined or "spec.ts" in combined
        ):
            return True, "pytest_ran_for_frontend_suite"
        if "npm test expected but pytest ran" in combined:
            return True, "npm_expected_pytest_ran"
        return False, None

    @staticmethod
    def _template_web_root() -> Path:
        repo_root = Path(__file__).resolve().parents[4]
        foundation = repo_root / "runtime-templates" / "frontend-foundation" / "apps" / "web"
        if foundation.exists():
            return foundation
        return repo_root / "runtime-templates" / "fullstack-monorepo" / "apps" / "web"

    def _ensure_preview_workspace_ready(self, repo_root: Path, work_item: WorkItem) -> dict[str, object]:
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        package_affinity = str(payload.get("package_affinity") or "").strip().lower()
        frontend_root = repo_root / "apps" / "web"
        if not frontend_root.exists() and package_affinity.startswith("apps/web"):
            frontend_root.mkdir(parents=True, exist_ok=True)
        if not frontend_root.exists():
            return {"preview_workspace_consistency": "not_applicable", "workspace_hydration_repairs": []}
        template_root = self._template_web_root()
        repairs: list[str] = []
        for rel in (
            "package.json",
            "vite.config.ts",
            "src/main.ts",
            "src/App.vue",
            "src/pages/LandingPage.vue",
            "src/layouts/PageShell.vue",
            "src/components/layout/Navbar.vue",
            "src/components/layout/Footer.vue",
            "src/components/layout/MobileNav.vue",
            "src/components/ui/SectionContainer.vue",
            "src/components/ui/ContentGrid.vue",
            "src/components/ui/Stack.vue",
            "src/components/ui/SectionHeading.vue",
            "src/components/ui/PrimaryButton.vue",
            "src/components/zones/HeroZone.vue",
            "src/components/zones/FeatureZone.vue",
            "src/components/zones/TestimonialsZone.vue",
            "src/components/zones/CTAZone.vue",
            "index.html",
        ):
            target = frontend_root / rel
            if target.exists():
                continue
            source = template_root / rel
            if not source.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            repairs.append(f"apps/web/{rel}")
        # Deterministic entrypoint reconciliation for stale template drift:
        # if main.ts imports ./App.vue but App.vue is absent, recreate App.vue.
        entrypoint = frontend_root / "src" / "main.ts"
        app_vue = frontend_root / "src" / "App.vue"
        landing_page = frontend_root / "src" / "pages" / "LandingPage.vue"
        legacy_landing = frontend_root / "src" / "LandingPage.vue"
        if entrypoint.exists() and not app_vue.exists():
            main_text = entrypoint.read_text(encoding="utf-8")
            if "./App.vue" in main_text:
                app_fallback = "<template>\n  <main>\n    <h1>Landing Page</h1>\n  </main>\n</template>\n"
                if landing_page.exists():
                    app_content = (
                        "<template>\n  <LandingPage />\n</template>\n\n"
                        "<script setup lang=\"ts\">\n"
                        'import LandingPage from "./pages/LandingPage.vue";\n'
                        "</script>\n"
                    )
                elif legacy_landing.exists():
                    app_content = (
                        "<template>\n  <LandingPage />\n</template>\n\n"
                        "<script setup lang=\"ts\">\n"
                        'import LandingPage from "./LandingPage.vue";\n'
                        "</script>\n"
                    )
                else:
                    app_content = app_fallback
                app_vue.parent.mkdir(parents=True, exist_ok=True)
                app_vue.write_text(app_content, encoding="utf-8")
                repairs.append("apps/web/src/App.vue (entrypoint_reconciled)")
        shell_repairs = reconcile_frontend_runtime_shell(repo_root=repo_root)
        repairs.extend(shell_repairs)
        return {
            "preview_workspace_consistency": "repaired" if repairs else "ok",
            "workspace_hydration_repairs": repairs,
        }

    @staticmethod
    def _preview_probe_url(work_item: WorkItem) -> str | None:
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        direct = payload.get("preview_url") or payload.get("active_preview_url") or payload.get("url")
        if isinstance(direct, str) and direct.strip().startswith(("http://", "https://")):
            return direct.strip()
        nested = payload.get("preview")
        if isinstance(nested, dict):
            nested_url = nested.get("preview_url")
            if isinstance(nested_url, str) and nested_url.strip().startswith(("http://", "https://")):
                return nested_url.strip()
        env_url = os.environ.get("PREVIEW_URL", "").strip()
        if env_url.startswith(("http://", "https://")):
            return env_url
        return None

    @staticmethod
    def _probe_preview_url(url: str, timeout_seconds: int = 6) -> tuple[bool, str]:
        request = Request(url, method="GET")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 0) or 0)
                if 200 <= status < 500:
                    return True, f"preview_probe_status_{status}"
                return False, f"preview_probe_status_{status}"
        except HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            # 4xx means endpoint is reachable but unhealthy/config-mismatched.
            if 400 <= status < 500:
                return False, f"preview_probe_status_{status}"
            return False, f"preview_probe_http_error_{status}"
        except URLError as exc:
            return False, f"preview_probe_unreachable:{exc.reason}"
        except Exception as exc:
            return False, f"preview_probe_error:{exc}"

    @staticmethod
    def _validate_foundation_prerequisites(repo_root: Path) -> tuple[bool, list[str], dict[str, object]]:
        violations: list[str] = []
        web_root = repo_root / "apps" / "web" / "src"
        landing_path = web_root / "pages" / "LandingPage.vue"
        page_shell_path = web_root / "layouts" / "PageShell.vue"
        navbar_path = web_root / "components" / "layout" / "Navbar.vue"
        footer_path = web_root / "components" / "layout" / "Footer.vue"
        section_container_paths = [
            web_root / "components" / "layout" / "SectionContainer.vue",
            web_root / "components" / "ui" / "SectionContainer.vue",
        ]
        responsive_primitive_paths = [
            web_root / "components" / "ui" / "ContentGrid.vue",
            web_root / "components" / "ui" / "Stack.vue",
            web_root / "components" / "ui" / "SectionHeading.vue",
        ]

        if not landing_path.exists():
            violations.append("Foundation prerequisite violation: LandingPage.vue does not exist.")
            landing_content = ""
        else:
            landing_content = landing_path.read_text(encoding="utf-8")
        if not page_shell_path.exists():
            violations.append("Foundation prerequisite violation: PageShell.vue does not exist.")
        if not navbar_path.exists():
            violations.append("Foundation prerequisite violation: Navbar.vue does not exist.")
        if not footer_path.exists():
            violations.append("Foundation prerequisite violation: Footer.vue does not exist.")
        if not any(path.exists() for path in section_container_paths):
            violations.append("Foundation prerequisite violation: SectionContainer primitive does not exist.")
        if not any(path.exists() for path in responsive_primitive_paths):
            violations.append("Foundation prerequisite violation: responsive shell primitives are missing.")
        manifest_path = repo_root / "runtime-contracts" / "component-manifest.json"
        foundation_version_path = repo_root / "runtime-contracts" / "foundation_version.json"
        if not manifest_path.exists():
            violations.append("Foundation prerequisite violation: component-manifest.json does not exist.")
        if not foundation_version_path.exists():
            violations.append("Foundation prerequisite violation: foundation_version.json does not exist.")

        required_zones = ["HeroZone", "FeatureZone", "TestimonialsZone", "CTAZone"]
        missing_zones = [zone for zone in required_zones if f"<{zone}" not in landing_content]
        if missing_zones:
            violations.append(
                "Foundation prerequisite violation: missing required composition zones: " + ", ".join(missing_zones) + "."
            )
        if landing_content and "<PageShell" not in landing_content:
            violations.append("Foundation prerequisite violation: LandingPage must compose PageShell.")

        topology = {
            "shell": "PageShell",
            "zones": ["hero", "features", "testimonials", "cta"],
            "foundation_version": 1,
        }
        topology_path = repo_root / "runtime-contracts" / "topology_hash.json"
        topology_path.parent.mkdir(parents=True, exist_ok=True)
        topology_path.write_text(json.dumps(topology, indent=2) + "\n", encoding="utf-8")
        return len(violations) == 0, violations, {"topology_path": str(topology_path), "topology": topology}

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        repo_root = Path(context.repo_path) if context.repo_path else self.repo_root
        if work_item.type == "GENESIS_FOUNDATION":
            repairs = reconcile_frontend_runtime_shell(repo_root=repo_root)
            ok, violations, meta = self._validate_foundation_prerequisites(repo_root)
            topology_path = Path(str(meta.get("topology_path")))
            artifacts = [
                {
                    "type": "topology_hash",
                    "uri": workspace_uri("runtime-contracts", "topology_hash.json") if context.logs_path else str(topology_path),
                    "path": str(topology_path),
                    "payload": {"foundation_version": 1},
                }
            ]
            if ok:
                return {
                    "status": "DONE",
                    "message": "Foundation bootstrap converged deterministically",
                    "payload": {
                        "message": "Foundation bootstrap converged deterministically",
                        "workspace_hydration_repairs": repairs,
                        "topology_hash": meta.get("topology"),
                        "artifacts": artifacts,
                    },
                }
            return {
                "status": "FAILED",
                "message": "Foundation bootstrap failed deterministic validation",
                "payload": {
                    "message": "; ".join(violations),
                    "workspace_hydration_repairs": repairs,
                    "violations": violations,
                    "topology_hash": meta.get("topology"),
                    "artifacts": artifacts,
                },
            }
        if work_item.type == "FOUNDATION_VALIDATE":
            ok, violations, meta = self._validate_foundation_prerequisites(repo_root)
            topology_path = Path(str(meta.get("topology_path")))
            artifacts = [
                {
                    "type": "topology_hash",
                    "uri": workspace_uri("runtime-contracts", "topology_hash.json") if context.logs_path else str(topology_path),
                    "path": str(topology_path),
                    "payload": {"foundation_version": 1},
                }
            ]
            if ok:
                return {
                    "status": "DONE",
                    "message": "Foundation prerequisites validated",
                    "payload": {
                        "message": "Foundation prerequisites validated",
                        "topology_hash": meta.get("topology"),
                        "artifacts": artifacts,
                    },
                }
            return {
                "status": "FAILED",
                "message": "Foundation prerequisite validation failed",
                "payload": {
                    "message": "; ".join(violations),
                    "violations": violations,
                    "topology_hash": meta.get("topology"),
                    "artifacts": artifacts,
                },
            }
        framework_router = "backend_pytest"
        test_strategy = "pytest"
        web_pkg_present = (repo_root / "apps" / "web" / "package.json").exists()
        if isinstance(work_item.payload, dict):
            package_affinity = str(work_item.payload.get("package_affinity") or "").strip().lower()
            if package_affinity.startswith("apps/web"):
                framework_router = "frontend_vite_vitest"
                test_strategy = "vitest"
        if test_strategy == "pytest" and web_pkg_present:
            payload = work_item.payload if isinstance(work_item.payload, dict) else {}
            referenced_files: list[str] = []
            for key in ("target_files", "files", "expected_files"):
                values = payload.get(key)
                if isinstance(values, list):
                    referenced_files.extend(value for value in values if isinstance(value, str))
            if any("apps/web/" in path.replace("\\", "/").lower() for path in referenced_files):
                framework_router = "frontend_vite_vitest"
                test_strategy = "vitest"
        hydration_meta: dict[str, object] = {
            "preview_workspace_consistency": "not_applicable",
            "workspace_hydration_repairs": [],
        }
        dependency_repair_attempted = False
        dependency_repair_status = "not_required"
        if work_item.type in {"PREVIEW_VALIDATE", "FRAMEWORK_VALIDATE"}:
            hydration_meta = self._ensure_preview_workspace_ready(repo_root, work_item)
            cmd = self._resolve_preview_validate_command(context, repo_root)
        else:
            cmd = self._resolve_test_command(work_item, context, repo_root)
        log_dir = Path(context.logs_path) if context.logs_path else repo_root / ".agentic-sdlc-logs"
        try:
            result = await run_workspace_command_async(
                cmd,
                cwd=repo_root,
                log_dir=log_dir,
                label=f"test-{work_item.type.lower()}",
                timeout_seconds=self.settings.test_timeout_seconds,
                allowed_prefixes=(
                    list(context.execution_contract.allowed_command_prefixes)
                    if context.execution_contract is not None and context.execution_contract.allowed_command_prefixes
                    else None
                ),
                output_max_bytes=self.settings.test_output_max_bytes,
                env=self._command_env(),
            )
            if result.status == "BLOCKED":
                return {
                    "status": "FAILED",
                    "message": "Test command blocked by workspace policy",
                    "payload": {
                        "exit_code": None,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "command_status": result.status,
                    },
                }
            if result.timed_out:
                return {
                    "status": "FAILED",
                    "message": "Test command timed out",
                    "payload": {
                        "exit_code": None,
                        "stdout": result.stdout,
                        "stderr": result.stderr or "timeout",
                        "command_status": result.status,
                    },
                }

            out = result.stdout
            err = result.stderr
            exit_code = result.exit_code
            preview_stage = work_item.type == "PREVIEW_VALIDATE"
            framework_validation_stage = work_item.type == "FRAMEWORK_VALIDATE"
            if (
                (preview_stage or framework_validation_stage)
                and self._is_missing_vite_binary(command=cmd, stderr=err, stdout=out, exit_code=exit_code)
            ):
                install_cmd = self._frontend_dependency_hydration_command(repo_root)
                if install_cmd is not None:
                    dependency_repair_attempted = True
                    repair_result = await run_workspace_command_async(
                        install_cmd,
                        cwd=repo_root,
                        log_dir=log_dir,
                        label="test-preview-validate-hydrate-frontend-deps",
                        timeout_seconds=self.settings.test_timeout_seconds,
                        allowed_prefixes=(
                            list(context.execution_contract.allowed_command_prefixes)
                            if context.execution_contract is not None and context.execution_contract.allowed_command_prefixes
                            else None
                        ),
                        output_max_bytes=self.settings.test_output_max_bytes,
                        env=self._command_env(),
                    )
                    repair_exit_code = repair_result.exit_code
                    repair_ok = (
                        repair_result.status == "SUCCEEDED"
                        and not repair_result.timed_out
                        and repair_exit_code is not None
                        and int(repair_exit_code) == 0
                    )
                    if repair_ok:
                        retry_result = await run_workspace_command_async(
                            cmd,
                            cwd=repo_root,
                            log_dir=log_dir,
                            label=f"test-{work_item.type.lower()}-retry",
                            timeout_seconds=self.settings.test_timeout_seconds,
                            allowed_prefixes=(
                                list(context.execution_contract.allowed_command_prefixes)
                                if context.execution_contract is not None and context.execution_contract.allowed_command_prefixes
                                else None
                            ),
                            output_max_bytes=self.settings.test_output_max_bytes,
                            env=self._command_env(),
                        )
                        result = retry_result
                        out = result.stdout
                        err = result.stderr
                        exit_code = result.exit_code
                        dependency_repair_status = "repaired"
                        repairs = list(hydration_meta.get("workspace_hydration_repairs", []))
                        repairs.append("apps/web/node_modules (hydrated)")
                        hydration_meta["workspace_hydration_repairs"] = repairs
                        hydration_meta["preview_workspace_consistency"] = "repaired"
                    else:
                        dependency_repair_status = "failed"
                else:
                    dependency_repair_status = "skipped_missing_package_json"
            no_tests_collected = self._is_pytest_command(cmd) and exit_code == 5
            status = "SKIPPED" if (no_tests_collected and not preview_stage) else ("DONE" if exit_code == 0 else "FAILED")
            artifacts: list[dict] = []
            if result.log_path:
                log_path = Path(result.log_path)
                log_name = log_path.name
                uri = workspace_uri("logs", log_name) if context.logs_path else str(log_path)
                artifacts.append(
                    {
                        "type": "test_log",
                        "uri": uri,
                        "path": str(log_path),
                        "payload": {
                            "exit_code": exit_code,
                            "command_status": result.status,
                            "command_audit_path": result.audit_path,
                        },
                    }
                )
            preview_probe_url = self._preview_probe_url(work_item) if preview_stage else None
            preview_probe_ok = None
            preview_probe_detail = None
            if preview_stage and status == "DONE" and preview_probe_url:
                preview_probe_ok, preview_probe_detail = self._probe_preview_url(preview_probe_url)
                if not preview_probe_ok:
                    status = "FAILED"
            if preview_stage:
                message = "Preview validation passed" if status == "DONE" else "Preview validation failed"
            elif framework_validation_stage:
                message = "Framework validation passed" if status == "DONE" else "Framework validation failed"
            elif no_tests_collected:
                message = "No relevant tests were collected; validation skipped."
            else:
                message = "Tests passed" if status == "DONE" else "Tests failed"
            stack_mismatch_detected = False
            stack_mismatch_reason = None
            if work_item.type == "RUN_TESTS" and status == "FAILED":
                stack_mismatch_detected, stack_mismatch_reason = self._detect_stack_test_strategy_mismatch(
                    work_item=work_item,
                    command=cmd,
                    stdout=out,
                    stderr=err,
                    repo_root=repo_root,
                )
                # Production fallback: when frontend tests were routed to pytest and fail with Vue stack mismatch,
                # retry once with npm test in apps/web if available.
                web_pkg = repo_root / "apps" / "web" / "package.json"
                if stack_mismatch_detected and web_pkg.exists():
                    fallback_cmd = ["npm", "-C", "apps/web", "run", "test"]
                    retry_result = await run_workspace_command_async(
                        fallback_cmd,
                        cwd=repo_root,
                        log_dir=log_dir,
                        label="test-run-tests-frontend-fallback",
                        timeout_seconds=self.settings.test_timeout_seconds,
                        allowed_prefixes=(
                            list(context.execution_contract.allowed_command_prefixes)
                            if context.execution_contract is not None and context.execution_contract.allowed_command_prefixes
                            else None
                        ),
                        output_max_bytes=self.settings.test_output_max_bytes,
                        env=self._command_env(),
                    )
                    retry_exit_code = retry_result.exit_code
                    if (
                        retry_result.status != "BLOCKED"
                        and not retry_result.timed_out
                        and retry_exit_code is not None
                        and int(retry_exit_code) == 0
                    ):
                        status = "DONE"
                        message = "Tests passed"
                        out = retry_result.stdout
                        err = retry_result.stderr
                        exit_code = retry_result.exit_code
                        stack_mismatch_repairs = [
                            {
                                "status": "repaired",
                                "reason": stack_mismatch_reason,
                                "test_strategy_before": test_strategy,
                                "test_strategy_after": "vitest",
                                "repair_action": "reroute_to_npm_test",
                            }
                        ]
                        return {
                            "status": status,
                            "message": message,
                            "payload": {
                                "exit_code": exit_code,
                                "stdout": out,
                                "stderr": err,
                                "message": message,
                                "skip_reason": None,
                                "command_status": retry_result.status,
                                "command_audit_path": retry_result.audit_path,
                                "preview_probe_url": None,
                                "preview_probe_ok": None,
                                "preview_probe_detail": None,
                                "artifacts": artifacts,
                                "framework_router": "frontend_vite_vitest",
                                "test_strategy": "vitest",
                                "workspace_hydration_repairs": hydration_meta.get("workspace_hydration_repairs", []),
                                "frontend_dependency_repair_attempted": dependency_repair_attempted,
                                "frontend_dependency_repair_status": dependency_repair_status,
                                "stack_mismatch_detected": True,
                                "stack_mismatch_reason": stack_mismatch_reason,
                                "stack_mismatch_repairs": stack_mismatch_repairs,
                                "preview_workspace_consistency": hydration_meta.get("preview_workspace_consistency", "not_applicable"),
                            },
                        }
            stack_mismatch_repairs = (
                [
                    {
                        "status": "detected",
                        "reason": stack_mismatch_reason,
                        "test_strategy_before": test_strategy,
                        "test_strategy_after": "vitest" if framework_router == "frontend_vite_vitest" else test_strategy,
                    }
                ]
                if stack_mismatch_detected
                else []
            )
            composition_meta: dict[str, object] = {}
            if preview_stage or framework_validation_stage:
                composition_meta = validate_frontend_composition_integrity(
                    repo_root=repo_root,
                    payload=work_item.payload if isinstance(work_item.payload, dict) else {},
                    recovery_repairs=[
                        str(item)
                        for item in hydration_meta.get("workspace_hydration_repairs", [])
                        if isinstance(item, str)
                    ],
                )
                if status == "DONE" and not bool(composition_meta.get("composition_integrity_ok")):
                    status = "FAILED"
                    message = "Framework validation failed" if framework_validation_stage else "Preview validation failed"
            framework_validation_errors: list[str] = []
            if framework_validation_stage and status == "FAILED":
                compiler_output = "\n".join(part for part in (err, out) if isinstance(part, str))
                for line in compiler_output.splitlines():
                    if any(token in line.lower() for token in ("error", "failed to", "[plugin:vite:vue]", "vite:")):
                        framework_validation_errors.append(line.strip())
                if not framework_validation_errors and compiler_output.strip():
                    framework_validation_errors.append(compiler_output.strip()[:800])
            return {
                "status": status,
                "message": message,
                "payload": {
                    "exit_code": exit_code,
                    "stdout": out,
                    "stderr": err,
                    "message": message,
                    "skip_reason": "no_tests_collected" if no_tests_collected else None,
                    "command_status": result.status,
                    "command_audit_path": result.audit_path,
                    "preview_probe_url": preview_probe_url,
                    "preview_probe_ok": preview_probe_ok,
                    "preview_probe_detail": preview_probe_detail,
                    "artifacts": artifacts,
                    "framework_router": framework_router,
                    "test_strategy": test_strategy,
                    "workspace_hydration_repairs": hydration_meta.get("workspace_hydration_repairs", []),
                    "frontend_dependency_repair_attempted": dependency_repair_attempted,
                    "frontend_dependency_repair_status": dependency_repair_status,
                    "stack_mismatch_detected": stack_mismatch_detected,
                    "stack_mismatch_reason": stack_mismatch_reason,
                    "stack_mismatch_repairs": stack_mismatch_repairs,
                    "preview_workspace_consistency": hydration_meta.get("preview_workspace_consistency", "not_applicable"),
                    "framework_validation_errors": framework_validation_errors,
                    "syntax_repair_attempts": sum(
                        1
                        for item in hydration_meta.get("workspace_hydration_repairs", [])
                        if isinstance(item, str)
                        and (
                            "smart_quote_normalized" in item
                            or "runtime_shell_reconciled" in item
                            or "entrypoint_reconciled" in item
                        )
                    ),
                    "compiler_error_count": len(framework_validation_errors),
                    "convergence_after_repair": bool(
                        status == "DONE"
                        and framework_validation_stage
                        and any(
                            isinstance(item, str)
                            and (
                                "smart_quote_normalized" in item
                                or "runtime_shell_reconciled" in item
                                or "entrypoint_reconciled" in item
                            )
                            for item in hydration_meta.get("workspace_hydration_repairs", [])
                        )
                    ),
                    **composition_meta,
                },
            }
        except Exception as exc:
            return {
                "status": "FAILED",
                "message": f"Test executor error: {exc}",
                "payload": {},
            }
