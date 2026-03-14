from __future__ import annotations

import asyncio
import uuid

from app.db.models import (
    KnowledgeArtifact,
    KnowledgeChange,
    KnowledgeEvent,
    KnowledgeProposal,
    KnowledgePublication,
    KnowledgeReview,
    Project,
    ProjectRepository,
)
from app.db.session import SessionLocal


async def main() -> None:
    tenant_id = uuid.UUID(int=0)
    async with SessionLocal() as session:
        project = Project(name="Knowledge Demo", description="Demo project for knowledge verification UI", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        repo = ProjectRepository(
            tenant_id=tenant_id,
            project_id=project.id,
            provider="github",
            repo_url="https://github.com/example/knowledge-demo.git",
            repo_full_name="example/knowledge-demo",
            default_branch="main",
            created_by="seed-script",
        )
        session.add(repo)
        await session.flush()

        artifact = KnowledgeArtifact(
            tenant_id=tenant_id,
            project_id=project.id,
            repository_id=repo.id,
            artifact_type="runbook",
            artifact_key="operations",
            title="Operations Runbook",
            canonical_content="# Operations Runbook\n\n## Recent Verified Updates\n\n### Baseline\n\n- Seeded demo content.\n",
            current_version=1,
            last_verified_by="seed-script",
            status="active",
        )
        session.add(artifact)
        await session.flush()

        event = KnowledgeEvent(
            tenant_id=tenant_id,
            project_id=project.id,
            repository_id=repo.id,
            source_type="manual_sync",
            branch_name="main",
            commit_sha="seed-demo-commit",
            title="Seed knowledge verification demo",
            raw_payload_json={"seed": True},
            triggered_by="seed-script",
            status="proposed",
        )
        session.add(event)
        await session.flush()

        change = KnowledgeChange(
            knowledge_event_id=event.id,
            change_type="infra",
            summary="Operational automation changed and the runbook should be verified.",
            technical_summary="The seed event simulates deployment and environment workflow changes.",
            business_summary="Operators need a verified runbook update before treating the change as official knowledge.",
            risk_level="medium",
            confidence_score=0.82,
            impacts_runtime=True,
            impacts_docs=True,
            impacts_architecture=True,
            impacted_files=["infra/deploy/README.md", ".github/workflows/deploy.yml"],
            impacted_modules=["infra/deploy", ".github/workflows"],
            probable_artifacts=[{"artifact_type": "runbook", "artifact_key": "operations"}],
        )
        session.add(change)
        await session.flush()

        approved_proposal = KnowledgeProposal(
            tenant_id=tenant_id,
            project_id=project.id,
            repository_id=repo.id,
            knowledge_event_id=event.id,
            artifact_id=artifact.id,
            proposal_type="append",
            artifact_type="runbook",
            artifact_key="operations",
            artifact_title="Operations Runbook",
            target_section="Recent Verified Updates",
            generated_content=artifact.canonical_content,
            diff_preview="--- official\n+++ published\n",
            rationale="Historical approved publication for the demo artifact.",
            confidence_score=0.82,
            review_status="approved",
            created_by_agent="seed-script",
        )
        session.add(approved_proposal)
        await session.flush()

        session.add(
            KnowledgeReview(
                proposal_id=approved_proposal.id,
                reviewer_user_id="seed-script",
                action="approve",
                review_notes="Historical approved publication for the demo artifact.",
            )
        )

        publication = KnowledgePublication(
            proposal_id=approved_proposal.id,
            artifact_id=artifact.id,
            artifact_version=1,
            published_content=artifact.canonical_content,
            publication_mode="manual_publish",
            published_by="seed-script",
        )
        session.add(publication)

        proposal = KnowledgeProposal(
            tenant_id=tenant_id,
            project_id=project.id,
            repository_id=repo.id,
            knowledge_event_id=event.id,
            artifact_id=artifact.id,
            proposal_type="append",
            artifact_type="runbook",
            artifact_key="operations",
            artifact_title="Operations Runbook",
            target_section="Recent Verified Updates",
            generated_content=artifact.canonical_content
            + "\n### Seed follow-up\n\n- Deployment workflow now requires an explicit preview verification step.\n",
            diff_preview="--- official\n+++ proposed\n@@\n+### Seed follow-up\n+\n+- Deployment workflow now requires an explicit preview verification step.\n",
            rationale="Infra and workflow changes usually require a runbook verification step.",
            confidence_score=0.82,
            review_status="pending",
            created_by_agent="seed-script",
        )
        session.add(proposal)
        await session.flush()

        session.add(
            KnowledgeReview(
                proposal_id=proposal.id,
                reviewer_user_id="seed-script",
                action="defer",
                review_notes="Seeded pending proposal for UI review.",
            )
        )

        await session.commit()
        print(f"Seeded knowledge demo project={project.id} repo={repo.id} proposal={proposal.id}")


if __name__ == "__main__":
    asyncio.run(main())
