"""Shared by the Python check scripts: report checkpoints as a verdict.

A check prints one JSON line, {"result", "detail", "score"}, and exits 0 only
when every checkpoint was met; score is the share met, for partial credit.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ["HOME"])
STATE = Path(os.environ["BENCH_STATE"])


class Checkpoints:
    """Scored checkpoints, plus guards: things the agent must not break
    (the data, the originals). A guard earns nothing when kept, so doing
    nothing scores 0, and breaking one fails the trial with a score of 0."""

    def __init__(self) -> None:
        self.items: list[tuple[str, bool, str]] = []
        self.broken: list[str] = []

    def guard(self, name: str, ok: bool, detail: str = "") -> bool:
        if not ok:
            self.broken.append(name + (f" ({detail})" if detail else ""))
        return bool(ok)

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append((name, bool(ok), detail))
        return bool(ok)

    def finish(self) -> None:
        met = sum(1 for _, ok, _ in self.items if ok)
        total = len(self.items) or 1
        missed = [f"{n}" + (f" ({d})" if d else "") for n, ok, d in self.items if not ok]
        passed = met == len(self.items) and bool(self.items) and not self.broken
        detail = f"{met}/{total}" + (": missed " + "; ".join(missed) if missed else "")
        if self.broken:
            detail += "; broke " + "; ".join(self.broken)
        print(
            json.dumps(
                {
                    "result": "pass" if passed else "fail",
                    "detail": detail,
                    "score": 0.0 if self.broken else round(met / total, 3),
                }
            )
        )
        sys.exit(0 if passed else 1)
