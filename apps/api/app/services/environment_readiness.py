from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class ChecklistTemplateItem:
    environment: str
    item_key: str
    label: str
    owner: str
    category: str
    required: bool = True
    note: str | None = None


def checklist_template() -> list[ChecklistTemplateItem]:
    return [
        ChecklistTemplateItem("PREVIEW", "preview.runtime", "Preview runtime orchestration", "platform", "runtime"),
        ChecklistTemplateItem("PREVIEW", "preview.domain", "Temporary preview URL provisioning", "platform", "deployment"),
        ChecklistTemplateItem("PREVIEW", "preview.recovery", "Preview recovery and restart", "platform", "recovery"),
        ChecklistTemplateItem("PREVIEW", "preview.provider", "Connect deployment provider (Vercel/Render)", "user", "deployment"),
        ChecklistTemplateItem("PREVIEW", "preview.repo", "Connect repository for deployment bootstrap", "user", "deployment"),
        ChecklistTemplateItem("STAGING", "staging.orchestration", "Staging deployment orchestration", "platform", "deployment"),
        ChecklistTemplateItem("STAGING", "staging.rollback", "Rollback workflow available", "platform", "recovery"),
        ChecklistTemplateItem("STAGING", "staging.secrets", "Provide staging environment secrets", "user", "secrets"),
        ChecklistTemplateItem("STAGING", "staging.auth", "Configure staging auth callbacks/domains", "user", "auth"),
        ChecklistTemplateItem("PRODUCTION", "production.governance", "Promotion and deployment governance", "platform", "governance"),
        ChecklistTemplateItem("PRODUCTION", "production.recovery", "Rollback and recovery orchestration", "platform", "recovery"),
        ChecklistTemplateItem("PRODUCTION", "production.domain", "Configure custom domain and DNS", "user", "deployment"),
        ChecklistTemplateItem("PRODUCTION", "production.secrets", "Set production secrets", "user", "secrets"),
        ChecklistTemplateItem("PRODUCTION", "production.monitoring", "Enable production monitoring", "user", "operations"),
        ChecklistTemplateItem("PRODUCTION", "production.backup", "Define backup and restore policy", "user", "operations"),
    ]


def infer_item_status(
    template: ChecklistTemplateItem,
    *,
    has_repo: bool,
    has_connector: bool,
    preview_ready: bool,
    foundation_missing: set[str],
) -> tuple[str, str | None]:
    key = template.item_key
    if template.owner == "platform":
        if key == "preview.runtime" and not preview_ready:
            return "pending", "No healthy preview run verified yet."
        return "done", None

    if key.endswith("provider"):
        return ("done", None) if has_connector else ("pending", "Connect Vercel or Render provider.")
    if key.endswith("repo"):
        return ("done", None) if has_repo else ("pending", "Repository must be connected.")
    if "auth" in key and any("auth" in item for item in foundation_missing):
        return "pending", "Auth prerequisites are incomplete."
    if "secrets" in key and any(item in foundation_missing for item in {"architecture", "repo", "preview"}):
        return "pending", "Foundation prerequisites should be completed before secrets handoff."
    if key in {"production.monitoring", "production.backup"}:
        return "pending", template.note or "User action required for production operations."
    return "done", None


def complete_timestamp(status: str) -> datetime | None:
    if status != "done":
        return None
    return datetime.now(timezone.utc)


def normalize_missing_prerequisites(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    return {str(value or "").strip().lower() for value in values if str(value or "").strip()}


def summarize_rows(rows: list[Any]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for env in ("PREVIEW", "STAGING", "PRODUCTION"):
        grouped[env] = {
            "environment": env,
            "total": 0,
            "completed": 0,
            "platform_total": 0,
            "platform_completed": 0,
            "user_pending": 0,
        }
    for row in rows:
        env = str(getattr(row, "environment", "")).upper()
        if env not in grouped:
            grouped[env] = {
                "environment": env,
                "total": 0,
                "completed": 0,
                "platform_total": 0,
                "platform_completed": 0,
                "user_pending": 0,
            }
        bucket = grouped[env]
        owner = str(getattr(row, "owner", "user")).lower()
        status = str(getattr(row, "status", "pending")).lower()
        bucket["total"] += 1
        if status == "done":
            bucket["completed"] += 1
        if owner == "platform":
            bucket["platform_total"] += 1
            if status == "done":
                bucket["platform_completed"] += 1
        if owner == "user" and status != "done":
            bucket["user_pending"] += 1

    envs = []
    total = 0
    completed = 0
    for env in ("PREVIEW", "STAGING", "PRODUCTION"):
        bucket = grouped[env]
        bucket_total = bucket["total"]
        bucket["score_pct"] = int(round((bucket["completed"] / bucket_total) * 100)) if bucket_total else 0
        total += bucket_total
        completed += bucket["completed"]
        envs.append(bucket)
    score_pct = int(round((completed / total) * 100)) if total else 0
    return {
        "score_pct": score_pct,
        "environments": envs,
        "total": total,
        "completed": completed,
    }
