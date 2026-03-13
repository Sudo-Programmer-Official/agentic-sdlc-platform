from __future__ import annotations

import re
from dataclasses import dataclass


_TOKEN_RE = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class StrategyOption:
    strategy_type: str
    label: str
    rationale: str
    prompt_hint: str


def _tokenize(*values: str | None) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        tokens.update(token for token in _TOKEN_RE.findall(value.lower()) if len(token) >= 3)
    return tokens


def plan_run_strategies(
    *,
    goal_text: str | None,
    error_text: str | None,
    files: list[str] | None,
    limit: int = 3,
) -> list[StrategyOption]:
    tokens = _tokenize(goal_text, error_text, *(files or []))
    options: list[StrategyOption] = [
        StrategyOption(
            strategy_type="minimal_patch",
            label="Minimal Patch",
            rationale="Prefer the smallest code change that can restore a passing run quickly.",
            prompt_hint="Favor a narrow, low-impact code change with the fewest modified files possible.",
        )
    ]

    if {"test", "tests", "pytest", "fixture", "spec"} & tokens:
        options.append(
            StrategyOption(
                strategy_type="update_test",
                label="Update Test Path",
                rationale="Investigate whether the failure is caused by stale fixtures, imports, or test assumptions.",
                prompt_hint="Check whether the test setup, fixtures, or imports should be adjusted instead of the application code.",
            )
        )
        options.append(
            StrategyOption(
                strategy_type="refactor_module",
                label="Refactor Module",
                rationale="Explore a slightly broader refactor if a narrow patch is likely to hide a deeper module issue.",
                prompt_hint="If the failing area is structurally brittle, prefer a cleaner module-level refactor over a one-line patch.",
            )
        )
    elif {"import", "module", "path"} & tokens:
        options.append(
            StrategyOption(
                strategy_type="fix_imports",
                label="Fix Imports",
                rationale="Prioritize import, path, and fixture resolution before broader code changes.",
                prompt_hint="Focus first on resolving import paths, module boundaries, and fixture wiring.",
            )
        )
        options.append(
            StrategyOption(
                strategy_type="update_test",
                label="Update Test Path",
                rationale="A failing import can also come from outdated test wiring or fixture references.",
                prompt_hint="Check whether the tests are importing the right modules and using the expected fixtures.",
            )
        )
    else:
        options.append(
            StrategyOption(
                strategy_type="targeted_refactor",
                label="Targeted Refactor",
                rationale="Try a constrained refactor when the issue may come from unclear boundaries rather than a single bug.",
                prompt_hint="Consider a focused refactor in the failing module if it improves correctness without widening scope too much.",
            )
        )
        options.append(
            StrategyOption(
                strategy_type="review_first",
                label="Review First",
                rationale="Create a safer exploration path that favors diagnosis and low-risk changes.",
                prompt_hint="Bias toward diagnosis, validation, and low-risk fixes before making broad code changes.",
            )
        )

    deduped: list[StrategyOption] = []
    seen: set[str] = set()
    for option in options:
        if option.strategy_type in seen:
            continue
        seen.add(option.strategy_type)
        deduped.append(option)
        if len(deduped) >= max(1, min(limit, 5)):
            break
    return deduped
