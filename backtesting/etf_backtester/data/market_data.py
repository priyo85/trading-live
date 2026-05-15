"""Market data facade with ICICI Breeze primary and Yahoo/NSE fallback."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Iterable

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE
from backtesting.etf_backtester.data.icici_breeze import PROVIDER_NAME, create_provider_from_env
from backtesting.etf_backtester.data.sqlite_cache import CandleCache
from backtesting.etf_backtester.data.yahoo_finance import (
    HistoryAvailability,
    PriceQuote,
    fetch_current_prices as fetch_yahoo_current_prices,
    fetch_historical_prices as fetch_yahoo_historical_prices,
    fetch_history_availability as fetch_yahoo_history_availability,
    fetch_max_close_history as fetch_yahoo_max_close_history,
    format_price_table,
)
from backtesting.market_data.dhanhq import fetch_dhan_current_prices


def fetch_current_prices(symbols: Iterable[str] = ETF_UNIVERSE) -> list[PriceQuote]:
    """Fetch quotes from DhanHQ/ICICI/Yahoo, depending on local configuration."""

    symbol_list = list(symbols)
    if _use_dhan_live_quotes():
        dhan_quotes, fallback_symbols = fetch_dhan_current_prices(symbol_list, PriceQuote)
        if not fallback_symbols:
            return dhan_quotes
        return dhan_quotes + _fetch_non_dhan_current_prices(fallback_symbols)

    return _fetch_non_dhan_current_prices(symbol_list)


def _fetch_non_dhan_current_prices(symbols: Iterable[str]) -> list[PriceQuote]:
    provider = _icici_provider()
    if provider is None:
        return fetch_yahoo_current_prices(symbols)

    quotes: list[PriceQuote] = []
    fallback_symbols: list[str] = []
    for source_symbol in symbols:
        if not provider.supports_symbol(source_symbol):
            fallback_symbols.append(source_symbol)
            continue
        try:
            quotes.append(provider.quote(source_symbol))
        except Exception as exc:
            print(f"[ICICI Breeze] {source_symbol}: quote failed; using Yahoo/NSE fallback. {exc}")
            fallback_symbols.append(source_symbol)

    if fallback_symbols:
        quotes.extend(fetch_yahoo_current_prices(fallback_symbols))
    return quotes


def fetch_historical_prices(
    symbols: Iterable[str],
    start_date: date,
    end_date: date,
    price_time: time | None = None,
    intraday_interval: str = "5m",
) -> dict[str, list[dict]]:
    """Fetch OHLCV history from ICICI Breeze when configured, then Yahoo/NSE fallback."""

    provider = _icici_provider()
    if provider is None:
        return fetch_yahoo_historical_prices(symbols, start_date, end_date, price_time, intraday_interval)

    cache = CandleCache()
    histories: dict[str, list[dict]] = {}
    fallback_symbols: list[str] = []
    timeframe = _timeframe_key(price_time, intraday_interval)

    for source_symbol in symbols:
        if not provider.supports_symbol(source_symbol):
            fallback_symbols.append(source_symbol)
            continue

        try:
            rows = _cached_provider_history(cache, provider, source_symbol, start_date, end_date, price_time, intraday_interval, timeframe)
        except Exception as exc:
            print(f"[ICICI Breeze] {source_symbol}: history failed; using Yahoo/NSE fallback. {exc}")
            fallback_symbols.append(source_symbol)
            continue

        if rows:
            histories[source_symbol] = rows
        else:
            fallback_symbols.append(source_symbol)

    if fallback_symbols:
        histories.update(fetch_yahoo_historical_prices(fallback_symbols, start_date, end_date, price_time, intraday_interval))
    return histories


def fetch_max_close_history(symbols: Iterable[str]) -> dict[str, list[dict]]:
    """Fetch up to ten years of ICICI daily closes, then Yahoo/NSE fallback."""

    provider = _icici_provider()
    if provider is None:
        return fetch_yahoo_max_close_history(symbols)

    end_date = date.today()
    start_date = end_date - timedelta(days=3650)
    daily_histories = fetch_historical_prices(symbols, start_date, end_date)
    fallback = {
        symbol
        for symbol, rows in daily_histories.items()
        if not rows
    }
    missing = [symbol for symbol in symbols if symbol not in daily_histories]
    fallback.update(missing)

    histories = {
        symbol: [{"date": row["date"], "close": row["close"]} for row in rows if "date" in row and "close" in row]
        for symbol, rows in daily_histories.items()
        if rows
    }
    if fallback:
        histories.update(fetch_yahoo_max_close_history(sorted(fallback)))
    return histories


def fetch_history_availability(symbols: Iterable[str]) -> dict[str, HistoryAvailability]:
    """Return provider availability, falling back to Yahoo/NSE availability checks."""

    provider = _icici_provider()
    if provider is None:
        return fetch_yahoo_history_availability(symbols)

    histories = fetch_max_close_history(symbols)
    availability: dict[str, HistoryAvailability] = {}
    fallback_symbols: list[str] = []
    for source_symbol in symbols:
        rows = histories.get(source_symbol, [])
        if not rows or not provider.supports_symbol(source_symbol):
            fallback_symbols.append(source_symbol)
            continue
        dates = [row["date"] for row in rows if isinstance(row.get("date"), date)]
        availability[source_symbol] = HistoryAvailability(
            source_symbol=source_symbol,
            yahoo_symbol=f"ICICI:{provider.stock_code(source_symbol)}",
            first_date=min(dates) if dates else None,
            last_date=max(dates) if dates else None,
            rows=len(dates),
        )

    if fallback_symbols:
        availability.update(fetch_yahoo_history_availability(fallback_symbols))
    return availability


def _cached_provider_history(
    cache: CandleCache,
    provider,
    source_symbol: str,
    start_date: date,
    end_date: date,
    price_time: time | None,
    intraday_interval: str,
    timeframe: str,
) -> list[dict]:
    fetch_end_date = _latest_fetchable_daily_date(end_date) if price_time is None else end_date
    for missing_start, missing_end in cache.missing_ranges(provider.name, source_symbol, timeframe, start_date, fetch_end_date):
        print(f"[ICICI Breeze] {source_symbol}: fetching {missing_start} to {missing_end}.")
        rows = provider.historical_prices(source_symbol, missing_start, missing_end, price_time, intraday_interval)
        cache.save_rows(provider.name, source_symbol, timeframe, rows)
        cache.mark_attempted(provider.name, source_symbol, timeframe, missing_start, missing_end)

    return cache.rows(provider.name, source_symbol, timeframe, start_date, end_date)


def _icici_provider():
    provider_mode = os.getenv("ETF_DATA_PROVIDER", "").strip().lower()
    if provider_mode in {"yahoo", "yfinance"}:
        return None

    provider, error = create_provider_from_env()
    if provider is not None:
        return provider
    if provider_mode in {"icici", PROVIDER_NAME}:
        print(f"[ICICI Breeze] disabled: {error}")
    return None


def _use_dhan_live_quotes() -> bool:
    provider = (
        os.getenv("SWING_LIVE_PRICE_PROVIDER")
        or os.getenv("ETF_LIVE_PRICE_PROVIDER")
        or os.getenv("ETF_DATA_PROVIDER")
        or "auto"
    ).strip().lower()
    return provider in {"auto", "dhan", "dhanhq"}


def _timeframe_key(price_time: time | None, intraday_interval: str) -> str:
    if price_time is None:
        return "daily_close"
    return f"{intraday_interval}_{price_time.isoformat(timespec='minutes')}"


def _latest_fetchable_daily_date(value: date) -> date:
    expected = value
    if expected == date.today() and datetime.now().time() < time(18, 0):
        expected -= timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    return expected
