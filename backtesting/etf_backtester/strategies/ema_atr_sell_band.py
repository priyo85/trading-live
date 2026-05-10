"""EMA trend strategy with ATR sell band."""

from __future__ import annotations

from dataclasses import dataclass

from backtesting.etf_backtester.signals.ema_atr_rules import ema_atr_sell_band_signal


@dataclass(frozen=True)
class EmaAtrSellBandStrategy:
    """EMA strategy that buys above EMA and sells below an ATR-adjusted EMA band."""

    ema_window: int = 9
    atr_window: int = 14
    atr_multiplier: float = 0.25
    name: str = "EMA 9 ATR Sell Band"

    def generate_signals(self, rows: list[dict]) -> list[int]:
        return ema_atr_sell_band_signal(
            rows,
            ema_window=self.ema_window,
            atr_window=self.atr_window,
            atr_multiplier=self.atr_multiplier,
        )
