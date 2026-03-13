from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, Run
from app.schemas.artifact_diff import ArtifactDiffFile, ArtifactDiffResponse


def resolve_artifact_content(run: Run | None, artifact: Artifact) -> str | None:
    metadata = artifact.extra_metadata or {}
    content = metadata.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if artifact.uri.startswith("workspace://patches/") and run and run.workspace_root:
        patch_name = artifact.uri.removeprefix("workspace://patches/")
        patch_path = Path(run.workspace_root) / "patches" / patch_name
        if patch_path.exists():
            try:
                return patch_path.read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def parse_unified_diff(diff: str) -> tuple[list[ArtifactDiffFile], int, int]:
    files: list[ArtifactDiffFile] = []
    current: dict | None = None

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return
        files.append(
            ArtifactDiffFile(
                path=current["path"],
                old_path=current["old_path"],
                new_path=current["new_path"],
                additions=current["additions"],
                deletions=current["deletions"],
                patch="\n".join(current["patch"]).strip(),
            )
        )
        current = None

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            flush_current()
            current = {
                "path": "",
                "old_path": None,
                "new_path": None,
                "additions": 0,
                "deletions": 0,
                "patch": [line],
            }
            continue

        if current is None:
            continue

        current["patch"].append(line)
        if line.startswith("--- "):
            old_path = line.split(maxsplit=1)[1].strip()
            current["old_path"] = None if old_path == "/dev/null" else old_path.removeprefix("a/")
        elif line.startswith("+++ "):
            new_path = line.split(maxsplit=1)[1].strip()
            current["new_path"] = None if new_path == "/dev/null" else new_path.removeprefix("b/")
            current["path"] = current["new_path"] or current["old_path"] or ""
        elif line.startswith("+") and not line.startswith("+++"):
            current["additions"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            current["deletions"] += 1

    flush_current()
    additions = sum(file.additions for file in files)
    deletions = sum(file.deletions for file in files)
    return files, additions, deletions


async def build_artifact_diff_preview(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> ArtifactDiffResponse:
    artifact = await session.get(Artifact, artifact_id)
    if not artifact or artifact.project_id != project_id or artifact.deleted_at:
        raise ValueError("Artifact not found")
    if artifact.type != "git_diff":
        raise ValueError("Artifact does not contain a git diff preview")

    run = await session.get(Run, artifact.run_id) if artifact.run_id else None
    diff = resolve_artifact_content(run, artifact)
    if not diff:
        raise ValueError("Artifact diff content is not available")

    files, additions, deletions = parse_unified_diff(diff)
    return ArtifactDiffResponse(
        artifact_id=artifact.id,
        project_id=artifact.project_id,
        run_id=artifact.run_id,
        work_item_id=artifact.work_item_id,
        artifact_type=artifact.type,
        uri=artifact.uri,
        created_at=artifact.created_at,
        file_count=len(files),
        additions=additions,
        deletions=deletions,
        files=files,
    )
