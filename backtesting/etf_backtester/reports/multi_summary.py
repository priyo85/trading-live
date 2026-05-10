"""Summary reporting for multi-ETF backtests."""

from backtesting.etf_backtester.metrics.performance import cagr, max_drawdown, total_return, xirr
from backtesting.etf_backtester.portfolio.multi_backtest import MultiBacktestResult


def build_multi_summary(result: MultiBacktestResult) -> str:
    """Build a compact text summary for multi-ETF results."""

    if not result.equity_curve:
        return "No equity curve was generated."

    start = result.equity_curve[0]["equity"]
    end = result.equity_curve[-1]["equity"]
    first_date = result.equity_curve[0]["date"]
    last_date = result.equity_curve[-1]["date"]
    max_positions = max(row["positions"] for row in result.equity_curve)

    lines = [
        f"Date range: {first_date} to {last_date}",
        f"Starting equity: {start:,.2f}",
        f"Ending equity: {end:,.2f}",
        f"Realized profit: {result.realized_profit:,.2f}",
        f"Unrealized profit: {result.unrealized_profit:,.2f}",
        f"Total return: {total_return(result.equity_curve):.2%}",
        f"CAGR: {cagr(result.equity_curve):.2%}",
        f"XIRR: {xirr(result.capital_flows):.2%}",
        f"Max drawdown: {max_drawdown(result.equity_curve):.2%}",
        f"Trades: {len(result.trades)}",
        f"Open positions: {len(result.open_positions)}",
        f"Max open positions used: {max_positions}",
        f"Capital added: {result.total_capital_added:,.2f}",
        f"Capital withdrawn: {result.total_capital_withdrawn:,.2f}",
        f"MTF capital borrowed: {result.total_extra_capital:,.2f}",
        f"Max MTF capital used: {result.max_extra_capital_used:,.2f}",
        f"MTF capital outstanding: {result.extra_capital_balance:,.2f}",
        f"MTF interest paid: {result.total_extra_capital_interest:,.2f}",
    ]
    if result.skipped_symbols:
        lines.append(f"Skipped symbols: {', '.join(result.skipped_symbols)}")

    return "\n".join(lines)
