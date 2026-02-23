from __future__ import annotations

import hashlib
import uuid
from typing import List, Tuple

from app.schemas.generation import TaskGenInput, GeneratedTask


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mock_generate_tasks(document_title: str, document_body: str, opts: TaskGenInput) -> Tuple[List[GeneratedTask], dict]:
    """
    Deterministic, offline-friendly task generator for development.
    Splits body into sentences and yields up to opts.max_tasks tasks.
    """
    sentences = [s.strip() for s in document_body.replace("\n", " ").split(".") if s.strip()]
    tasks: List[GeneratedTask] = []
    for idx, sentence in enumerate(sentences[: opts.max_tasks]):
        tasks.append(
            GeneratedTask(
                title=f"{document_title} - Task {idx+1}",
                description=sentence,
                category="func",
                confidence=0.75,
            )
        )
    if not tasks:
        tasks.append(
            GeneratedTask(
                title=f"{document_title} - Define scope",
                description="Define scope and acceptance criteria.",
                category="func",
                confidence=0.65,
            )
        )
    prov = {
        "ai_model_name": opts.model,
        "ai_prompt_hash": _prompt_hash(document_body),
        "ai_run_id": str(uuid.uuid4()),
    }
    return tasks, prov
