import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXTRA_PATHS = [
    ROOT / "apps" / "api",
    ROOT / "core" / "src",
    ROOT / "agent" / "src",
    ROOT,
]

for path in EXTRA_PATHS:
    path_str = str(path)
    if path.exists() and path_str not in sys.path:
        sys.path.insert(0, path_str)
