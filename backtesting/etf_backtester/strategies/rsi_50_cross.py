"""RSI 50 cross strategy."""

from __future__ import annotations

from dataclasses import dataclass

from backtesting.etf_backtester.signals.rsi_rules import rsi_cross_signal


@dataclass(frozen=True)
class Rsi50CrossStrategy:
    """Buy when RSI crosses above 50 and sell when it crosses below 50."""

    window: int = 14
    threshold: float = 50.0
    name: str = "RSI 50 Cross"

    def generate_signals(self, rows: list[dict]) -> list[int]:
        closes = [float(row["close"]) for row in rows]
        return rsi_cross_signal(closes, self.window, self.threshold)
