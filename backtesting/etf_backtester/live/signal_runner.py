"""Live signal generation and paper ledger updates."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import floor
from pathlib import Path
from time import perf_counter
from typing import Any

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE
from backtesting.etf_backtester.config.json_loader import load_json_config
from backtesting.etf_backtester.config.signal_sources import signal_sources_for
from backtesting.etf_backtester.config.settings import DEFAULT_CONFIG
from backtesting.etf_backtester.data.market_data import fetch_current_prices, fetch_historical_prices, fetch_max_close_history
from backtesting.etf_backtester.indicators.moving_average import exponential_moving_average
from backtesting.etf_backtester.metrics.performance import xirr
from backtesting.etf_backtester.live.state import (
    LIVE_REPORT_PATH,
    LIVE_STATE_PATH,
    build_completed_trades,
    empty_live_state,
    load_live_state,
    reconcile_strategy_cash,
    save_live_report,
    save_live_state,
)
from backtesting.etf_backtester.strategies.ema_atr_confirmed import EmaAtrConfirmedStrategy
from backtesting.etf_backtester.strategies.ema_atr_sell_band import EmaAtrSellBandStrategy
from backtesting.etf_backtester.strategies.ema_trend import EmaTrendStrategy
from backtesting.etf_backtester.strategies.rsi_50_cross import Rsi50CrossStrategy
from backtesting.etf_backtester.utils.paths import PACKAGE_ROOT


LIVE_CONFIG_PATH = PACKAGE_ROOT / "config" / "live_trading.json"


@dataclass(frozen=True)
class LiveSignalRun:
    """Live signal run output."""

    report: dict[str, Any]
    state_path: Path
    report_path: Path


def _record_timing(timings: dict[str, float], name: str, started_at: float) -> None:
    timings[name] = round(perf_counter() - started_at, 3)


def clear_live_ledger(
    config_path: Path = LIVE_CONFIG_PATH,
    state_path: Path = LIVE_STATE_PATH,
    report_path: Path = LIVE_REPORT_PATH,
) -> dict[str, Any]:
    """Clear all live holdings and trades for a fresh paper/live test."""

    config = _load_live_config(config_path)
    state = empty_live_state(float(config["initial_capital"]))
    save_live_state(state, state_path)
    if report_path.exists():
        report_path.unlink()
    return state


def run_live_signals(
    config_path: Path = LIVE_CONFIG_PATH,
    state_path: Path = LIVE_STATE_PATH,
    report_path: Path = LIVE_REPORT_PATH,
    apply_actions: bool = False,
    selected_action_ids: list[str] | None = None,
    run_date: date | None = None,
    run_time: time | None = None,
    save_report: bool = True,
    strict_price_time: bool = False,
    use_daily_close: bool = False,
    use_current_price: bool = False,
) -> LiveSignalRun:
    """Generate live buy/sell signals and optionally apply them to the ledger."""

    overall_started = perf_counter()
    timings: dict[str, float] = {}

    phase_started = perf_counter()
    config = _load_live_config(config_path)
    explicit_run_date = run_date is not None
    run_day = run_date or date.today()
    today = date.today()
    if run_day > today:
        raise ValueError(
            f"Cannot generate signals for {run_day.isoformat()} because it is after today "
            f"({today.isoformat()}). Yahoo Finance has no future candle data."
        )

    start_date = run_day - timedelta(days=int(config["lookback_days"]))
    symbols = config["symbols"] or ETF_UNIVERSE
    price_time = None if use_daily_close else _live_price_time(config, run_time)
    state = load_live_state(state_path, initial_capital=float(config["initial_capital"]))
    if reconcile_strategy_cash(state, float(config["initial_capital"])):
        save_live_state(state, state_path)
    _record_timing(timings, "load_config_state", phase_started)

    history_price_time = price_time if strict_price_time and price_time is not None else None
    if strict_price_time and price_time is not None and not _can_request_intraday(run_day):
        raise ValueError(
            "Selected-time Yahoo intraday data is only available for recent dates. "
            "Choose a recent trading date or use the main backtest daily-close workflow for older history."
        )
    if history_price_time is not None:
        start_date = max(start_date, run_day - timedelta(days=59))

    signal_sources = signal_sources_for(symbols) if config["signal_source_mode"] == "saved" else {symbol: symbol for symbol in symbols}
    external_sources = sorted({source for symbol, source in signal_sources.items() if source != symbol})
    phase_started = perf_counter()
    etf_histories, external_histories = _fetch_live_histories(
        symbols=symbols,
        external_sources=external_sources,
        start_date=start_date,
        run_day=run_day,
        price_time=history_price_time,
        intraday_interval=str(config["intraday_interval"]),
    )
    _record_timing(timings, "history_fetch", phase_started)
    price_note = "Daily candle close"
    if price_time is not None:
        price_note = "Daily cached data; Yahoo intraday not requested for old dates or non-trading days"
    if strict_price_time and price_time is not None:
        price_note = f"Selected-time intraday rows at {price_time.isoformat(timespec='minutes')}"
    elif price_time is not None and _can_request_intraday(run_day):
        phase_started = perf_counter()
        etf_intraday_symbols = _symbols_with_row_on_date(etf_histories, symbols, run_day)
        _overlay_latest_intraday_rows(
            histories=etf_histories,
            symbols=etf_intraday_symbols,
            run_day=run_day,
            price_time=price_time,
            intraday_interval=str(config["intraday_interval"]),
        )
        if external_sources:
            external_intraday_symbols = _symbols_with_row_on_date(external_histories, external_sources, run_day)
            _overlay_latest_intraday_rows(
                histories=external_histories,
                symbols=external_intraday_symbols,
                run_day=run_day,
                price_time=price_time,
                intraday_interval=str(config["intraday_interval"]),
            )
        _record_timing(timings, "intraday_overlay", phase_started)
        price_note = "Selected-time intraday when available; daily cached data for missing intraday rows"
    if strict_price_time and price_time is not None:
        _require_selected_time_rows(etf_histories, symbols, run_day, price_time)

    if use_current_price:
        phase_started = perf_counter()
        _overlay_current_price_rows_for_live(
            etf_histories=etf_histories,
            symbols=symbols,
            external_histories=external_histories,
            external_sources=external_sources,
            run_day=run_day,
        )
        _record_timing(timings, "current_price_overlay", phase_started)
        price_note = "Current market price live EMA"
        price_time = None

    signal_histories = {**etf_histories, **external_histories}
    strategy = _strategy_from_config(config)
    phase_started = perf_counter()
    signals_by_source = _generate_signals(strategy, signal_histories)
    _record_timing(timings, "signal_generation", phase_started)

    latest_rows = {
        symbol: rows[-1]
        for symbol, rows in etf_histories.items()
        if rows and (not strict_price_time or rows[-1]["date"] == run_day) and (not use_current_price or rows[-1]["date"] == run_day)
    }
    signal_contexts = _latest_signal_contexts(
        symbols,
        latest_rows,
        signal_sources,
        signal_histories,
        signals_by_source,
        min_source_rows=_minimum_live_signal_rows(config),
        ema_window=int(config["ema_window"]),
    )
    if use_daily_close and not explicit_run_date:
        _require_fresh_daily_close_rows(latest_rows, signal_contexts, _expected_latest_daily_close_date(run_day))
    latest_signals = {symbol: int(context["event"]) for symbol, context in signal_contexts.items()}

    ath_sources = sorted(set(signal_sources.values()))
    phase_started = perf_counter()
    ath_histories = fetch_max_close_history(ath_sources)
    _record_timing(timings, "ath_history", phase_started)
    ath_latest_rows = _latest_rows_by_symbol(signal_histories, ath_sources)
    phase_started = perf_counter()
    actions = _build_actions(config, state, etf_histories, signal_sources, ath_histories, ath_latest_rows, latest_rows, latest_signals, signal_contexts, run_day)
    signal_rows = _build_signal_rows(symbols, signal_sources, ath_histories, ath_latest_rows, latest_rows, latest_signals, signal_contexts, actions, state)
    report = _build_report(config, state, latest_rows, latest_signals, signal_rows, actions, run_day, price_time, price_note, apply_actions=False)
    _record_timing(timings, "action_report_build", phase_started)

    if apply_actions:
        phase_started = perf_counter()
        actions_to_apply = _filter_selected_actions(actions, selected_action_ids)
        _apply_actions(state, actions_to_apply, config)
        signal_rows = _build_signal_rows(symbols, signal_sources, ath_histories, ath_latest_rows, latest_rows, latest_signals, signal_contexts, actions_to_apply, state)
        report = _build_report(config, state, latest_rows, latest_signals, signal_rows, actions_to_apply, run_day, price_time, price_note, apply_actions=True)
        save_live_state(state, state_path)
        _record_timing(timings, "apply_actions", phase_started)

    timings["total_before_save"] = round(perf_counter() - overall_started, 3)
    report["timings"] = timings
    saved_report_path = save_live_report(report, report_path) if save_report else report_path
    return LiveSignalRun(report=report, state_path=state_path, report_path=saved_report_path)


def next_live_trading_date(
    after_date: date,
    config_path: Path = LIVE_CONFIG_PATH,
    max_scan_days: int = 21,
) -> date | None:
    """Find the next ETF trading date after a selected live backtest date."""

    today = date.today()
    if after_date >= today:
        return None

    config = _load_live_config(config_path)
    symbols = config["symbols"] or ETF_UNIVERSE
    start_date = after_date + timedelta(days=1)
    end_date = min(after_date + timedelta(days=max_scan_days), today)
    histories = fetch_historical_prices(
        symbols,
        start_date,
        end_date,
        price_time=None,
        intraday_interval=str(config["intraday_interval"]),
    )
    dates = sorted({
        row["date"]
        for rows in histories.values()
        for row in rows
        if row.get("date") is not None and row["date"] > after_date
    })
    return dates[0] if dates else None


def _fetch_live_histories(
    symbols: list[str],
    external_sources: list[str],
    start_date: date,
    run_day: date,
    price_time: time | None,
    intraday_interval: str,
) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        etf_future = executor.submit(
            fetch_historical_prices,
            symbols,
            start_date,
            run_day,
            price_time,
            intraday_interval,
        )
        external_future = (
            executor.submit(
                fetch_historical_prices,
                external_sources,
                start_date,
                run_day,
                price_time,
                intraday_interval,
            )
            if external_sources
            else None
        )
        etf_histories = etf_future.result()
        external_histories = external_future.result() if external_future is not None else {}

    return etf_histories, external_histories


def _overlay_current_price_rows_for_live(
    etf_histories: dict[str, list[dict]],
    symbols: list[str],
    external_histories: dict[str, list[dict]],
    external_sources: list[str],
    run_day: date,
) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        etf_future = executor.submit(_overlay_current_price_rows, etf_histories, symbols, run_day)
        external_future = (
            executor.submit(_overlay_current_price_rows, external_histories, external_sources, run_day)
            if external_sources
            else None
        )
        etf_future.result()
        if external_future is not None:
            external_future.result()


def _generate_signals(strategy, signal_histories: dict[str, list[dict]]) -> dict[str, list[int]]:
    items = [(symbol, rows) for symbol, rows in signal_histories.items() if rows]
    if not items:
        return {}

    with ThreadPoolExecutor(max_workers=min(8, len(items))) as executor:
        generated = executor.map(lambda item: (item[0], strategy.generate_signals(item[1])), items)
        return dict(generated)


def _overlay_latest_intraday_rows(
    histories: dict[str, list[dict]],
    symbols: list[str],
    run_day: date,
    price_time: time,
    intraday_interval: str,
) -> None:
    """Replace the latest daily row with the selected-time intraday row when available."""

    if not symbols:
        return

    intraday_histories = fetch_historical_prices(
        symbols,
        run_day,
        run_day,
        price_time=price_time,
        intraday_interval=intraday_interval,
    )
    for symbol, intraday_rows in intraday_histories.items():
        if not intraday_rows:
            continue
        _replace_or_append_row(histories.setdefault(symbol, []), intraday_rows[-1])


def _overlay_current_price_rows(
    histories: dict[str, list[dict]],
    symbols: list[str],
    run_day: date,
) -> None:
    """Replace the latest row with current market price rows when quotes are available."""

    quotes = fetch_current_prices(symbols)
    for quote in quotes:
        if quote.price is None:
            continue

        price = float(quote.price)
        _replace_or_append_row(
            histories.setdefault(quote.source_symbol, []),
            {
                "date": run_day,
                "time": "CMP",
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
            },
        )


def _can_request_intraday(run_day: date) -> bool:
    today = date.today()
    if run_day > today:
        return False
    return run_day >= today - timedelta(days=59)


def _symbols_with_row_on_date(
    histories: dict[str, list[dict]],
    symbols: list[str],
    run_day: date,
) -> list[str]:
    selected: list[str] = []
    for symbol in symbols:
        rows = histories.get(symbol, [])
        if rows and rows[-1]["date"] == run_day:
            selected.append(symbol)
    return selected


def _require_selected_time_rows(
    histories: dict[str, list[dict]],
    symbols: list[str],
    run_day: date,
    price_time: time,
) -> None:
    available = _symbols_with_row_on_date(histories, symbols, run_day)
    if available:
        return

    raise ValueError(
        "No selected-time price rows were available for "
        f"{run_day.isoformat()} at {price_time.isoformat(timespec='minutes')}. "
        "Use Next Trading Date or choose a recent trading day with intraday data."
    )


def _replace_or_append_row(rows: list[dict], new_row: dict) -> None:
    for index, row in enumerate(rows):
        if row["date"] == new_row["date"]:
            rows[index] = new_row
            return

    rows.append(new_row)
    rows.sort(key=lambda row: row["date"])


def format_live_signal_report(report: dict[str, Any]) -> str:
    """Format live signal report for terminal output."""

    lines = [
        f"Live signal run: {report['run_date']} {report['run_time']}",
        f"Strategy: {report['config']['strategy']} | Ranking: {report['config']['candidate_ranking']}",
        f"Cash: {report['cash']:.2f} | Equity: {report['equity']:.2f} | Holdings: {len(report['holdings'])}",
        "",
        "Actions",
    ]
    if not report["actions"]:
        lines.append("  No buy/sell action. Hold current positions.")
    else:
        for action in report["actions"]:
            lines.append(
                "  "
                f"{action['side']} {action['symbol']} "
                f"price={action['price']:.2f} "
                f"shares={action.get('shares', 0):.0f} "
                f"reason={action['reason']}"
            )

    lines.append("")
    lines.append("Open holdings")
    if not report["holdings"]:
        lines.append("  None")
    else:
        for holding in report["holdings"]:
            lines.append(
                "  "
                f"{holding['symbol']} shares={holding['shares']:.0f} "
                f"entry={holding['entry_price']:.2f} "
                f"last={holding['last_price']:.2f} "
                f"unrealized={holding['unrealized_profit']:.2f}"
            )

    return "\n".join(lines)


def _load_live_config(path: Path) -> dict[str, Any]:
    config = load_json_config(path)
    symbols = config.get("symbols") or []
    if symbols and not isinstance(symbols, list):
        raise ValueError("live_trading.json symbols must be a list")

    normalized_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    invalid_symbols = [symbol for symbol in normalized_symbols if symbol not in ETF_UNIVERSE]
    if invalid_symbols:
        raise ValueError(f"Unknown live ETF symbols: {', '.join(invalid_symbols)}")

    return {
        "symbols": normalized_symbols,
        "initial_capital": float(config.get("initial_capital", DEFAULT_CONFIG.initial_capital)),
        "max_positions": int(config.get("max_positions", DEFAULT_CONFIG.max_positions)),
        "strategy": str(config.get("strategy", "ema_trend")),
        "ema_window": int(config.get("ema_window", 9)),
        "rsi_window": int(config.get("rsi_window", 14)),
        "candidate_ranking": str(config.get("candidate_ranking", "ath")),
        "signal_source_mode": str(config.get("signal_source_mode", "saved")),
        "price_mode": str(config.get("price_mode", "time")),
        "price_time": str(config.get("price_time", DEFAULT_CONFIG.price_time)),
        "intraday_interval": str(config.get("intraday_interval", DEFAULT_CONFIG.intraday_interval)),
        "lookback_days": int(config.get("lookback_days", 120)),
        "rotate_to_stronger_candidates": bool(config.get("rotate_to_stronger_candidates", False)),
        "compound_positions": bool(config.get("compound_positions", True)),
        "mtf_enabled": bool(config.get("mtf_enabled", False)),
        "mtf_broker": str(config.get("mtf_broker", "ICICI Direct Prime 4999")),
        "mtf_interest_rate_annual_pct": float(config.get("mtf_interest_rate_annual_pct", 9.65)),
        "mtf_funded_multiple": float(config.get("mtf_funded_multiple", 3.0)),
        "mtf_collateral_haircut_pct": float(config.get("mtf_collateral_haircut_pct", 6.0)),
        "mtf_cash_buffer_pct": float(config.get("mtf_cash_buffer_pct", 20.0)),
        "mtf_pledged_liquidcase_value": float(config.get("mtf_pledged_liquidcase_value", 0.0)),
    }


def _live_price_time(config: dict[str, Any], run_time: time | None = None) -> time | None:
    if run_time is not None:
        return run_time

    if config["price_mode"] == "daily_close":
        return None

    return datetime.strptime(config["price_time"], "%H:%M").time()


def _strategy_from_config(config: dict[str, Any]):
    strategy_name = config["strategy"]
    if strategy_name in {"ema_trend", "ema_entry_low_sell"}:
        return EmaTrendStrategy(window=config["ema_window"])
    if strategy_name == "ema_atr_confirmed":
        return EmaAtrConfirmedStrategy(ema_window=config["ema_window"])
    if strategy_name == "ema_atr_sell_band":
        return EmaAtrSellBandStrategy(ema_window=config["ema_window"])
    if strategy_name == "rsi_50_cross":
        return Rsi50CrossStrategy(window=config["rsi_window"])

    raise ValueError(f"Unknown live strategy: {strategy_name}")


def _latest_signals(
    symbols: list[str],
    latest_rows: dict[str, dict],
    signal_sources: dict[str, str],
    signal_histories: dict[str, list[dict]],
    signals_by_source: dict[str, list[int]],
    min_source_rows: int,
) -> dict[str, int]:
    latest: dict[str, int] = {}
    for symbol in symbols:
        etf_row = latest_rows.get(symbol)
        if not etf_row:
            latest[symbol] = 0
            continue

        source = signal_sources.get(symbol, symbol)
        signal = _signal_event_on_date(source, etf_row["date"], signal_histories, signals_by_source, min_source_rows)
        latest[symbol] = int(signal or 0)

    return latest


def _latest_signal_contexts(
    symbols: list[str],
    latest_rows: dict[str, dict],
    signal_sources: dict[str, str],
    signal_histories: dict[str, list[dict]],
    signals_by_source: dict[str, list[int]],
    min_source_rows: int,
    ema_window: int,
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        etf_row = latest_rows.get(symbol)
        if not etf_row:
            contexts[symbol] = _empty_signal_context()
            continue

        source = signal_sources.get(symbol, symbol)
        context = _signal_context_on_date(source, etf_row["date"], signal_histories, signals_by_source, min_source_rows, ema_window)
        contexts[symbol] = context or _empty_signal_context()

    return contexts


def _empty_signal_context() -> dict[str, Any]:
    return {
        "event": 0,
        "state": 0,
        "signal_date": "",
        "signal_time": "",
        "source_date": "",
        "last_event": 0,
        "last_event_date": "",
        "source_price": None,
        "source_ema": None,
        "source_low": None,
    }


def _signal_context_on_date(
    symbol: str,
    target_date: date,
    histories: dict[str, list[dict]],
    signals_by_source: dict[str, list[int]],
    min_source_rows: int,
    ema_window: int,
) -> dict[str, Any] | None:
    rows = histories.get(symbol, [])
    signals = signals_by_source.get(symbol, [])
    if not rows or not signals:
        return None

    target_index: int | None = None
    for index, row in enumerate(rows):
        if row["date"] <= target_date:
            target_index = index
        if row["date"] >= target_date:
            break

    if target_index is None or target_index + 1 < min_source_rows:
        return None

    closes = [float(row["close"]) for row in rows]
    ema_values = exponential_moving_average(closes, ema_window)
    current = int(signals[target_index])
    previous = int(signals[target_index - 1]) if target_index > 0 else 0
    event = _transition_event(previous, current)
    row = rows[target_index]
    last_event = event
    last_event_date = row["date"] if event else None
    last_event_time = row.get("time", "")

    if not event:
        for index in range(target_index, 0, -1):
            transition = _transition_event(int(signals[index - 1]), int(signals[index]))
            if transition:
                last_event = transition
                last_event_date = rows[index]["date"]
                last_event_time = rows[index].get("time", "")
                break

    signal_date = row["date"] if event else last_event_date
    signal_time = row.get("time", "") if event else last_event_time
    return {
        "event": event,
        "state": current,
        "signal_date": signal_date.isoformat() if signal_date else "",
        "signal_time": signal_time,
        "source_date": row["date"].isoformat(),
        "last_event": last_event,
        "last_event_date": last_event_date.isoformat() if last_event_date else "",
        "source_price": float(row["close"]),
        "source_ema": ema_values[target_index],
        "source_low": float(row.get("low", row["close"])),
    }


def _transition_event(previous: int, current: int) -> int:
    if previous == 0 and current == 1:
        return 1
    if previous == 1 and current == 0:
        return -1
    return 0


def _signal_event_on_date(
    symbol: str,
    target_date: date,
    histories: dict[str, list[dict]],
    signals_by_source: dict[str, list[int]],
    min_source_rows: int,
) -> int | None:
    rows = histories.get(symbol, [])
    signals = signals_by_source.get(symbol, [])
    for index, row in enumerate(rows):
        if row["date"] == target_date:
            if index + 1 < min_source_rows:
                return None
            current = int(signals[index])
            previous = int(signals[index - 1]) if index > 0 else 0
            return _transition_event(previous, current)
    return None


def _minimum_live_signal_rows(config: dict[str, Any]) -> int:
    strategy_name = config["strategy"]
    if strategy_name == "rsi_50_cross":
        return int(config["rsi_window"])
    if strategy_name in {"ema_atr_confirmed", "ema_atr_sell_band"}:
        return max(int(config["ema_window"]), int(config["atr_window"]))
    return int(config["ema_window"])


def _expected_latest_daily_close_date(run_day: date) -> date:
    expected = run_day
    if run_day == date.today() and datetime.now().time() < time(18, 0):
        expected -= timedelta(days=1)

    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    return expected


def _require_fresh_daily_close_rows(
    latest_rows: dict[str, dict],
    signal_contexts: dict[str, dict[str, Any]],
    expected_date: date,
) -> None:
    stale: list[str] = []

    for symbol, row in sorted(latest_rows.items()):
        row_date = row.get("date")
        if isinstance(row_date, date) and row_date < expected_date:
            stale.append(f"{symbol} ETF {row_date.isoformat()}")

    for symbol, context in sorted(signal_contexts.items()):
        source_date = _parse_iso_date(context.get("source_date"))
        if source_date is not None and source_date < expected_date:
            stale.append(f"{symbol} source {source_date.isoformat()}")

    if not stale:
        return

    sample = ", ".join(stale[:8])
    suffix = "" if len(stale) <= 8 else f", +{len(stale) - 8} more"
    raise ValueError(
        "Daily close data is stale. "
        f"Expected latest completed candle on or after {expected_date.isoformat()}, "
        f"but found stale rows: {sample}{suffix}. "
        "Refresh/fix the EC2 data provider or cache before using Daily Close signals."
    )


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_actions(
    config: dict[str, Any],
    state: dict[str, Any],
    etf_histories: dict[str, list[dict]],
    signal_sources: dict[str, str],
    ath_histories: dict[str, list[dict]],
    ath_latest_rows: dict[str, dict],
    latest_rows: dict[str, dict],
    latest_signals: dict[str, int],
    signal_contexts: dict[str, dict[str, Any]],
    run_day: date,
) -> list[dict[str, Any]]:
    holdings = state.get("holdings", {})
    actions: list[dict[str, Any]] = []
    held_after_sells = set(holdings)
    cash_after_sells = float(state.get("cash", config["initial_capital"]))
    loan_after_sells = _live_mtf_loan_balance(holdings)

    for symbol in sorted(holdings):
        row = latest_rows.get(symbol)
        signal_context = signal_contexts.get(symbol, _empty_signal_context())
        source_sell_event = latest_signals.get(symbol, 0) == -1
        source_below_ema = bool(signal_context.get("signal_date")) and int(signal_context.get("state", 0)) == 0
        if row and (source_sell_event or source_below_ema):
            reason = "signal" if source_sell_event else "source_below_ema"
            action = _sell_action(symbol, row, holdings[symbol], run_day, reason)
            actions.append(action)
            cash_after_sells += float(action.get("cash_delta", action["value"]))
            loan_after_sells -= float(action.get("mtf_loan_repayment", 0) or 0)
            held_after_sells.discard(symbol)

    slots_available = max(int(config["max_positions"]) - len(held_after_sells), 0)
    if slots_available <= 0:
        return actions

    candidates = [
        symbol
        for symbol, signal in latest_signals.items()
        if signal == 1 and symbol not in held_after_sells and symbol in latest_rows
    ]
    candidates = sorted(
        candidates,
        key=lambda symbol: _ath_score(signal_sources.get(symbol, symbol), ath_histories, ath_latest_rows),
        reverse=True,
    )
    selected = candidates[:slots_available]
    cash = cash_after_sells
    held_market_value = sum(
        float(latest_rows[symbol]["close"]) * float(holdings[symbol]["shares"])
        for symbol in held_after_sells
        if symbol in latest_rows and symbol in holdings
    )
    equity_after_sells = cash + held_market_value - loan_after_sells
    mtf_enabled = bool(config.get("mtf_enabled", False))
    mtf_rules = _live_mtf_rules(config, holdings, latest_rows, held_after_sells, loan_after_sells, cash)
    target_budget = (
        (mtf_rules["limit"] / int(config["max_positions"]) if mtf_enabled else equity_after_sells / int(config["max_positions"]))
        if config["compound_positions"]
        else _fixed_live_position_budget(config, state)
    )
    for symbol in selected:
        if mtf_enabled:
            position_budget = min(target_budget, mtf_rules["available"])
        else:
            position_budget = min(target_budget, cash)
        if position_budget <= 0:
            continue
        price = float(latest_rows[symbol]["close"])
        shares = floor(position_budget / price)
        if shares <= 0:
            continue
        trade_value = shares * price
        if mtf_enabled:
            mtf_loan = trade_value
            cash_required = 0.0
            mtf_rules["available"] = max(mtf_rules["available"] - mtf_loan, 0.0)
        else:
            mtf_loan = 0.0
            cash_required = trade_value
        actions.append(
            {
                "side": "BUY",
                "symbol": symbol,
                "date": run_day.isoformat(),
                "signal_date": latest_rows[symbol]["date"].isoformat(),
                "time": latest_rows[symbol].get("time", ""),
                "price": price,
                "shares": shares,
                "value": trade_value,
                "cash_required": cash_required,
                "funding_mode": "mtf" if mtf_enabled else "delivery",
                "mtf_loan": mtf_loan,
                "mtf_broker": config.get("mtf_broker", ""),
                **_ath_metrics_for_etf(symbol, signal_sources, ath_histories, ath_latest_rows),
                "reason": "signal",
            }
        )
        cash -= cash_required

    return _with_action_ids(actions)


def _sell_action(symbol: str, row: dict, holding: dict, run_day: date, reason: str) -> dict[str, Any]:
    price = float(row["close"])
    shares = float(holding["shares"])
    value = shares * price
    cost_basis = float(holding.get("cost_basis", shares * float(holding["entry_price"])))
    mtf_loan = float(holding.get("mtf_loan", 0) or 0)
    return {
        "side": "SELL",
        "symbol": symbol,
        "date": run_day.isoformat(),
        "signal_date": row["date"].isoformat(),
        "time": row.get("time", ""),
        "price": price,
        "shares": shares,
        "value": value,
        "cash_delta": value - mtf_loan,
        "funding_mode": holding.get("funding_mode", "delivery"),
        "mtf_loan_repayment": mtf_loan,
        "profit": value - cost_basis,
        "reason": reason,
    }


def _live_mtf_loan_balance(holdings: dict[str, Any]) -> float:
    return sum(float(holding.get("mtf_loan", 0) or 0) for holding in holdings.values())


def _live_mtf_rules(
    config: dict[str, Any],
    holdings: dict[str, Any],
    latest_rows: dict[str, dict],
    held_symbols: set[str],
    loan_balance: float,
    cash_available: float | None = None,
) -> dict[str, float]:
    liquidcase = float(config.get("mtf_pledged_liquidcase_value", 0) or 0)
    haircut = float(config.get("mtf_collateral_haircut_pct", 0) or 0) / 100.0
    multiple = float(config.get("mtf_funded_multiple", 0) or 0)
    delivery_value = 0.0
    for symbol in held_symbols:
        holding = holdings.get(symbol, {})
        if str(holding.get("funding_mode", "delivery")).lower() == "mtf":
            continue
        row = latest_rows.get(symbol)
        price = float(row["close"]) if row else float(holding.get("entry_price", 0) or 0)
        delivery_value += float(holding.get("shares", 0) or 0) * price

    collateral = max((liquidcase + delivery_value) * (1.0 - haircut), 0.0)
    limit = collateral * multiple
    required_cash_buffer = float(config.get("initial_capital", 0) or 0) * float(config.get("mtf_cash_buffer_pct", 0) or 0) / 100.0
    available = max(limit - loan_balance, 0.0)
    if cash_available is not None and cash_available < required_cash_buffer:
        available = 0.0
    daily_interest_rate = float(config.get("mtf_interest_rate_annual_pct", 0) or 0) / 100.0 / 365.0
    return {
        "liquidcase": liquidcase,
        "delivery_collateral_value": delivery_value,
        "collateral": collateral,
        "limit": limit,
        "loan_balance": loan_balance,
        "available": available,
        "required_cash_buffer": required_cash_buffer,
        "daily_interest": loan_balance * daily_interest_rate,
        "daily_interest_rate": daily_interest_rate,
    }


def _with_action_ids(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for action in actions:
        action["id"] = (
            f"{action['side']}_{action['symbol']}_{action['signal_date']}_{action.get('time', '')}_{action['reason']}"
            .replace(":", "")
            .replace(" ", "_")
        )
    return actions


def _filter_selected_actions(
    actions: list[dict[str, Any]],
    selected_action_ids: list[str] | None,
) -> list[dict[str, Any]]:
    if selected_action_ids is None:
        return actions

    selected = set(selected_action_ids)
    return [action for action in actions if action.get("id") in selected]


def _rank_candidates(
    candidates: list[str],
    ranking_mode: str,
    histories: dict[str, list[dict]],
    latest_rows: dict[str, dict],
) -> list[str]:
    if ranking_mode == "ath":
        return sorted(candidates, key=lambda symbol: _ath_score(symbol, histories, latest_rows), reverse=True)
    if ranking_mode == "momentum_20_60":
        return sorted(candidates, key=lambda symbol: _momentum_score(symbol, histories), reverse=True)
    return candidates


def _ath_score(symbol: str, histories: dict[str, list[dict]], latest_rows: dict[str, dict]) -> float:
    highs = [float(row["close"]) for row in histories.get(symbol, [])]
    if not highs or symbol not in latest_rows:
        return 0.0
    return float(latest_rows[symbol]["close"]) / max(highs)


def _ath_metrics(symbol: str, histories: dict[str, list[dict]], latest_rows: dict[str, dict]) -> dict[str, float | None]:
    closes = [float(row["close"]) for row in histories.get(symbol, []) if row.get("close") is not None]
    if not closes or symbol not in latest_rows:
        return {"ath_current_price": None, "ath_price": None, "ath_distance_pct": None, "ath_closeness": None}

    current_price = float(latest_rows[symbol]["close"])
    ath_price = max([*closes, current_price])
    if ath_price <= 0:
        return {"ath_current_price": current_price, "ath_price": ath_price, "ath_distance_pct": None, "ath_closeness": None}

    return {
        "ath_current_price": current_price,
        "ath_price": ath_price,
        "ath_distance_pct": (ath_price - current_price) / ath_price,
        "ath_closeness": current_price / ath_price,
    }


def _ath_metrics_for_etf(
    etf_symbol: str,
    signal_sources: dict[str, str],
    ath_histories: dict[str, list[dict]],
    ath_latest_rows: dict[str, dict],
) -> dict[str, Any]:
    source = signal_sources.get(etf_symbol, etf_symbol)
    metrics = _ath_metrics(source, ath_histories, ath_latest_rows)
    return {
        **metrics,
        "ath_source": source,
    }


def _latest_rows_by_symbol(histories: dict[str, list[dict]], symbols: list[str]) -> dict[str, dict]:
    return {
        symbol: histories[symbol][-1]
        for symbol in symbols
        if histories.get(symbol)
    }


def _build_signal_rows(
    symbols: list[str],
    signal_sources: dict[str, str],
    ath_histories: dict[str, list[dict]],
    ath_latest_rows: dict[str, dict],
    latest_rows: dict[str, dict],
    latest_signals: dict[str, int],
    signal_contexts: dict[str, dict[str, Any]],
    actions: list[dict[str, Any]],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    selected_actions = {
        action["symbol"]: action
        for action in actions
        if action.get("side") in {"BUY", "SELL"}
    }
    holdings = state.get("holdings", {})
    rows: list[dict[str, Any]] = []

    for symbol in symbols:
        row = latest_rows.get(symbol)
        signal = int(latest_signals.get(symbol, 0))
        signal_context = signal_contexts.get(symbol, _empty_signal_context())
        metrics = _ath_metrics_for_etf(symbol, signal_sources, ath_histories, ath_latest_rows)
        rows.append(
            {
                "symbol": symbol,
                "signal_source": signal_sources.get(symbol, symbol),
                "signal": signal,
                "signal_label": _live_signal_label(signal, int(signal_context["state"])),
                "signal_date": signal_context["signal_date"],
                "time": signal_context["signal_time"] if signal_context["signal_time"] else (row.get("time", "") if row and signal else ""),
                "source_date": signal_context["source_date"],
                "last_signal": _signal_label(int(signal_context["last_event"])),
                "last_signal_date": signal_context["last_event_date"],
                "source_price": signal_context["source_price"],
                "source_ema": signal_context["source_ema"],
                "source_low": signal_context.get("source_low"),
                "price": float(row["close"]) if row else None,
                "ath_source": metrics["ath_source"],
                "ath_current_price": metrics["ath_current_price"],
                "ath_price": metrics["ath_price"],
                "ath_distance_pct": metrics["ath_distance_pct"],
                "ath_closeness": metrics["ath_closeness"],
                "selected_action": selected_actions.get(symbol, {}).get("side", ""),
                "is_selected": symbol in selected_actions,
                "is_held": symbol in holdings,
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            int(item["signal"]) != 1,
            item["ath_distance_pct"] is None,
            float(item["ath_distance_pct"] or 999.0),
            item["symbol"],
        ),
    )


def _signal_label(signal: int) -> str:
    if signal == 1:
        return "BUY"
    if signal == -1:
        return "SELL"
    return "HOLD"


def _live_signal_label(event: int, state: int) -> str:
    if event == 1:
        return "BUY"
    if event == -1:
        return "SELL"
    if state == 1:
        return "HOLD"
    return "WAIT"


def _momentum_score(symbol: str, histories: dict[str, list[dict]]) -> tuple[int, float]:
    rows = histories.get(symbol, [])
    if len(rows) < 61:
        return (0, -999.0)
    close = float(rows[-1]["close"])
    return_20 = close / float(rows[-21]["close"]) - 1.0
    return_60 = close / float(rows[-61]["close"]) - 1.0
    return (int(return_20 > 0 and return_60 > 0), return_20 + return_60)


def _apply_actions(state: dict[str, Any], actions: list[dict[str, Any]], config: dict[str, Any]) -> None:
    holdings = state.setdefault("holdings", {})
    trades = state.setdefault("trades", [])
    completed_trades = state.setdefault("completed_trades", [])
    cash = float(state.get("cash", config["initial_capital"]))

    for action in actions:
        if action["side"] == "SELL" and action["symbol"] in holdings:
            holding = holdings[action["symbol"]]
            if not _has_open_buy_trade(trades, action["symbol"]):
                completed_trades.append(_completed_trade_from_holding(action["symbol"], holding, action))
            cash += float(action.get("cash_delta", action["value"]))
            holdings.pop(action["symbol"], None)
            trades.append(action)

    for action in actions:
        if action["side"] == "BUY" and action["symbol"] not in holdings:
            cash -= float(action.get("cash_required", action["value"]))
            holdings[action["symbol"]] = {
                "symbol": action["symbol"],
                "shares": int(action["shares"]),
                "entry_price": float(action["price"]),
                "entry_date": action["date"],
                "cost_basis": float(action["value"]),
                "funding_mode": str(action.get("funding_mode", "delivery")).lower(),
                "mtf_loan": float(action.get("mtf_loan", 0) or 0),
                "margin_used": float(action.get("margin_used", 0) or 0),
                "broker": str(action.get("broker", "")),
                "entry_ema": float(action.get("entry_ema", 0) or 0),
                "entry_low": float(action.get("entry_low", 0) or 0),
            }
            trades.append(action)

    state["cash"] = cash


def _has_open_buy_trade(trades: list[dict[str, Any]], symbol: str) -> bool:
    open_buys = 0
    for trade in trades:
        if str(trade.get("symbol", "")).strip() != symbol:
            continue
        side = str(trade.get("side", "")).upper()
        if side == "BUY":
            open_buys += 1
        elif side == "SELL" and open_buys > 0:
            open_buys -= 1
    return open_buys > 0


def _completed_trade_from_holding(symbol: str, holding: dict[str, Any], sell_action: dict[str, Any]) -> dict[str, Any]:
    shares = int(float(sell_action.get("shares", holding.get("shares", 0)) or 0))
    buy_price = float(holding.get("entry_price", 0) or 0)
    sell_price_value = float(sell_action.get("price", 0) or 0)
    buy_value = float(holding.get("cost_basis", shares * buy_price) or 0)
    sell_value = float(sell_action.get("value", shares * sell_price_value) or 0)
    profit = float(sell_action.get("profit", sell_value - buy_value) or 0)
    buy_date = holding.get("entry_date", "")
    sell_date = sell_action.get("signal_date") or sell_action.get("date", "")
    return {
        "symbol": symbol,
        "buy_date": buy_date,
        "sell_date": sell_date,
        "buy_time": holding.get("time", ""),
        "sell_time": sell_action.get("time", ""),
        "buy_price": buy_price,
        "sell_price": sell_price_value,
        "shares": shares,
        "buy_value": buy_value,
        "sell_value": sell_value,
        "profit": profit,
        "return_pct": (profit / buy_value) if buy_value > 0 else 0.0,
        "holding_days": _holding_days_between(buy_date, sell_date),
        "reason": sell_action.get("reason", ""),
    }


def _holding_days_between(buy_date: Any, sell_date: Any) -> int | None:
    if not buy_date or not sell_date:
        return None
    try:
        return (datetime.fromisoformat(str(sell_date)).date() - datetime.fromisoformat(str(buy_date)).date()).days
    except ValueError:
        return None


def _fixed_live_position_budget(config: dict[str, Any], state: dict[str, Any]) -> float:
    return _live_capital_base(config, state) / int(config["max_positions"])


def _live_capital_base(config: dict[str, Any], state: dict[str, Any]) -> float:
    return float(config["initial_capital"]) + sum(
        float(row.get("amount", 0))
        for row in state.get("capital_adjustments", [])
        if isinstance(row, dict)
    )


def _build_report(
    config: dict[str, Any],
    state: dict[str, Any],
    latest_rows: dict[str, dict],
    latest_signals: dict[str, int],
    signal_rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    run_day: date,
    price_time: time | None,
    price_note: str,
    apply_actions: bool,
) -> dict[str, Any]:
    latest_data_dates = sorted(
        {
            row["date"]
            for row in latest_rows.values()
            if isinstance(row.get("date"), date)
        }
    )
    holdings_report = []
    for symbol, holding in sorted(state.get("holdings", {}).items()):
        last_price = float(latest_rows.get(symbol, {}).get("close", holding["entry_price"]))
        shares = float(holding["shares"])
        cost_basis = float(holding.get("cost_basis", shares * float(holding["entry_price"])))
        mtf_loan = float(holding.get("mtf_loan", 0) or 0)
        holdings_report.append(
            {
                "symbol": symbol,
                "shares": shares,
                "entry_price": float(holding["entry_price"]),
                "entry_date": holding["entry_date"],
                "last_price": last_price,
                "market_value": shares * last_price,
                "cost_basis": cost_basis,
                "unrealized_profit": (shares * last_price) - cost_basis,
                "funding_mode": holding.get("funding_mode", "delivery"),
                "mtf_loan": mtf_loan,
                "signal": latest_signals.get(symbol, 0),
            }
        )

    completed_trades = [
        *state.get("completed_trades", []),
        *build_completed_trades(state.get("trades", [])),
    ]
    cash = float(state.get("cash", config["initial_capital"]))
    mtf_loan_balance = sum(float(row.get("mtf_loan", 0) or 0) for row in holdings_report)
    equity = cash + sum(row["market_value"] for row in holdings_report) - mtf_loan_balance
    xirr_value = xirr(_live_cash_flows(config, state, equity, run_day))
    mtf_rules = _live_mtf_rules(
        config,
        state.get("holdings", {}),
        latest_rows,
        set(state.get("holdings", {}).keys()),
        mtf_loan_balance,
        cash,
    )
    return {
        "run_date": run_day.isoformat(),
        "run_time": datetime.now().isoformat(timespec="seconds"),
        "signal_time": "CMP" if price_note.startswith("Current market price") else (price_time.isoformat(timespec="minutes") if price_time else "daily_close"),
        "price_note": price_note,
        "data_as_of": latest_data_dates[-1].isoformat() if latest_data_dates else "",
        "data_date_range": {
            "min": latest_data_dates[0].isoformat() if latest_data_dates else "",
            "max": latest_data_dates[-1].isoformat() if latest_data_dates else "",
        },
        "mode": "applied" if apply_actions else "signals_only",
        "config": config,
        "cash": cash,
        "equity": equity,
        "xirr": xirr_value,
        "mtf": mtf_rules,
        "capital_base": _live_capital_base(config, state),
        "capital_adjustments": state.get("capital_adjustments", []),
        "actions": actions,
        "signal_rows": signal_rows,
        "holdings": holdings_report,
        "signals": latest_signals,
        "trades_count": len(state.get("trades", [])),
        "ledger_trades": state.get("trades", []),
        "completed_trades": completed_trades,
    }


def _live_cash_flows(config: dict[str, Any], state: dict[str, Any], ending_equity: float, ending_date: date) -> list[dict[str, Any]]:
    start_date = _state_start_date(state, ending_date)
    flows: list[dict[str, Any]] = [
        {"date": start_date, "amount": -float(config["initial_capital"]), "reason": "initial_capital"}
    ]
    for row in state.get("capital_adjustments", []):
        if not isinstance(row, dict):
            continue
        adjustment_date = _parse_flow_date(row.get("date"), ending_date)
        amount = float(row.get("amount", 0) or 0)
        if amount:
            flows.append({"date": adjustment_date, "amount": -amount, "reason": "capital_adjustment"})
    flows.append({"date": ending_date, "amount": float(ending_equity), "reason": "ending_equity"})
    return flows


def _state_start_date(state: dict[str, Any], fallback: date) -> date:
    return _parse_flow_date(state.get("created_at"), fallback)


def _parse_flow_date(value: Any, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return fallback
