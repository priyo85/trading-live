"""Weekly EMA cross strategy."""

from dataclasses import dataclass

from backtesting.etf_backtester.signals.ema_rules import weekly_price_above_ema_signal


@dataclass(frozen=True)
class WeeklyEmaCrossStrategy:
    """Buy/hold when weekly close is above EMA, sell when below EMA."""

    window: int = 9
    confirmation_days: int = 1
    name: str = "Weekly EMA Cross"

    def generate_signals(self, rows: list[dict]) -> list[int]:
        return weekly_price_above_ema_signal(rows, self.window, self.confirmation_days)
