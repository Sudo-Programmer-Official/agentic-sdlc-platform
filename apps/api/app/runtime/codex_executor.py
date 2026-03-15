from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
import re

from app.db.models import Run, WorkItem
from app.db.session import SessionLocal
from app.runtime.executor import TaskExecutor, TaskResult
from app.runtime.context import RunContext
from app.runtime.patch_guard import (
    build_patch_guard_meta,
    derive_allowed_files,
    evaluate_patch_guard,
    has_mutating_actions,
)
from app.runtime.schemas.executor_io import CodexPlan
from app.runtime.llm.openai_client import OpenAIClient
from app.runtime.tools.repo_tools import RepoTools
from app.core.config import get_settings
from app.runtime.tools.redaction import SECRET_PATTERNS
from app.schemas.run_narrative import RunPatchVerificationSummary
from app.services.patch_verification import build_run_patch_plan_and_verification
from app.services.graph_context import EXECUTOR_CONTEXT_LIMITS, build_graph_context, compact_graph_context
from app.services.workspace_supervisor import workspace_uri
from app.services.ai_policy import AIJobManager, AIJobRequest, contains_sensitive_paths, estimate_tokens, is_retryable_error, retry_error_kind


SYSTEM_PROMPT = """You are an automated code change worker.
You must output ONLY a valid JSON object matching the provided schema.
Prefer apply_patch with unified diff (git format) for edits; use write_file for new files or full replacements.
Do not invent files outside the repo. Do not include explanations outside JSON."""

log = logging.getLogger("app.runtime.codex_executor")


