"""Shared bounds and atomic progress snapshots for the complete data investigation."""

import json
import math
import time
from pathlib import Path


class BudgetExhausted(BaseException):
    """Like cancellation, must cross source-level exception/retry guards unchanged."""


class RunControl:
    DEFAULTS = {"seconds": 600, "model_calls": 80, "search_calls": 8, "downloads": 100}

    def __init__(self, directory, limits=None):
        self.limits = {**self.DEFAULTS, **(limits or {})}
        if set(self.limits) != set(self.DEFAULTS) or any(
            type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 100000
            for v in self.limits.values()
        ):
            raise ValueError("Invalid data research budget")
        self.directory = Path(directory)
        self.started = time.monotonic()
        self.counts = dict.fromkeys(("model_calls", "search_calls", "downloads"), 0)
        self.state = None
        self.seed = None
        self.staged = None
        self.stop_reason = ""

    def snapshot(self):
        return {
            "limits": self.limits,
            "counts": dict(self.counts),
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "stop_reason": self.stop_reason,
            "qualification": "Limits apply before operations; an in-flight call retains its own timeout.",
        }

    def checkpoint(self):
        if self.state is None:
            return
        value = {**self.state, "run_control": self.snapshot()}
        if self.staged:
            value["connector_checkpoint"] = self.staged
        path = self.directory / "checkpoint.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
        temporary.replace(path)

    def check(self):
        if time.monotonic() - self.started >= self.limits["seconds"]:
            self.stop_reason = "Data investigation time budget exhausted"
            self.checkpoint()
            raise BudgetExhausted(self.stop_reason)

    def wrap(self, name, operation):
        def call(*args, **kwargs):
            self.check()
            if self.counts[name] >= self.limits[name]:
                self.stop_reason = "Data investigation budget exhausted: " + name
                self.checkpoint()
                raise BudgetExhausted(self.stop_reason)
            self.counts[name] += 1
            self.checkpoint()
            return operation(*args, **kwargs)

        return call

    def preserve_staged(self):
        if not self.state or not self.staged:
            return
        for name in ("analyses", "assessments"):
            for item in self.staged.get(name, []):
                if item not in self.state[name]:
                    self.state[name].append(item)
        self.staged = None
