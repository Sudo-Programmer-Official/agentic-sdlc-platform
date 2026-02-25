"""FastAPI application package."""

# Ensure local sibling packages (core, agent) are importable during local runs
# without requiring editable installs. Docker images still install them normally.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXTRA_PATHS = [
    ROOT / "core" / "src",
    ROOT / "agent" / "src",
]
for path in EXTRA_PATHS:
    p = str(path)
    if path.exists() and p not in sys.path:
        sys.path.insert(0, p)
