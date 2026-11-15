#!/usr/bin/env python3
"""Summarize bench results: one row per task and arm, then per arm.

    bench/report.py bench/results/<run> [more runs...]

Success counts only trials the check passed AND, for "gui" tasks, that
didn't take a shortcut the task ruled out (a shell command where it asked
for the UI). "result" tasks accept any route; their shortcuts are counted
but don't fail. Score is the mean share of a task's checkpoints met.
Times, turns, tool calls and images are medians over all trials, passing
or not, since a fast failure is still a cost. Infra errors (a desk that
never started, a setup that failed) are counted apart and left out of
everything else.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def load(paths: list[str]) -> list[dict]:
    rows = []
    for p in paths:
        path = Path(p)
        path = path / "results.ndjson" if path.is_dir() else path
        rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows


def median(values: list) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "-"
    m = statistics.median(values)
    return f"{m:.0f}" if m >= 10 else f"{m:.1f}"


def clean_pass(t: dict) -> bool:
    if not t.get("passed") or t.get("cheats"):
        return False
    return t.get("kind") == "result" or not t.get("shortcuts")


def row(label: str, trials: list[dict]) -> str:
    real = [t for t in trials if "infra_error" not in t]
    infra = len(trials) - len(real)
    clean = sum(1 for t in real if clean_pass(t))
    checked = sum(1 for t in real if t["passed"])
    shortcut = sum(1 for t in real if t.get("shortcuts"))
    leaks = sum(
        1
        for t in real
        if t.get("host", {}).get("windows_opened") or t.get("host", {}).get("files_changed")
    )
    cost = [t.get("cost_usd") for t in real]
    cells = [
        label,
        f"{clean}/{len(real)}" + (f" (+{infra} infra)" if infra else ""),
        f"{statistics.mean([t.get('score', 1.0 if t['passed'] else 0.0) for t in real]):.2f}"
        if real
        else "-",
        str(checked),
        str(shortcut),
        median([t.get("wall_s") for t in real]),
        median([t.get("turns") for t in real]),
        median([t.get("tool_calls") for t in real]),
        median([t.get("images") for t in real]),
        median([round(t.get("input_tokens", 0) / 1000) for t in real]),
        f"{statistics.median([c for c in cost if c is not None]):.3f}"
        if any(c is not None for c in cost)
        else "-",
        str(leaks),
    ]
    return "| " + " | ".join(cells) + " |"


HEADER = (
    "| | pass | score | check ok | shortcut | wall s | turns | tools | images "
    "| kTok in | $ | host leak |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|"
)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    trials = load(sys.argv[1:])
    by_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for t in trials:
        by_task[(t["task"], t["arm"])].append(t)
        by_arm[t["arm"]].append(t)

    print(HEADER)
    for task, arm in sorted(by_task):
        print(row(f"{task} / {arm}", by_task[(task, arm)]))
    print()
    print(HEADER)
    for arm in sorted(by_arm):
        print(row(arm, by_arm[arm]))

    tools: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in trials:
        for name, count in (t.get("tools") or {}).items():
            tools[t["arm"]][name] += count
    print("\nTool calls by arm:")
    for arm in sorted(tools):
        ranked = sorted(tools[arm].items(), key=lambda kv: -kv[1])
        print(f"  {arm}: " + ", ".join(f"{n} {c}" for n, c in ranked))

    failures = [t for t in trials if not clean_pass(t) or t.get("shortcuts")]
    if failures:
        print("\nFailures and shortcuts:")
        for t in failures:
            why = t.get("infra_error") or t.get("detail", "")
            if t.get("cheats"):
                why += f"; read the answer key: {t['cheats'][0][:80]}"
            if t.get("shortcuts"):
                why += f"; shortcut: {t['shortcuts'][0][:80]}"
            print(f"  {t['trial']}: {why}")


if __name__ == "__main__":
    main()
