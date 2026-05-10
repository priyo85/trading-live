"""Backtest orchestration helpers for UI and API entry points."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from backtesting.etf_backtester.config.signal_sources import signal_sources_for
from backtesting.etf_backtester.config.settings import BacktestConfig
from backtesting.etf_backtester.data.market_data import (
    HistoryAvailability,
    fetch_historical_prices,
    fetch_history_availability,
)
from backtesting.etf_backtester.portfolio.multi_backtest import MultiBacktestResult, run_multi_etf_backtest
from backtesting.etf_backtester.strategies.ema_atr_confirmed import EmaAtrConfirmedStrategy
from backtesting.etf_backtester.strategies.ema_atr_sell_band import EmaAtrSellBandStrategy
from backtesting.etf_backtester.strategies.ema_trend import EmaTrendStrategy
from backtesting.etf_backtester.strategies.rsi_50_cross import Rsi50CrossStrategy
from backtesting.etf_backtester.strategies.rsi_divergence_staged import RsiDivergenceStagedStrategy
from backtesting.etf_backtester.strategies.weekly_ema_cross import WeeklyEmaCrossStrategy


@dataclass(frozen=True)
class EmaBacktestRequest:
    """Configuration for a multi-ETF EMA backtest."""

    symbols: list[str]
    initial_capital: float
    max_positions: int
    start_date: date
    end_date: date
    strategy_name: str
    ema_window: int
    atr_window: int
    atr_multiplier: float
    confirmation_days: int
    rsi_window: int
    candidate_ranking: str
    rank_buy_candidates_by_ath: bool
    rotate_to_stronger_candidates: bool
    compound_positions: bool
    buy_all_overflow_signals: bool
    mtf_mode: str
    extra_capital_limit_multiplier: float
    max_overflow_positions: int | None
    extra_capital_interest_rate_daily: float
    monthly_capital_addition: float
    withdrawal_target: float | None
    monthly_withdrawal_amount: float
    price_time: time | None
    intraday_interval: str
    signal_sources: dict[str, str] | None = None


@dataclass(frozen=True)
class EmaBacktestRun:
    """Backtest result plus metadata needed for reports."""

    result: MultiBacktestResult
    signal_sources: dict[str, str]
    condition_identifier: str


def run_ema_backtest(request: EmaBacktestRequest) -> EmaBacktestRun:
    """Fetch Yahoo Finance history and run the EMA trend strategy."""

    price_time = None if request.strategy_name in _DAILY_CLOSE_STRATEGIES else request.price_time
    etf_histories = fetch_historical_prices(
        request.symbols,
        request.start_date,
        request.end_date,
        price_time=price_time,
        intraday_interval=request.intraday_interval,
    )
    signal_sources = _request_signal_sources(request)
    external_signal_sources = sorted({source for etf, source in signal_sources.items() if source != etf})
    external_signal_histories = (
        fetch_historical_prices(
            external_signal_sources,
            request.start_date,
            request.end_date,
            price_time=price_time,
            intraday_interval=request.intraday_interval,
        )
        if external_signal_sources
        else {}
    )
    external_availability = (
        fetch_history_availability(external_signal_sources)
        if external_signal_sources
        else {}
    )
    signal_histories = {**etf_histories, **external_signal_histories}
    strategy = _strategy_from_request(request)
    signals_by_source = _generate_signals_by_source(strategy, signal_histories)
    _print_signal_source_coverage(
        etf_histories=etf_histories,
        signal_sources=signal_sources,
        signal_histories=signal_histories,
        external_availability=external_availability,
    )
    signals_by_symbol = _map_source_signals_to_etf_dates(
        etf_histories,
        signal_sources,
        signals_by_source,
        signal_histories,
        min_source_rows=_minimum_signal_rows(request),
    )
    config = BacktestConfig(initial_capital=request.initial_capital)

    result = run_multi_etf_backtest(
        histories=etf_histories,
        signals_by_symbol=signals_by_symbol,
        config=config,
        max_positions=request.max_positions,
        rank_buy_candidates_by_ath=request.rank_buy_candidates_by_ath,
        candidate_ranking=request.candidate_ranking,
        rotate_to_stronger_candidates=request.rotate_to_stronger_candidates,
        compound_positions=request.compound_positions,
        buy_all_overflow_signals=request.buy_all_overflow_signals,
        mtf_mode=request.mtf_mode,
        extra_capital_limit_multiplier=request.extra_capital_limit_multiplier,
        max_overflow_positions=request.max_overflow_positions,
        extra_capital_interest_rate_daily=request.extra_capital_interest_rate_daily,
        monthly_capital_addition=request.monthly_capital_addition,
        withdrawal_target=request.withdrawal_target,
        monthly_withdrawal_amount=request.monthly_withdrawal_amount,
        sell_price_rule=_sell_price_rule(request),
        sell_rule_ema_window=request.ema_window,
        ranking_histories=signal_histories,
        ranking_sources=signal_sources,
        entry_parts=_entry_parts(request),
        entry_part_weights=_entry_part_weights(request),
    )
    return EmaBacktestRun(
        result=result,
        signal_sources=signal_sources,
        condition_identifier=build_condition_identifier(request, signal_sources),
    )


def build_condition_identifier(request: EmaBacktestRequest, signal_sources: dict[str, str] | None = None) -> str:
    """Build a stable identifier for the strategy/config condition."""

    price_source = (
        f"time_{request.price_time.isoformat(timespec='minutes').replace(':', '')}"
        if request.price_time and request.strategy_name not in _DAILY_CLOSE_STRATEGIES
        else "daily_close"
    )
    ranking_mode = f"rank_{request.candidate_ranking}"
    rotation_mode = "rotate_on" if request.rotate_to_stronger_candidates else "rotate_off"
    compounding_mode = "compound_on" if request.compound_positions else "compound_off"
    overflow_mode = "buy_all_overflow_on" if request.buy_all_overflow_signals else "buy_all_overflow_off"
    mtf_mode = f"mtf_mode_{request.mtf_mode}"
    mtf_cap = f"mtf_cap_{_number_token(request.extra_capital_limit_multiplier)}"
    mtf_extra = f"mtf_extra_{request.max_overflow_positions if request.max_overflow_positions is not None else 'all'}"
    extra_interest = f"extra_interest_{_number_token(request.extra_capital_interest_rate_daily)}"
    monthly_add = f"monthly_add_{_number_token(request.monthly_capital_addition)}"
    withdrawal = f"withdraw_target_{_number_token(request.withdrawal_target or 0)}"
    monthly_withdraw = f"monthly_withdraw_{_number_token(request.monthly_withdrawal_amount)}"
    signal_mode = "index_signals" if signal_sources and any(etf != source for etf, source in signal_sources.items()) else "etf_signals"
    strategy_key = _strategy_identifier(request)
    return f"{strategy_key}_{signal_mode}_{price_source}_max_{request.max_positions}_{ranking_mode}_{rotation_mode}_{compounding_mode}_{overflow_mode}_{mtf_mode}_{mtf_cap}_{mtf_extra}_{extra_interest}_{monthly_add}_{withdrawal}_{monthly_withdraw}"


def _request_signal_sources(request: EmaBacktestRequest) -> dict[str, str]:
    if not request.signal_sources:
        return signal_sources_for(request.symbols)

    signal_sources: dict[str, str] = {}
    for symbol in request.symbols:
        source = request.signal_sources.get(symbol, symbol)
        signal_sources[symbol] = source.strip().upper() if isinstance(source, str) and source.strip() else symbol

    return signal_sources


def _generate_signals_by_source(strategy: EmaTrendStrategy, histories: dict[str, list[dict]]) -> dict[str, list[int]]:
    return {
        symbol: strategy.generate_signals(rows)
        for symbol, rows in histories.items()
        if rows
    }


def _strategy_from_request(request: EmaBacktestRequest):
    if request.strategy_name in {"ema_trend", "ema_entry_low_sell"}:
        return EmaTrendStrategy(window=request.ema_window)
    if request.strategy_name == "weekly_ema_cross":
        return WeeklyEmaCrossStrategy(
            window=request.ema_window,
            confirmation_days=request.confirmation_days,
        )
    if request.strategy_name == "ema_atr_confirmed":
        return EmaAtrConfirmedStrategy(
            ema_window=request.ema_window,
            atr_window=request.atr_window,
            atr_multiplier=request.atr_multiplier,
            confirmation_days=request.confirmation_days,
        )
    if request.strategy_name == "ema_atr_sell_band":
        return EmaAtrSellBandStrategy(
            ema_window=request.ema_window,
            atr_window=request.atr_window,
            atr_multiplier=request.atr_multiplier,
        )
    if request.strategy_name == "rsi_50_cross":
        return Rsi50CrossStrategy(window=request.rsi_window)
    if request.strategy_name == "rsi_divergence_staged":
        return RsiDivergenceStagedStrategy(window=request.rsi_window)

    raise ValueError(f"Unknown strategy: {request.strategy_name}")


def _strategy_identifier(request: EmaBacktestRequest) -> str:
    if request.strategy_name == "rsi_50_cross":
        return f"rsi_{request.rsi_window}_cross_50"
    if request.strategy_name == "rsi_divergence_staged":
        return f"rsi_{request.rsi_window}_divergence_staged_30_70"
    if request.strategy_name == "ema_atr_confirmed":
        multiplier = str(request.atr_multiplier).replace(".", "p")
        return (
            f"ema_{request.ema_window}_rising_confirm_{request.confirmation_days}"
            f"_atr_{request.atr_window}_{multiplier}"
        )
    if request.strategy_name == "ema_atr_sell_band":
        multiplier = str(request.atr_multiplier).replace(".", "p")
        return f"ema_{request.ema_window}_atr_sell_band_{request.atr_window}_{multiplier}"
    if request.strategy_name == "ema_entry_low_sell":
        return f"ema_{request.ema_window}_entry_low_or_entry_ema_sell"
    if request.strategy_name == "weekly_ema_cross":
        return f"weekly_ema_{request.ema_window}_confirm_{request.confirmation_days}_cross"

    return f"ema_{request.ema_window}"


def _sell_price_rule(request: EmaBacktestRequest) -> str:
    if request.strategy_name == "ema_entry_low_sell":
        return "entry_low_or_entry_ema"
    return "close"


def _entry_parts(request: EmaBacktestRequest) -> int:
    if request.strategy_name == "rsi_divergence_staged":
        return 3
    return 1


def _entry_part_weights(request: EmaBacktestRequest) -> list[float] | None:
    if request.strategy_name == "rsi_divergence_staged":
        return [0.50, 0.25, 0.25]
    return None


def _number_token(value: float) -> str:
    return f"{value:.8g}".replace(".", "p").replace("-", "m")


def _map_source_signals_to_etf_dates(
    etf_histories: dict[str, list[dict]],
    signal_sources: dict[str, str],
    signals_by_source: dict[str, list[int]],
    signal_histories: dict[str, list[dict]],
    min_source_rows: int,
) -> dict[str, list[int]]:
    signals_by_symbol: dict[str, list[int]] = {}

    for etf_symbol, etf_rows in etf_histories.items():
        source_symbol = signal_sources.get(etf_symbol, etf_symbol)
        source_rows = signal_histories.get(source_symbol, [])
        source_signals = signals_by_source.get(source_symbol, [])
        source_signal_by_date = {
            row["date"]: signal
            for index, (row, signal) in enumerate(zip(source_rows, source_signals))
            if index + 1 >= min_source_rows
        }
        if source_symbol == etf_symbol:
            etf_signals = signals_by_source.get(etf_symbol, [])
            etf_signal_by_date = {
                row["date"]: signal
                for row, signal in zip(etf_rows, etf_signals)
            }
            signals_by_symbol[etf_symbol] = [
                etf_signal_by_date.get(row["date"], 0)
                for row in etf_rows
            ]
            continue

        mapped_signals: list[int] = []
        last_source_signal = 0
        for row in etf_rows:
            if row["date"] in source_signal_by_date:
                last_source_signal = source_signal_by_date[row["date"]]
            mapped_signals.append(last_source_signal)
        signals_by_symbol[etf_symbol] = mapped_signals

    return signals_by_symbol


def _minimum_signal_rows(request: EmaBacktestRequest) -> int:
    if request.strategy_name in {"rsi_50_cross", "rsi_divergence_staged"}:
        return request.rsi_window
    if request.strategy_name == "weekly_ema_cross":
        return request.ema_window + request.confirmation_days - 1
    if request.strategy_name in {"ema_atr_confirmed", "ema_atr_sell_band"}:
        return max(request.ema_window, request.atr_window)
    return request.ema_window


def _print_signal_source_coverage(
    etf_histories: dict[str, list[dict]],
    signal_sources: dict[str, str],
    signal_histories: dict[str, list[dict]],
    external_availability: dict[str, HistoryAvailability],
) -> None:
    """Print index availability and ETF fallback details to the terminal."""

    for etf_symbol, etf_rows in etf_histories.items():
        source_symbol = signal_sources.get(etf_symbol, etf_symbol)
        if source_symbol == etf_symbol:
            continue

        source_rows = signal_histories.get(source_symbol, [])
        etf_dates = {row["date"] for row in etf_rows}
        source_dates = {row["date"] for row in source_rows}
        index_dates_used = len(etf_dates & source_dates)
        fallback_dates = len(etf_dates - source_dates)
        requested_range = _format_row_range(etf_rows)
        source_range = _format_row_range(source_rows)
        available_range = _format_availability(external_availability.get(source_symbol))

        print(
            "[Signal Source] "
            f"{etf_symbol}: source={source_symbol}; "
            f"requested ETF range={requested_range}; "
            f"source rows in requested range={source_range}; "
            f"Yahoo available range={available_range}; "
            f"using index for {index_dates_used} dates, ETF fallback for {fallback_dates} dates."
        )


def _format_row_range(rows: list[dict]) -> str:
    dates = [row["date"] for row in rows if row.get("date") is not None]
    if not dates:
        return "unavailable"

    return f"{min(dates).isoformat()} to {max(dates).isoformat()} ({len(dates)} rows)"


def _format_availability(availability: HistoryAvailability | None) -> str:
    if availability is None:
        return "not checked"
    if availability.error:
        return f"unavailable ({availability.error})"
    if availability.first_date is None or availability.last_date is None:
        return "unavailable"

    return f"{availability.first_date.isoformat()} to {availability.last_date.isoformat()} ({availability.rows} rows)"


_DAILY_CLOSE_STRATEGIES = {
    "ema_trend",
    "weekly_ema_cross",
    "rsi_50_cross",
    "rsi_divergence_staged",
    "ema_atr_confirmed",
    "ema_atr_sell_band",
    "ema_entry_low_sell",
}
