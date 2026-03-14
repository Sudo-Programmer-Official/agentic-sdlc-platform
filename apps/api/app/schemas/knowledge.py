from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class KnowledgeManualSyncRequest(BaseModel):
    project_id: uuid.UUID
    title: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None


class KnowledgeDecisionRequest(BaseModel):
    review_notes: str | None = None


class KnowledgeEditApproveRequest(KnowledgeDecisionRequest):
    edited_content: str = Field(min_length=1)


class KnowledgeReviewOut(BaseModel):
    id: uuid.UUID
    proposal_id: uuid.UUID
    reviewer_user_id: str
    action: str
    review_notes: str | None = None
    edited_content: str | None = None
    created_at: datetime


class KnowledgePublicationOut(BaseModel):
    id: uuid.UUID
    proposal_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_version: int
    published_content: str
    publication_mode: str
    published_by: str | None = None
    published_at: datetime


class KnowledgeArtifactSummaryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    repository_id: uuid.UUID
    repo_full_name: str | None = None
    artifact_type: str
    artifact_key: str
    title: str
    canonical_content: str
    current_version: int
    last_verified_at: datetime | None = None
    last_verified_by: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class KnowledgeChangeOut(BaseModel):
    id: uuid.UUID
    change_type: str
    summary: str
    technical_summary: str
    business_summary: str
    risk_level: str
    confidence_score: float
    impacts_runtime: bool
    impacts_api: bool
    impacts_schema: bool
    impacts_docs: bool
    impacts_architecture: bool
    impacts_onboarding: bool
    impacted_files: list[str]
    impacted_modules: list[str]
    probable_artifacts: list[dict[str, Any]]
    created_at: datetime


class KnowledgeEventSummaryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    repository_id: uuid.UUID
    repo_full_name: str | None = None
    source_type: str
    source_external_id: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_number: int | None = None
    title: str | None = None
    triggered_by: str | None = None
    detected_at: datetime
    analyzed_at: datetime | None = None
    status: str


class KnowledgeProposalSummaryOut(BaseModel):
    id: uuid.UUID
    knowledge_event_id: uuid.UUID
    artifact_id: uuid.UUID | None = None
    proposal_type: str
    artifact_type: str
    artifact_key: str
    artifact_title: str
    target_section: str | None = None
    confidence_score: float
    review_status: str
    created_by_agent: str
    created_at: datetime
    updated_at: datetime


class KnowledgeInboxItemOut(BaseModel):
    proposal_id: uuid.UUID
    event_id: uuid.UUID
    artifact_id: uuid.UUID | None = None
    project_id: uuid.UUID
    repository_id: uuid.UUID
    repo_full_name: str | None = None
    event_title: str | None = None
    source_type: str
    impacted_modules: list[str] = Field(default_factory=list)
    proposal_target: str
    artifact_type: str
    change_type: str
    confidence_score: float
    risk_level: str
    created_at: datetime
    review_status: str
    detected_at: datetime


class KnowledgeProposalDetailOut(KnowledgeProposalSummaryOut):
    event: KnowledgeEventSummaryOut
    change: KnowledgeChangeOut | None = None
    current_canonical_content: str = ""
    generated_content: str
    diff_preview: str
    rationale: str
    reviews: list[KnowledgeReviewOut] = Field(default_factory=list)
    publication: KnowledgePublicationOut | None = None
    raw_payload_json: dict[str, Any] | None = None


class KnowledgeArtifactHistoryItemOut(BaseModel):
    proposal: KnowledgeProposalSummaryOut
    reviews: list[KnowledgeReviewOut] = Field(default_factory=list)
    publication: KnowledgePublicationOut | None = None


class KnowledgeArtifactDetailOut(KnowledgeArtifactSummaryOut):
    history: list[KnowledgeArtifactHistoryItemOut] = Field(default_factory=list)


class KnowledgeEventDetailOut(KnowledgeEventSummaryOut):
    raw_payload_json: dict[str, Any] | None = None
    change: KnowledgeChangeOut | None = None
    proposals: list[KnowledgeProposalSummaryOut] = Field(default_factory=list)


class KnowledgeSearchHookOut(BaseModel):
    artifact_id: uuid.UUID
    artifact_key: str
    title: str
    official_only: bool = True
    search_text: str


class KnowledgeTriggerResponse(BaseModel):
    event: KnowledgeEventSummaryOut
    proposals_created: int = 0
    queued: bool = True
    inline_processed: bool = False


class KnowledgeInboxResponse(BaseModel):
    items: list[KnowledgeInboxItemOut]
    total: int


class KnowledgeProposalListResponse(BaseModel):
    items: list[KnowledgeProposalSummaryOut]
    total: int


class KnowledgeArtifactListResponse(BaseModel):
    items: list[KnowledgeArtifactSummaryOut]
    total: int


class KnowledgeSearchHookListResponse(BaseModel):
    items: list[KnowledgeSearchHookOut]
    total: int
