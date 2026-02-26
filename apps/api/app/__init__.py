"""FastAPI application package."""

# Ensure local sibling packages (core, agent) are importable during local runs
# without requiring editable installs. Docker images still install them normally.
import sys
from pathlib import Path

# Find the repo root that contains core/src (works both locally and in the container)
_here = Path(__file__).resolve()
ROOT = next(
    (p for p in _here.parents if (p / "core" / "src").exists()),
    _here.parent,  # fallback: app package directory
)

EXTRA_PATHS = [
    ROOT / "core" / "src",
    ROOT / "agent" / "src",
]
for path in EXTRA_PATHS:
    p = str(path)
    if path.exists() and p not in sys.path:
        sys.path.insert(0, p)