class CodexExecutor(TaskExecutor):
    name = "codex"

    def __init__(self, repo_root: Path | None = None):
        self.settings = get_settings()
        self.repo_root = repo_root or Path.cwd()
        self._client: OpenAIClient | None = None
        self._job_manager = AIJobManager()
        # Simple heuristic caps for patch size
        self.max_patch_lines = 2000
        self.max_patch_files = 50
        self.max_patch_ratio_default = 0.4  # per file changed_lines / original_lines

    def _get_client(self) -> OpenAIClient:
        if self._client is None:
            self._client = OpenAIClient()
        return self._client

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        repo_root = Path(context.repo_path) if context.repo_path else self.repo_root
        self.repo_root = repo_root
        repo = RepoTools(repo_root, logs_path=Path(context.logs_path) if context.logs_path else None)
        payload = work_item.payload or {}
        task_id = payload.get("task_id") if isinstance(payload.get("task_id"), str) else None

        context_bundle = self._build_context(repo, work_item)
        context_bundle.setdefault("meta", {})
        allowed_files = derive_allowed_files(
            work_item_id=str(work_item.id),
            work_item_type=work_item.type,
            payload=work_item.payload,
            plan_snapshot=context.plan_snapshot,
        )
        context_bundle["meta"]["workspace"] = {
            "workspace_root": context.workspace_root,
            "repo_path": context.repo_path,
            "artifacts_path": context.artifacts_path,
            "logs_path": context.logs_path,
            "patches_path": context.patches_path,
            "branch_name": context.branch_name,
            "workspace_status": context.workspace_status,
            "simulation_mode": context.simulation_mode,
            "command_audit_path": context.command_audit_path,
            "cleanup_policy": context.cleanup_policy,
        }
        if isinstance(context.plan_snapshot, dict):
            context_bundle["meta"]["run_plan"] = {
                "goal": context.plan_snapshot.get("goal"),
                "rationale": context.plan_snapshot.get("rationale"),
                "validation_steps": context.plan_snapshot.get("validation_steps", []),
                "expected_files": context.plan_snapshot.get("expected_files", []),
                "steps": [
                    {
                        "title": step.get("title"),
                        "phase": step.get("phase"),
                        "success_criteria": step.get("success_criteria", []),
                    }
                    for step in context.plan_snapshot.get("steps", [])[:8]
                    if isinstance(step, dict)
                ],
            }
        context_bundle["meta"]["patch_guard"] = build_patch_guard_meta(context, allowed_files)
        graph_context = await self._load_graph_context(work_item)
        if graph_context:
            context_bundle["graph_context"] = graph_context
        job_request = self._build_ai_job_request(work_item, context_bundle, allowed_files)
        cache_context = await self._job_manager.load_cached_context_fragments(job_request)
        if cache_context.fragments:
            context_bundle["meta"]["cached_context"] = cache_context.fragments

        # Adaptive patch ratio based on stage
        ratio = self.max_patch_ratio_default
        if "PLAN" in work_item.type:
            ratio = 0.6
        if "FIX" in work_item.type:
            ratio = 0.25

        # Build minimal context (future: fetch relevant files)
        user_prompt = json.dumps(
            {
                "work_item": {
                    "id": str(work_item.id),
                    "type": work_item.type,
                    "key": work_item.key,
                    "payload": work_item.payload or {},
                    "required_capabilities": work_item.required_capabilities or [],
                },
                "instructions": self._instructions_for(work_item),
                "context_files": context_bundle.get("files", {}),
                "meta": context_bundle.get("meta", {}),
                "artifacts": context_bundle.get("artifacts", {}),
                "graph_context": context_bundle.get("graph_context"),
                "output_schema": CodexPlan.model_json_schema(),
            }
        )
        filters_used = ["diff_narrowing", "stack_trace_extraction", "path_hint_lookup", "graph_context_lookup"]
        if cache_context.fragments:
            filters_used.append("cache_lookup")
        prepared = await self._job_manager.prepare_job(
            job_request,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            filters_used=filters_used,
            cache_hit_count=cache_context.cache_hits,
            completion_token_estimate=self.settings.codex_max_tokens,
            block_on_human_review=True,
        )
        if prepared.stop_reason:
            log.warning(
                "AI execution blocked run_id=%s work_item_id=%s task_id=%s ai_job_id=%s work_item_type=%s tier=%s model=%s provider=%s stop_reason=%s next_action=%s",
                work_item.run_id,
                work_item.id,
                task_id,
                prepared.job_id,
                work_item.type,
                prepared.policy.selected_model_tier,
                prepared.model_name,
                self.settings.llm_provider,
                prepared.stop_reason,
                prepared.next_action,
            )
            return {
                "status": "FAILED",
                "message": prepared.stop_reason,
                "payload": {
                    "ai_job_id": str(prepared.job_id),
                    "next_action": prepared.next_action,
                    "estimated_cost_cents": prepared.estimated_cost_cents,
                    "context_size": prepared.context_size,
                    "run_id": str(work_item.run_id),
                    "work_item_id": str(work_item.id),
                    "task_id": task_id,
                    "provider": self.settings.llm_provider,
                    "model_name": prepared.model_name,
                    "selected_model_tier": prepared.policy.selected_model_tier,
                    "policy": self._policy_payload(prepared.policy),
                },
                "warnings": ["ai_policy_stop"],
            }

        plan: CodexPlan | None = None
        raw = ""
        usage: dict[str, Any] = {}
        current_user_prompt = user_prompt
        parse_retry_used = False
        client = self._get_client()
        log.info(
            "AI execution starting run_id=%s work_item_id=%s task_id=%s ai_job_id=%s work_item_type=%s tier=%s model=%s provider=%s client_method=%s openai_sdk_version=%s policy=%s",
            work_item.run_id,
            work_item.id,
            task_id,
            prepared.job_id,
            work_item.type,
            prepared.policy.selected_model_tier,
            prepared.model_name,
            self.settings.llm_provider,
            client.method_name(),
            client.sdk_version(),
            self._policy_payload(prepared.policy),
        )
        for attempt in range(prepared.policy.max_retries + 1):
            await self._job_manager.record_attempt(prepared.job_id)
            try:
                raw, usage = await client.generate(
                    SYSTEM_PROMPT,
                    current_user_prompt,
                    model=prepared.model_name or self.settings.codex_model,
                    temperature=self.settings.codex_temperature,
                    max_tokens=self.settings.codex_max_tokens,
                    timeout=self.settings.codex_timeout_seconds,
                )
                data = json.loads(raw)
                plan = CodexPlan.model_validate(data)
                break
            except Exception as exc:
                parse_failure = isinstance(exc, json.JSONDecodeError) or "validation" in exc.__class__.__name__.lower()
                if parse_failure and not parse_retry_used and attempt < prepared.policy.max_retries:
                    parse_retry_used = True
                    await self._job_manager.record_retry(prepared.job_id, "structured_parser_failure")
                    current_user_prompt = (
                        f"{user_prompt}\nYour previous output was invalid. Respond with EXACTLY one JSON object matching the schema. No prose."
                    )
                    continue
                error_kind = "structured_parser_failure" if parse_failure else retry_error_kind(exc)
                if not parse_failure and attempt < prepared.policy.max_retries and is_retryable_error(exc):
                    await self._job_manager.record_retry(prepared.job_id, error_kind)
                    await asyncio.sleep(min(2 ** attempt, 3))
                    continue
                failure_reason = "output_contract_invalid" if parse_failure else "model_call_failed"
                await self._job_manager.fail_job(
                    prepared.job_id,
                    reason=failure_reason,
                    next_action="Reduce scope, tighten context, or request human review before retrying.",
                    error_kind=error_kind,
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    details={
                        "error_message": str(exc),
                        "exception_type": exc.__class__.__name__,
                        "provider": self.settings.llm_provider,
                        "model_name": prepared.model_name or self.settings.codex_model,
                        "client_method": client.method_name(),
                        "openai_sdk_version": client.sdk_version(),
                        "selected_model_tier": prepared.policy.selected_model_tier,
                        "policy": self._policy_payload(prepared.policy),
                        "run_id": str(work_item.run_id),
                        "work_item_id": str(work_item.id),
                        "task_id": task_id,
                        "work_item_type": work_item.type,
                    },
                )
                log.exception(
                    "AI execution failed run_id=%s work_item_id=%s task_id=%s ai_job_id=%s work_item_type=%s tier=%s model=%s provider=%s client_method=%s openai_sdk_version=%s failure_reason=%s error_kind=%s",
                    work_item.run_id,
                    work_item.id,
                    task_id,
                    prepared.job_id,
                    work_item.type,
                    prepared.policy.selected_model_tier,
                    prepared.model_name,
                    self.settings.llm_provider,
                    client.method_name(),
                    client.sdk_version(),
                    failure_reason,
                    error_kind,
                    exc_info=exc,
                )
                return {
                    "status": "FAILED",
                    "message": f"AI policy halted execution: {failure_reason}",
                    "payload": {
                        "raw": raw,
                        "ai_job_id": str(prepared.job_id),
                        "next_action": "Reduce scope, tighten context, or request human review before retrying.",
                        "error_message": str(exc),
                        "exception_type": exc.__class__.__name__,
                        "error_kind": error_kind,
                        "run_id": str(work_item.run_id),
                        "work_item_id": str(work_item.id),
                        "task_id": task_id,
                        "work_item_type": work_item.type,
                        "provider": self.settings.llm_provider,
                        "model_name": prepared.model_name or self.settings.codex_model,
                        "client_method": client.method_name(),
                        "openai_sdk_version": client.sdk_version(),
                        "selected_model_tier": prepared.policy.selected_model_tier,
                        "policy": self._policy_payload(prepared.policy),
                    },
                    "warnings": ["ai_policy_stop"],
                }

        if plan is None:
            return {
                "status": "FAILED",
                "message": "ai_plan_missing",
                "payload": {"ai_job_id": str(prepared.job_id)},
                "warnings": ["ai_policy_stop"],
            }

        usage_input_tokens = int(usage.get("input_tokens") or estimate_tokens(SYSTEM_PROMPT + current_user_prompt))
        usage_output_tokens = int(usage.get("output_tokens") or estimate_tokens(raw))
        if plan.confidence is not None and plan.confidence < self.settings.ai_low_confidence_threshold:
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="low_confidence_output",
                next_action="Narrow the file set or request human review before applying the patch.",
                error_kind="low_confidence_reasoning",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                approval_state="pending",
                status="blocked",
                details={"confidence": plan.confidence},
            )
            return {
                "status": "FAILED",
                "message": "low_confidence_output",
                "payload": {
                    "confidence": plan.confidence,
                    "ai_job_id": str(prepared.job_id),
                    "next_action": "Narrow the file set or request human review before applying the patch.",
                },
                "warnings": ["requires_confirmation"],
            }

        patch_guard = evaluate_patch_guard(actions=plan.actions, allowed_files=allowed_files)
        verification = await self._load_patch_verification(work_item, context)
        if verification and verification.requires_confirmation and has_mutating_actions(plan.actions):
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="human_review_required",
                next_action="Confirm the patch plan before allowing mutating actions.",
                error_kind="human_review_required",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                approval_state="pending",
                status="blocked",
                details={"verification": verification.model_dump()},
            )
            return {
                "status": "FAILED",
                "message": "Patch execution requires operator confirmation before mutating the repository.",
                "payload": {
                    "actions": [a.model_dump() for a in plan.actions],
                    "verification": verification.model_dump(),
                    "touched_files": patch_guard.touched_files,
                },
                "warnings": ["requires_confirmation"],
            }
        if not patch_guard.ok:
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="patch_guard_violation",
                next_action="Reduce the touched file set or adjust the scoped plan before retrying.",
                error_kind="patch_guard_violation",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                details={"violations": patch_guard.violations},
            )
            return {
                "status": "FAILED",
                "message": "; ".join(patch_guard.violations),
                "payload": {
                    "actions": [a.model_dump() for a in plan.actions],
                    "allowed_files": patch_guard.allowed_files,
                    "touched_files": patch_guard.touched_files,
                },
                "warnings": ["patch_guard_violation"],
            }

        # Apply actions
        total_written = 0
        try:
            for act in plan.actions:
                if act.type == "write_file":
                    if not act.path or act.content is None:
                        raise ValueError("write_file requires path and content")
                    # output redaction check
                    for pat in SECRET_PATTERNS:
                        if pat.lower() in act.content.lower():
                            raise ValueError("secret_pattern_detected_in_output")
                    b = act.content.encode()
                    total_written += len(b)
                    if total_written > self.settings.codex_max_write_bytes_total:
                        raise ValueError("Write exceeds max total bytes")
                    repo.write_file(act.path, act.content)
                elif act.type == "delete_file":
                    if not act.path:
                        raise ValueError("delete_file requires path")
                    repo.delete_file(act.path)
                elif act.type == "apply_patch":
                    if not act.patch:
                        raise ValueError("apply_patch requires patch")
                    lower_patch = act.patch.lower()
                    for pat in SECRET_PATTERNS:
                        if pat.lower() in lower_patch:
                            raise ValueError("secret_pattern_detected_in_output")
                    b = act.patch.encode()
                    total_written += len(b)
                    if total_written > self.settings.codex_max_write_bytes_total:
                        raise ValueError("Write exceeds max total bytes")
                    # Heuristic guard: file count, line count, per-file change ratio
                    file_headers = [ln for ln in act.patch.splitlines() if ln.startswith("diff --git")]
                    if len(file_headers) > self.max_patch_files:
                        raise ValueError("Patch touches too many files")
                    changed_lines = sum(1 for ln in act.patch.splitlines() if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")))
                    if changed_lines > self.max_patch_lines:
                        raise ValueError("Patch changes too many lines")
                    per_file_changes = self._parse_patch_changes(act.patch)
                    for rel_path, delta_lines in per_file_changes.items():
                        orig_lines = self._file_line_count(rel_path)
                        if orig_lines and delta_lines / orig_lines > ratio:
                            raise ValueError(f"Patch too large for {rel_path} (>{int(ratio*100)}% change)")
                    repo.apply_patch(act.patch)
                elif act.type == "note":
                    continue
        except Exception as exc:
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="action_error",
                next_action="Inspect the generated patch and rerun with a narrower scope.",
                error_kind="action_error",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                details={"error": str(exc)},
            )
            return {
                "status": "FAILED",
                "message": f"Action error: {exc}",
                "payload": {"actions": [a.model_dump() for a in plan.actions]},
            }

        # Budget enforcement
        total_tokens = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        if total_tokens and total_tokens > self.settings.codex_max_run_tokens:
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="run_budget_exceeded",
                next_action="Reduce context or split the work item before retrying.",
                error_kind="run_budget_exceeded",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
            )
            return {
                "status": "FAILED",
                "message": "run_budget_exceeded",
                "payload": {"usage": usage},
            }

        diff = repo.git_diff()
        artifacts = [a.model_dump() for a in plan.artifacts]
        if diff:
            if context.patches_path:
                patch_dir = Path(context.patches_path)
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_name = f"{work_item.type.lower()}-{work_item.id}.patch"
                patch_path = patch_dir / patch_name
                patch_path.write_text(diff, encoding="utf-8")
                artifacts.append(
                    {
                        "type": "git_diff",
                        "uri": workspace_uri("patches", patch_name),
                        "path": str(patch_path),
                        "content": diff,
                    }
                )
            else:
                artifacts.append({"type": "git_diff", "content": diff})

        # Save review metrics / patch stats
        review_metrics = {}
        if plan.risk_score is not None:
            review_metrics["risk_score"] = plan.risk_score
        if plan.confidence is not None:
            review_metrics["confidence"] = plan.confidence
        if plan.patch_complexity is not None:
            review_metrics["patch_complexity"] = plan.patch_complexity
        if 'git_diff' in {a["type"] for a in artifacts}:
            review_metrics["patch_lines"] = changed_lines if 'changed_lines' in locals() else None
        final_status = "completed" if plan.status in {"DONE", "SKIPPED"} else "failed"
        if final_status == "completed":
            await self._job_manager.complete_job(
                prepared.job_id,
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                confidence_score=plan.confidence,
                details={"review_metrics": review_metrics, "warnings": plan.warnings},
                status=final_status,
            )
        else:
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="model_reported_failure",
                next_action="Inspect the returned plan and rerun with narrower context.",
                error_kind="model_reported_failure",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                details={"review_metrics": review_metrics, "warnings": plan.warnings},
            )

        return {
            "status": plan.status,
            "message": plan.message,
            "payload": {
                "artifacts": artifacts,
                "warnings": plan.warnings,
                "ai_job_id": str(prepared.job_id),
                "ai_selected_tier": prepared.policy.selected_model_tier,
                "ai_policy": self._policy_payload(prepared.policy),
                "patch_guard": {
                    "allowed_files": patch_guard.allowed_files,
                    "touched_files": patch_guard.touched_files,
                    "file_budget": patch_guard.file_budget,
                    "hard_file_budget": patch_guard.hard_file_budget,
                },
                "review": review_metrics,
                "usage": usage,
            },
        }

    def _parse_patch_changes(self, patch: str) -> dict[str, int]:
        """
        Returns mapping of rel_path -> changed lines (add+del) from a unified diff.
        """
        changes: dict[str, int] = {}
        current: str | None = None
        for line in patch.splitlines():
            if line.startswith("+++ "):
                path = line.split(maxsplit=1)[1]
                if path.strip() == "/dev/null":
                    current = None
                    continue
                # strip leading a/ or b/
                if path.startswith("+++ b/"):
                    path = path[6:]
                elif path.startswith("+++ a/"):
                    path = path[6:]
                else:
                    path = path[4:]
                current = path.strip()
                changes.setdefault(current, 0)
                continue
            if line.startswith("diff --git"):
                # new file header will be handled on +++ line
                continue
            if current and line and line[0] in {"+", "-"} and not line.startswith(("+++", "---")):
                changes[current] = changes.get(current, 0) + 1
        return changes

    def _file_line_count(self, rel_path: str) -> int:
        p = (self.repo_root / rel_path).resolve()
        if not str(p).startswith(str(self.repo_root)):
            raise ValueError("Path escapes repo root")
        if not p.exists() or not p.is_file():
            return 0
        try:
            return len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            return 0

    def _build_context(self, repo: RepoTools, work_item: WorkItem) -> dict[str, Any]:
        """
        Deterministic minimal context selection.
        Priority:
        1) files referenced in latest diff artifact (if present)
        2) failing test file (from payload stderr/stdout)
        3) explicit paths in payload (files/paths/target_file)
        4) depth-1 local imports of already selected files
        5) small project metadata (pyproject/requirements/package.json)
        Capped by codex_max_context_bytes.
        Capped by codex_max_context_bytes.
        """
        max_bytes = self.settings.codex_max_context_bytes
        files: dict[str, str] = {}
        seen: set[str] = set()
        artifacts: dict[str, str] = {}

        def add_paths(paths: list[str]):
            nonlocal max_bytes
            new_paths = [p for p in paths if p and p not in seen]
            if not new_paths or max_bytes <= 0:
                return
            chunk = repo.read_files(new_paths, max_bytes)
            for k, v in chunk.items():
                if max_bytes <= 0:
                    break
                files[k] = v
                seen.add(k)
                max_bytes -= len(v.encode())

        payload = work_item.payload or {}

        # 1) Diff artifact file paths (highest priority for fixes)
        diff_art = None
        if isinstance(payload.get("artifacts"), list):
            for art in payload["artifacts"]:
                if not isinstance(art, dict):
                    continue
                if art.get("type") in {"git_diff", "diff_summary"} and isinstance(art.get("content"), str):
                    artifacts[art["type"]] = art["content"]
                    diff_art = art["content"]
                    break
        if diff_art:
            diff_paths = self._paths_from_diff(diff_art)
            add_paths(diff_paths)

        # 2) Failing test file from stderr/stdout stack traces
        payload = work_item.payload or {}
        err_text = (payload.get("stderr") or "") + "\n" + (payload.get("stdout") or "")
        stack_paths = re.findall(r'File "([^"]+)"', err_text)
        add_paths(stack_paths)

        # 3) Explicit paths from payload hints
        for key in ["file", "filepath", "path", "target_file"]:
            val = payload.get(key)
            if isinstance(val, str):
                add_paths([val])
            if isinstance(val, list):
                add_paths([x for x in val if isinstance(x, str)])
        if isinstance(payload.get("files"), list):
            add_paths([x for x in payload["files"] if isinstance(x, str)])

        # 4) Depth-1 local imports from already added Python files
        import_candidates = [p for p in list(files.keys()) if p.endswith(".py")]
        resolved_imports: list[str] = []
        for path in import_candidates:
            try:
                content = files[path]
            except KeyError:
                continue
            for imp in re.findall(r"^(?:from|import) ([\\w\\.]+)", content, flags=re.MULTILINE):
                resolved = self._resolve_local_import(imp)
                if resolved:
                    resolved_imports.append(resolved)
        add_paths(resolved_imports)

        # 5) Small project metadata (lowest priority)
        add_paths(
            [
                "pyproject.toml",
                "requirements.txt",
                "package.json",
                "poetry.lock",
                "README.md",
            ]
        )

        return {
            "files": files,
            "meta": {
                "context_bytes": self.settings.codex_max_context_bytes - max_bytes,
                "artifact_types": list(artifacts.keys()),
            },
            "artifacts": artifacts,
        }

    async def _load_graph_context(self, work_item: WorkItem) -> dict[str, Any] | None:
        try:
            async with SessionLocal() as session:
                context = await build_graph_context(
                    session,
                    entity_type="work_item",
                    entity_id=work_item.id,
                    project_id=work_item.project_id,
                    max_depth=EXECUTOR_CONTEXT_LIMITS.max_depth,
                    limits=EXECUTOR_CONTEXT_LIMITS,
                )
            return compact_graph_context(context)
        except Exception:
            return None

    async def _load_patch_verification(
        self,
        work_item: WorkItem,
        context: RunContext,
    ) -> RunPatchVerificationSummary | None:
        plan_snapshot = context.plan_snapshot if isinstance(context.plan_snapshot, dict) else {}
        planned_files = [
            path
            for path in plan_snapshot.get("expected_files", [])
            if isinstance(path, str) and path.strip()
        ]
        planned_steps = [
            step.get("title")
            for step in plan_snapshot.get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("title"), str) and step.get("title").strip()
        ]
        goal = plan_snapshot.get("goal")
        confidence_score = plan_snapshot.get("confidence_score")
        try:
            async with SessionLocal() as session:
                run = await session.get(Run, context.run_id)
                if run is None:
                    return None
                _, verification = await build_run_patch_plan_and_verification(
                    session,
                    tenant_id=work_item.tenant_id,
                    run=run,
                    goal=goal if isinstance(goal, str) and goal.strip() else None,
                    planned_steps=planned_steps,
                    planned_files=planned_files,
                    confidence_score=confidence_score if isinstance(confidence_score, (int, float)) else None,
                )
                return verification
        except Exception:
            return None

    def _resolve_local_import(self, module: str) -> str | None:
        """
        Resolve a python module string to a relative file path if it exists in repo root.
        Only depth-1 (no recursion).
        """
        candidate = module.replace(".", "/") + ".py"
        p = (self.repo_root / candidate).resolve()
        if str(p).startswith(str(self.repo_root)) and p.exists() and p.is_file():
            # return relative path from repo root
            return str(p.relative_to(self.repo_root))
        return None

    def _paths_from_diff(self, diff: str) -> list[str]:
        paths: list[str] = []
        for line in diff.splitlines():
            if line.startswith("+++ "):
                path = line.split(maxsplit=1)[1]
                if path.strip() == "/dev/null":
                    continue
                if path.startswith("+++ b/"):
                    path = path[6:]
                elif path.startswith("+++ a/"):
                    path = path[6:]
                else:
                    path = path[4:]
                paths.append(path.strip())
        return paths

    def _instructions_for(self, work_item: WorkItem) -> str:
        base = (
            "Produce JSON per schema. Prefer apply_patch with unified diff. "
            "Use write_file for new files or complete replacements. Keep changes minimal."
        )
        if work_item.type == "FIX_TEST_FAILURE":
            return (
                base
                + " You are fixing failing tests. Use the failing stack info and previous diff. "
                  "Make the smallest possible patch that addresses the failure; avoid broad refactors."
            )
        if "PLAN" in work_item.type:
            return base + " You may propose broader changes here, but still minimize diff where possible."
        return base

    def _build_ai_job_request(self, work_item: WorkItem, context_bundle: dict[str, Any], allowed_files: list[str]) -> AIJobRequest:
        candidate_paths = self._candidate_paths(work_item, context_bundle, allowed_files)
        risk_level = self._risk_level_for_work_item(work_item, candidate_paths)
        if "PLAN" in work_item.type:
            role = "planner"
            task_type = "planning"
            ambiguity = "high"
            workflow_type = "interactive_planning"
        elif work_item.type in {"REVIEW_DIFF", "REVIEW_INTEGRATION"}:
            role = "reviewer"
            task_type = "review"
            ambiguity = "high" if risk_level == "high" else "medium"
            workflow_type = "pr_review"
        elif work_item.type == "FIX_TEST_FAILURE":
            role = "coder"
            task_type = "bugfix"
            ambiguity = "medium"
            workflow_type = "repo_implementation_task"
        elif work_item.type in {"WRITE_TESTS", "RUN_TESTS"}:
            role = "coder"
            task_type = "testing"
            ambiguity = "medium"
            workflow_type = "repo_implementation_task"
        else:
            role = "coder"
            task_type = "implementation"
            ambiguity = "medium"
            workflow_type = "repo_implementation_task"
        return AIJobRequest(
            workflow_type=workflow_type,
            role=role,
            task_type=task_type,
            ambiguity_level=ambiguity,
            risk_level=risk_level,
            tenant_id=work_item.tenant_id,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            changed_files=candidate_paths,
            tests_failed=work_item.type == "FIX_TEST_FAILURE",
            metadata={"work_item_type": work_item.type, "work_item_key": work_item.key},
        )

    def _candidate_paths(self, work_item: WorkItem, context_bundle: dict[str, Any], allowed_files: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def add(paths: list[str]) -> None:
            for path in paths:
                cleaned = (path or "").strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                ordered.append(cleaned)

        add(list(context_bundle.get("files", {}).keys()))
        add(allowed_files)
        payload = work_item.payload or {}
        for key in ("file", "filepath", "path", "target_file"):
            value = payload.get(key)
            if isinstance(value, str):
                add([value])
            elif isinstance(value, list):
                add([item for item in value if isinstance(item, str)])
        if isinstance(payload.get("files"), list):
            add([item for item in payload["files"] if isinstance(item, str)])
        artifacts = context_bundle.get("artifacts", {})
        diff_content = artifacts.get("git_diff") or artifacts.get("diff_summary")
        if isinstance(diff_content, str):
            add(self._paths_from_diff(diff_content))
        return ordered[:12]

    def _risk_level_for_work_item(self, work_item: WorkItem, candidate_paths: list[str]) -> str:
        if contains_sensitive_paths(candidate_paths) or work_item.type == "REVIEW_INTEGRATION":
            return "high"
        if work_item.type in {"CODE_BACKEND", "CODE_FRONTEND", "FIX_TEST_FAILURE", "REVIEW_DIFF"} or len(candidate_paths) >= 4:
            return "medium"
        return "low"

    @staticmethod
    def _policy_payload(policy) -> dict[str, Any]:
        return {
            "task_type": policy.task_type,
            "ambiguity_level": policy.ambiguity_level,
            "risk_level": policy.risk_level,
            "max_model_tier": policy.max_model_tier,
            "max_retries": policy.max_retries,
            "max_context_tokens": policy.max_context_tokens,
            "budget_cents": policy.budget_cents,
            "requires_human_review": policy.requires_human_review,
        }
