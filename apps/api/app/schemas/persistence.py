from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


TaskBranchStrategy = Literal["auto", "new", "existing"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    status: str
    allowed_transitions: list[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentCreate(BaseModel):
    type: str
    title: str
    body: str = Field(validation_alias=AliasChoices("body", "content"))
    source: str = "manual"
    created_by: Optional[str] = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    type: str
    version: int
    title: str
    body: str
    source: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "func"
    stage: str = "PLAN"
    status: str = "PENDING"
    assignee: Optional[str] = None
    source: str = "manual"
    document_id: Optional[uuid.UUID] = None
    created_by: Optional[str] = None
    branch_strategy: TaskBranchStrategy = "auto"
    base_branch: Optional[str] = None
    branch_name: Optional[str] = None

    @field_validator("branch_strategy", mode="before")
    @classmethod
    def normalize_branch_strategy(cls, value: str | None) -> str:
        return (value or "auto").strip().lower()

    @field_validator("base_branch", "branch_name", mode="before")
    @classmethod
    def normalize_branch_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_branch_settings(self) -> "TaskCreate":
        if self.branch_strategy == "auto":
            self.base_branch = None
            self.branch_name = None
            return self

        if not self.branch_name:
            raise ValueError("branch_name is required when branch_strategy is 'new' or 'existing'")

        if self.branch_strategy == "existing":
            self.base_branch = None

        return self


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID]
    generated_from_document_version: Optional[int]
    title: str
    description: Optional[str]
    category: str
    stage: str
    status: str
    assignee: Optional[str]
    source: str
    created_by: Optional[str]
    branch_strategy: TaskBranchStrategy = "auto"
    base_branch: Optional[str]
    branch_name: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    executor: str
    workspace_root: Optional[str] = None
    repo_path: Optional[str] = None
    branch_name: Optional[str] = None
    workspace_status: str = "PENDING"
    workspace_error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    summary: Optional[dict] = None
    allowed_transitions: list[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunCreate(BaseModel):
    executor: str = "dummy"
    task_id: Optional[uuid.UUID] = None


class ProjectRepositoryConnect(BaseModel):
    provider: str = "github"
    repo_url: str
    repo_full_name: Optional[str] = None
    default_branch: str = "main"
    installation_id: Optional[int] = None
    auth_strategy: str = "runtime_default"
    created_by: Optional[str] = None


class ProjectRepositoryPreflightRequest(BaseModel):
    provider: str = "github"
    repo_url: Optional[str] = None
    repo_full_name: Optional[str] = None
    default_branch: Optional[str] = None
    installation_id: Optional[int] = None
    auth_strategy: Optional[str] = None
    clone: bool = True


class ProjectRepositoryPreflightOut(BaseModel):
    ok: bool
    provider: str
    auth_strategy: str
    auth_mode: Optional[str] = None
    credential_strategy: Optional[str] = None
    selection_reason: Optional[str] = None
    transport_url: Optional[str] = None
    repo_url: str
    default_branch: str
    installation_id: Optional[int] = None
    token_generated: bool = False
    git_binary: Optional[str] = None
    error: Optional[str] = None


class ProjectRepositoryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    repo_url: str
    repo_full_name: Optional[str]
    default_branch: str
    installation_id: Optional[int]
    auth_strategy: str = "runtime_default"
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GitHubConnectInfoOut(BaseModel):
    enabled: bool
    app_slug: Optional[str] = None
    allowed_org: Optional[str] = None
    install_url: Optional[str] = None
    runtime_git_auth_mode: str = "auto"


class GitHubInstallationRepositoryOut(BaseModel):
    id: int
    name: str
    full_name: str
    clone_url: Optional[str] = None
    ssh_url: Optional[str] = None
    html_url: Optional[str] = None
    default_branch: str = "main"
    private: bool = False
    owner_login: Optional[str] = None


class PullRequestCreate(BaseModel):
    artifact_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    body: Optional[str] = None
    branch_name: Optional[str] = None


class PullRequestOut(BaseModel):
    run_id: uuid.UUID
    artifact_id: uuid.UUID
    pull_request_url: Optional[str]
    pull_request_number: Optional[int]
    branch_name: str
    base_branch: str
    commit_sha: str


class WorkItemOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    type: str
    key: Optional[str] = None
    status: str
    priority: int
    executor: str
    assigned_agent_id: Optional[uuid.UUID] = None
    attempt: int
    max_attempts: int
    depends_on_count: int
    lease_expires_at: Optional[datetime] = None
    required_capabilities: list = Field(default_factory=list)
    payload: dict
    result: dict
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkItemEdgeOut(BaseModel):
    from_work_item_id: uuid.UUID
    to_work_item_id: uuid.UUID


class AgentCreate(BaseModel):
    name: str
    kind: str
    executors: list[str] = Field(default_factory=list)
    max_concurrency: int = 1
    capabilities: dict = Field(default_factory=dict)


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    executors: list[str]
    capabilities: dict
    max_concurrency: int
    status: str
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WorkItemComplete(BaseModel):
    status: Literal["DONE", "SKIPPED"] = "DONE"
    result: dict = Field(default_factory=dict)
    artifacts: list[dict] = Field(default_factory=list)


class WorkItemFail(BaseModel):
    error: str
    retry: bool = False
