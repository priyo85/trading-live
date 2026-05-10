"""Moving average crossover strategy."""

from dataclasses import dataclass

from backtesting.etf_backtester.signals.rules import moving_average_regime


@dataclass(frozen=True)
class MovingAverageCrossoverStrategy:
    """Long ETF exposure when short-term trend is above long-term trend."""

    fast_window: int = 20
    slow_window: int = 50
    name: str = "Moving Average Crossover"

    def generate_signals(self, rows: list[dict]) -> list[int]:
        closes = [float(row["close"]) for row in rows]
        return moving_average_regime(closes, self.fast_window, self.slow_window)
