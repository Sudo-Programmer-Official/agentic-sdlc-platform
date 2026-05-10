from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.db.models import Artifact


@dataclass(frozen=True)
class ContextScore:
    context_id: str
    context_kind: str
    overall: float
    relevance_score: float
    trust_score: float
    freshness_score: float
    historical_success_weight: float
    rationale: str


class ContextRankingPolicy:
    """Centralized ranking policy so runtime scoring is swappable and testable."""

    def score_external_reference(
        self,
        artifact: Artifact,
        *,
        requirement_id: str | None,
        requirement_tokens: set[str],
        successful_run_ids: set[uuid.UUID],
    ) -> ContextScore:
        metadata = artifact.extra_metadata if isinstance(artifact.extra_metadata, dict) else {}
        trust_score = float(metadata.get("trust_score") or 0.8)
        created_at = artifact.created_at.replace(tzinfo=timezone.utc) if artifact.created_at.tzinfo is None else artifact.created_at
        age_days = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0)
        freshness_score = max(0.0, min(1.0, 1.0 - min(age_days / 30.0, 1.0)))
        historical_success_weight = 0.8 if artifact.run_id in successful_run_ids else 0.5

        summary_blob = f"{metadata.get('summary') or ''} {metadata.get('sanitized_text') or ''}".lower()
        relevance_score = 0.95 if requirement_id and artifact.requirement_id == requirement_id else 0.65
        if requirement_tokens and any(token in summary_blob for token in requirement_tokens):
            relevance_score = max(relevance_score, 0.85)

        overall = round(
            (relevance_score * 0.4)
            + (trust_score * 0.2)
            + (freshness_score * 0.2)
            + (historical_success_weight * 0.2),
            4,
        )
        return ContextScore(
            context_id=str(artifact.id),
            context_kind="external_reference",
            overall=overall,
            relevance_score=round(relevance_score, 3),
            trust_score=round(trust_score, 3),
            freshness_score=round(freshness_score, 3),
            historical_success_weight=round(historical_success_weight, 3),
            rationale=(
                f"relevance={relevance_score:.3f}, trust={trust_score:.3f}, freshness={freshness_score:.3f}, "
                f"historical_success={historical_success_weight:.3f}"
            ),
        )

    def rank(self, items: list[tuple[Artifact, ContextScore]], *, top_k: int) -> tuple[list[tuple[Artifact, ContextScore]], list[tuple[Artifact, ContextScore]]]:
        ordered = sorted(items, key=lambda value: value[1].overall, reverse=True)
        return ordered[:top_k], ordered[top_k:]

    def summarize_efficiency(self, *, loaded_count: int, selected_count: int) -> float:
        if loaded_count <= 0:
            return 0.0
        return round(selected_count / loaded_count, 4)

    def decision_trace(
        self,
        *,
        selected: list[tuple[Artifact, ContextScore]],
        dropped: list[tuple[Artifact, ContextScore]],
        authoritative_keys: list[str],
        advisory_keys: list[str],
        loaded_count: int,
    ) -> dict[str, Any]:
        return {
            "authoritative_keys": authoritative_keys,
            "advisory_keys": advisory_keys,
            "context_loaded_count": loaded_count,
            "context_selected_count": len(selected),
            "context_efficiency_ratio": self.summarize_efficiency(loaded_count=loaded_count, selected_count=len(selected)),
            "selected_context": [
                {
                    "id": score.context_id,
                    "kind": score.context_kind,
                    "score": score.overall,
                    "relevance_score": score.relevance_score,
                    "trust_score": score.trust_score,
                    "freshness_score": score.freshness_score,
                    "historical_success_weight": score.historical_success_weight,
                    "uri": artifact.uri,
                }
                for artifact, score in selected
            ],
            "dropped_context": [
                {
                    "id": score.context_id,
                    "kind": score.context_kind,
                    "score": score.overall,
                    "uri": artifact.uri,
                }
                for artifact, score in dropped[:8]
            ],
        }
