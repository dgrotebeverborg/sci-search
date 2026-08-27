"""Capacity limits for queued and actively leased research jobs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobQuotaLimits:
    global_active: int = 10
    global_queued: int = 100
    workspace_active: int = 4
    workspace_queued: int = 25
    user_active: int = 2
    user_queued: int = 10

    def __post_init__(self) -> None:
        if any(value < 1 for value in self.values()):
            raise ValueError("every job quota must be at least one")

    def values(self) -> tuple[int, ...]:
        return (
            self.global_active,
            self.global_queued,
            self.workspace_active,
            self.workspace_queued,
            self.user_active,
            self.user_queued,
        )

    @classmethod
    def permissive(cls) -> JobQuotaLimits:
        return cls(*(10_000 for _ in range(6)))


class QuotaExceeded(RuntimeError):
    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(f"job quota exceeded: {scope}")
