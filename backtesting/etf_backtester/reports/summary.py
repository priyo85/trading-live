"""Text summaries for backtest results."""

from backtesting.etf_backtester.metrics.performance import max_drawdown, total_return
from backtesting.etf_backtester.portfolio.backtest import BacktestResult


def build_summary(result: BacktestResult) -> str:
    """Build a compact text summary for CLI and UI output."""

    if not result.equity_curve:
        return "No equity curve was generated."

    start = result.equity_curve[0]["equity"]
    end = result.equity_curve[-1]["equity"]

    return "\n".join(
        [
            f"Starting equity: {start:,.2f}",
            f"Ending equity: {end:,.2f}",
            f"Total return: {total_return(result.equity_curve):.2%}",
            f"Max drawdown: {max_drawdown(result.equity_curve):.2%}",
            f"Trades: {len(result.trades)}",
        ]
    )
