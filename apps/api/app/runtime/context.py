from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class RunContext:
    project_id: uuid.UUID
    run_id: uuid.UUID
