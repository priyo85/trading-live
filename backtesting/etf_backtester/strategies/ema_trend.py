"""EMA trend strategy."""

from dataclasses import dataclass

from backtesting.etf_backtester.signals.ema_rules import price_above_ema_signal


@dataclass(frozen=True)
class EmaTrendStrategy:
    """Buy/hold when price closes above EMA, sell when it closes below EMA."""

    window: int = 9
    name: str = "Close Above EMA"

    def generate_signals(self, rows: list[dict]) -> list[int]:
        closes = [float(row["close"]) for row in rows]
        return price_above_ema_signal(closes, self.window)
