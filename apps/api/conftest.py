import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRA = [
    ROOT / "apps" / "api",
    ROOT / "core" / "src",
    ROOT / "agent" / "src",
]
for path in EXTRA:
    p = str(path)
    if path.exists() and p not in sys.path:
        sys.path.insert(0, p)
