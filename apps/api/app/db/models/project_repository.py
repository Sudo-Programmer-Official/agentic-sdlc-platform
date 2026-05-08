from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ProjectRepository(TimestampMixin, Base):
    __tablename__ = "project_repositories"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_repositories_project_id"),
        Index("idx_project_repositories_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="github")
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    repo_full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(120), nullable=False, default="main")
    installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auth_strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="runtime_default")
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
