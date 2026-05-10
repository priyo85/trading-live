"""Long-only ETF portfolio simulator."""

from __future__ import annotations

from dataclasses import dataclass

from backtesting.etf_backtester.config.settings import BacktestConfig
from backtesting.etf_backtester.execution.broker import buy_price, commission, sell_price
from backtesting.etf_backtester.risk.position_sizing import capital_to_deploy


@dataclass(frozen=True)
class BacktestResult:
    """Backtest output used by reports and UI."""

    equity_curve: list[dict]
    trades: list[dict]


def run_long_only_backtest(
    rows: list[dict],
    signals: list[int],
    config: BacktestConfig,
) -> BacktestResult:
    """Run an all-in/all-out long-only backtest from long/cash signals."""

    if len(rows) != len(signals):
        raise ValueError("rows and signals must have the same length")

    cash = config.initial_capital
    shares = 0.0
    equity_curve: list[dict] = []
    trades: list[dict] = []

    for row, signal in zip(rows, signals):
        close = float(row["close"])

        if signal == 1 and shares == 0:
            fill_price = buy_price(close, config.slippage_rate)
            deployable_cash = capital_to_deploy(cash, config.position_fraction)
            gross_shares = deployable_cash / fill_price
            trade_value = gross_shares * fill_price
            fee = commission(trade_value, config.commission_rate)
            shares = max((deployable_cash - fee) / fill_price, 0)
            cash -= shares * fill_price + fee
            trades.append({"date": row["date"], "side": "BUY", "price": fill_price, "shares": shares})

        elif signal == 0 and shares > 0:
            fill_price = sell_price(close, config.slippage_rate)
            trade_value = shares * fill_price
            fee = commission(trade_value, config.commission_rate)
            cash += trade_value - fee
            trades.append({"date": row["date"], "side": "SELL", "price": fill_price, "shares": shares})
            shares = 0.0

        equity_curve.append({"date": row["date"], "equity": cash + shares * close})

    return BacktestResult(equity_curve=equity_curve, trades=trades)
