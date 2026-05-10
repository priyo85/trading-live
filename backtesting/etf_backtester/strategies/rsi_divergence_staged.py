"""RSI divergence staged-entry strategy."""

from __future__ import annotations

from dataclasses import dataclass

from backtesting.etf_backtester.signals.rsi_rules import rsi_divergence_staged_signal


@dataclass(frozen=True)
class RsiDivergenceStagedStrategy:
    """Buy in thirds on bullish RSI divergence and RSI 30 entries; sell below RSI 70."""

    window: int = 14
    oversold_threshold: float = 30.0
    overbought_threshold: float = 70.0
    divergence_max_rsi: float = 40.0
    pivot_span: int = 2
    regular_min_rsi_improvement: float = 3.0
    double_bottom_low_tolerance: float = 0.001
    double_bottom_min_rsi_improvement: float = 5.0
    name: str = "RSI Divergence Staged"

    def generate_signals(self, rows: list[dict]) -> list[int]:
        return rsi_divergence_staged_signal(
            rows,
            window=self.window,
            oversold_threshold=self.oversold_threshold,
            overbought_threshold=self.overbought_threshold,
            divergence_max_rsi=self.divergence_max_rsi,
            pivot_span=self.pivot_span,
            regular_min_rsi_improvement=self.regular_min_rsi_improvement,
            double_bottom_low_tolerance=self.double_bottom_low_tolerance,
            double_bottom_min_rsi_improvement=self.double_bottom_min_rsi_improvement,
        )
