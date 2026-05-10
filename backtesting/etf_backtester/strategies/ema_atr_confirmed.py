"""EMA trend strategy with ATR band and confirmation filters."""

from __future__ import annotations

from dataclasses import dataclass

from backtesting.etf_backtester.signals.ema_atr_rules import ema_atr_confirmed_signal


@dataclass(frozen=True)
class EmaAtrConfirmedStrategy:
    """EMA9 strategy with rising EMA, 2-day confirmation, and 0.25 ATR bands."""

    ema_window: int = 9
    atr_window: int = 14
    atr_multiplier: float = 0.25
    confirmation_days: int = 2
    name: str = "EMA 9 ATR Confirmed"

    def generate_signals(self, rows: list[dict]) -> list[int]:
        return ema_atr_confirmed_signal(
            rows,
            ema_window=self.ema_window,
            atr_window=self.atr_window,
            atr_multiplier=self.atr_multiplier,
            confirmation_days=self.confirmation_days,
        )
