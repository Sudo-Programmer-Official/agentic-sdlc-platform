from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class Provenance(BaseModel):
    ai_model_name: Optional[str] = None
    ai_prompt_hash: Optional[str] = None
    ai_run_id: Optional[str] = None
    confidence_score: Optional[float] = None
