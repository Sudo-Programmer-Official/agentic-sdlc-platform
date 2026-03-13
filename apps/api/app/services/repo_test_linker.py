from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from app.services.repo_index_types import ScannedRepoFile


def _split_identifier_tokens(value: str) -> list[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.replace("-", " ").replace("_", " "))
    return [token.lower() for token in normalized.split() if len(token) > 1]


def build_test_links(scanned_files: list[ScannedRepoFile]) -> list[tuple[str, str, str, float]]:
    by_path = {entry.path: entry for entry in scanned_files}
    targets = [entry for entry in scanned_files if entry.kind != "test_file"]
    links: dict[tuple[str, str, str], float] = {}

    for test_file in [entry for entry in scanned_files if entry.kind == "test_file"]:
        for target_path in test_file.imports:
            if target_path in by_path and by_path[target_path].kind != "test_file":
                links[(test_file.path, target_path, "import")] = max(
                    links.get((test_file.path, target_path, "import"), 0.0),
                    0.95,
                )

        test_tokens = set(_split_identifier_tokens(PurePosixPath(test_file.path).stem))
        if not test_tokens:
            continue
        for target in targets:
            score = len(test_tokens & set(_split_identifier_tokens(PurePosixPath(target.path).stem)))
            if score <= 0:
                continue
            confidence = 0.55 if score == 1 else 0.75
            links[(test_file.path, target.path, "name_match")] = max(
                links.get((test_file.path, target.path, "name_match"), 0.0),
                confidence,
            )

    ranked: defaultdict[str, list[tuple[str, str, str, float]]] = defaultdict(list)
    for (test_path, target_path, relation_type), confidence in links.items():
        ranked[test_path].append((test_path, target_path, relation_type, confidence))

    output: list[tuple[str, str, str, float]] = []
    for test_path, candidates in ranked.items():
        candidates.sort(key=lambda item: (item[3], item[1]), reverse=True)
        output.extend(candidates[:8])
    return output
