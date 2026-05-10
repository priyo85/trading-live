from backtesting.etf_backtester.config.settings import BacktestConfig
from backtesting.etf_backtester.portfolio.backtest import run_long_only_backtest
from backtesting.etf_backtester.strategies.moving_average_crossover import (
    MovingAverageCrossoverStrategy,
)


def test_moving_average_backtest_smoke():
    rows = [
        {"date": f"2026-01-{day:02d}", "open": 100 + day, "high": 101 + day, "low": 99 + day, "close": 100 + day}
        for day in range(1, 80)
    ]

    strategy = MovingAverageCrossoverStrategy(fast_window=3, slow_window=5)
    result = run_long_only_backtest(rows, strategy.generate_signals(rows), BacktestConfig())

    assert result.equity_curve
    assert result.equity_curve[-1]["equity"] > 0
