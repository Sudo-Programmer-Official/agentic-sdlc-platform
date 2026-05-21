#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    api_root = repo_root / "apps" / "api"
    sys.path.insert(0, str(api_root))

    from app.services.runtime_doctor import run_runtime_doctor

    result = run_runtime_doctor(repo_root=repo_root)
    print(json.dumps({"ok": result.ok, "summary": result.summary, "checks": result.checks}, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
