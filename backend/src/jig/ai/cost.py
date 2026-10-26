"""Per-session spend tracking with a hard budget stop."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from jig.ai.config import ModelConfig


class BudgetExceeded(RuntimeError):
    """Raised before a call that would run on an already spent budget."""


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    audio_seconds: float = 0.0


@dataclass
class CostEntry:
    role: str
    model: str
    usage: Usage
    cost_usd: float


@dataclass
class CostMeter:
    config: ModelConfig
    budget_usd: float
    warn_fraction: float = 0.8
    entries: list[CostEntry] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def spent_usd(self) -> float:
        return sum(entry.cost_usd for entry in self.entries)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)

    def estimate(self, model: str, usage: Usage) -> float:
        price = self.config.price(model)
        uncached = max(0, usage.input_tokens - usage.cached_input_tokens)
        return (
            uncached * price.input_per_mtok / 1e6
            + usage.cached_input_tokens * price.cached_input_per_mtok / 1e6
            + usage.output_tokens * price.output_per_mtok / 1e6
            + usage.images * price.per_image
            + usage.audio_seconds / 3600 * price.per_audio_hour
        )

    def check(self) -> None:
        if self.spent_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"Session budget of ${self.budget_usd:.2f} is spent "
                f"(${self.spent_usd:.2f} used). Raise JIG_BUDGET_USD or start a new session."
            )

    def record(self, role: str, model: str, usage: Usage) -> CostEntry:
        entry = CostEntry(role=role, model=model, usage=usage, cost_usd=self.estimate(model, usage))
        with self._lock:
            self.entries.append(entry)
        return entry

    def set_budget(self, budget_usd: float) -> None:
        self.budget_usd = max(0.0, budget_usd)

    def summary(self) -> dict[str, object]:
        spent = self.spent_usd
        return {
            "spent_usd": round(spent, 4),
            "budget_usd": self.budget_usd,
            "remaining_usd": round(self.remaining_usd, 4),
            "calls": len(self.entries),
            "warning": spent >= self.budget_usd * self.warn_fraction,
            "exhausted": spent >= self.budget_usd,
        }
