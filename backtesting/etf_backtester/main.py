"""Command-line entry point for the ETF swing backtester."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtesting.etf_backtester.config.settings import DEFAULT_CONFIG, STRATEGY_SETTINGS, WEB_UI_SETTINGS, BacktestConfig
from backtesting.etf_backtester.data.loader import load_ohlcv_csv
from backtesting.etf_backtester.portfolio.backtest import run_long_only_backtest
from backtesting.etf_backtester.reports.summary import build_summary
from backtesting.etf_backtester.strategies.moving_average_crossover import (
    MovingAverageCrossoverStrategy,
)


def parse_args() -> argparse.Namespace:
    strategy_defaults = STRATEGY_SETTINGS["moving_average_crossover"]
    parser = argparse.ArgumentParser(description="ETF swing trading backtester")
    parser.add_argument("--ui", action="store_true", help="Launch the browser UI")
    parser.add_argument("--desktop-ui", action="store_true", help="Launch the Tkinter desktop UI")
    parser.add_argument("--host", default=WEB_UI_SETTINGS["host"], help="Web UI host")
    parser.add_argument("--port", type=int, default=int(WEB_UI_SETTINGS["port"]), help="Web UI port")
    parser.add_argument("--prices", action="store_true", help="Print current ETF prices from the configured live provider")
    parser.add_argument("--migrate-cache", action="store_true", help="Import legacy JSON price caches into SQLite")
    parser.add_argument("--live-signals", action="store_true", help="Generate live buy/sell signals and update live report")
    parser.add_argument(
        "--apply-live-actions",
        action="store_true",
        help="Apply generated live actions to the local JSON ledger",
    )
    parser.add_argument("--csv", type=Path, help="Path to ETF OHLCV CSV data")
    parser.add_argument("--capital", type=float, default=DEFAULT_CONFIG.initial_capital, help="Initial capital")
    parser.add_argument("--fast", type=int, default=int(strategy_defaults["fast_window"]), help="Fast SMA window")
    parser.add_argument("--slow", type=int, default=int(strategy_defaults["slow_window"]), help="Slow SMA window")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.ui:
        from backtesting.etf_backtester.ui.web_app import run_web_ui

        run_web_ui(host=args.host, port=args.port)
        return

    if args.desktop_ui:
        from backtesting.etf_backtester.ui.app import run_ui

        run_ui()
        return

    if args.prices:
        from backtesting.etf_backtester.data.market_data import fetch_current_prices, format_price_table

        print(format_price_table(fetch_current_prices()))
        return

    if args.migrate_cache:
        from backtesting.etf_backtester.data.cache_migration import migrate_legacy_json_caches

        result = migrate_legacy_json_caches()
        print(
            "SQLite cache migration complete: "
            f"files seen={result.files_seen}, imported={result.files_imported}, "
            f"rows={result.rows_imported}, failed={result.files_failed}"
        )
        return

    if args.live_signals:
        from backtesting.etf_backtester.live.signal_runner import format_live_signal_report, run_live_signals

        run = run_live_signals(apply_actions=args.apply_live_actions)
        print(format_live_signal_report(run.report))
        print(f"\nLive report saved: {run.report_path}")
        print(f"Live state file: {run.state_path}")
        if not args.apply_live_actions:
            print("Run again with --apply-live-actions after you execute these trades to update the ledger.")
        return

    if not args.csv:
        print("Run with --ui, --prices, --live-signals, or pass --csv path/to/ohlcv.csv for CLI mode.")
        return

    rows = load_ohlcv_csv(args.csv)
    strategy = MovingAverageCrossoverStrategy(fast_window=args.fast, slow_window=args.slow)
    config = BacktestConfig(initial_capital=args.capital)
    result = run_long_only_backtest(rows, strategy.generate_signals(rows), config)
    print(build_summary(result))


if __name__ == "__main__":
    main()
