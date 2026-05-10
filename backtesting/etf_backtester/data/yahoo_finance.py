"""Yahoo Finance data provider for ETF prices."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE, NSE_INDEX_ALIASES, strip_exchange, to_yahoo_symbol
from backtesting.etf_backtester.data.sqlite_cache import CandleCache
from backtesting.etf_backtester.utils.paths import PACKAGE_ROOT


HISTORY_CACHE_DIR = PACKAGE_ROOT / "data" / "cache" / "history"
AVAILABILITY_CACHE_DIR = PACKAGE_ROOT / "data" / "cache" / "availability"
YAHOO_PROVIDER_NAME = "yahoo_finance"
MAX_CACHE_START = date(1900, 1, 1)
MAX_CACHE_END = date(9999, 12, 31)
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/reports-indices-historical-index-data",
}


@dataclass(frozen=True)
class PriceQuote:
    """Latest available market quote for an ETF."""

    source_symbol: str
    yahoo_symbol: str
    price: float | None
    currency: str | None = None
    market_time: datetime | None = None
    error: str | None = None


@dataclass(frozen=True)
class HistoryAvailability:
    """Available historical date range for a Yahoo Finance source."""

    source_symbol: str
    yahoo_symbol: str
    first_date: date | None
    last_date: date | None
    rows: int = 0
    error: str | None = None


def fetch_current_prices(symbols: Iterable[str] = ETF_UNIVERSE) -> list[PriceQuote]:
    """Fetch current or latest available prices from Yahoo Finance."""

    yf = _try_import_yfinance()
    quotes: list[PriceQuote] = []

    for source_symbol in symbols:
        yahoo_symbol = to_yahoo_symbol(source_symbol)
        try:
            quotes.append(_fetch_quote(source_symbol, yahoo_symbol, yf))
        except Exception as exc:
            alternate_symbol = _alternate_live_yahoo_symbol(source_symbol, yahoo_symbol)
            if alternate_symbol:
                try:
                    quotes.append(_fetch_quote(source_symbol, alternate_symbol, yf))
                    continue
                except Exception as alternate_exc:
                    exc = RuntimeError(f"{exc}; alternate {alternate_symbol} failed: {alternate_exc}")
            quotes.append(PriceQuote(source_symbol=source_symbol, yahoo_symbol=yahoo_symbol, price=None, error=str(exc)))

    return quotes


def fetch_history_availability(symbols: Iterable[str]) -> dict[str, HistoryAvailability]:
    """Fetch the maximum available daily history range for each source symbol."""

    yf = _try_import_yfinance()
    availability: dict[str, HistoryAvailability] = {}

    for source_symbol in symbols:
        yahoo_symbol = to_yahoo_symbol(source_symbol)
        try:
            rows = _cached_max_history(source_symbol, yahoo_symbol, yf)
        except Exception as exc:
            try:
                rows = _max_history_from_chart_api(yahoo_symbol)
            except Exception as fallback_exc:
                error = f"{exc}; chart API fallback failed: {fallback_exc}"
                _print_yahoo_error(source_symbol, yahoo_symbol, error)
                availability[source_symbol] = HistoryAvailability(
                    source_symbol=source_symbol,
                    yahoo_symbol=yahoo_symbol,
                    first_date=None,
                    last_date=None,
                    error=error,
                )
                continue

        availability[source_symbol] = _availability_from_rows(source_symbol, yahoo_symbol, rows)

    return availability


def fetch_max_close_history(symbols: Iterable[str]) -> dict[str, list[dict]]:
    """Fetch cached maximum daily close history for ATH calculations."""

    yf = _try_import_yfinance()
    histories: dict[str, list[dict]] = {}

    for source_symbol in symbols:
        yahoo_symbol = to_yahoo_symbol(source_symbol)
        try:
            histories[source_symbol] = _cached_max_history(source_symbol, yahoo_symbol, yf)
        except Exception as exc:
            _print_yahoo_error(source_symbol, yahoo_symbol, f"max close history failed: {exc}")
            try:
                histories[source_symbol] = _max_history_from_chart_api(yahoo_symbol)
            except Exception as fallback_exc:
                _print_yahoo_error(source_symbol, yahoo_symbol, f"max close chart API fallback failed: {fallback_exc}")
                histories[source_symbol] = []

    return histories


def fetch_historical_prices(
    symbols: Iterable[str],
    start_date: date,
    end_date: date,
    price_time: time | None = None,
    intraday_interval: str = "5m",
) -> dict[str, list[dict]]:
    """Fetch daily historical OHLCV rows for each ETF symbol."""

    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    yf = _try_import_yfinance()
    histories: dict[str, list[dict]] = {}

    for source_symbol in symbols:
        yahoo_symbol = to_yahoo_symbol(source_symbol)
        histories[source_symbol] = _cached_history(
            yf,
            source_symbol,
            yahoo_symbol,
            start_date,
            end_date,
            price_time,
            intraday_interval,
        )

    return histories


def _fetch_quote(source_symbol: str, yahoo_symbol: str, yf) -> PriceQuote:
    if _nse_index_names(source_symbol):
        try:
            return _quote_from_nse_index_api(source_symbol, yahoo_symbol)
        except Exception:
            pass

    if yf is None:
        try:
            return _quote_from_chart_api(source_symbol, yahoo_symbol)
        except Exception:
            return _quote_from_nse_index_api(source_symbol, yahoo_symbol)

    try:
        return _quote_from_ticker(source_symbol, yahoo_symbol, yf.Ticker(yahoo_symbol))
    except Exception:
        try:
            return _quote_from_chart_api(source_symbol, yahoo_symbol)
        except Exception:
            return _quote_from_nse_index_api(source_symbol, yahoo_symbol)


def _alternate_live_yahoo_symbol(source_symbol: str, yahoo_symbol: str) -> str | None:
    """Use the regular NSE quote as a live fallback for aliased ETF tickers."""

    normalized = source_symbol.strip().upper()
    if normalized not in ETF_UNIVERSE:
        return None

    alternate = f"{strip_exchange(normalized)}.NS"
    if alternate == yahoo_symbol:
        return None
    return alternate


def _cached_history(
    yf,
    source_symbol: str,
    yahoo_symbol: str,
    start_date: date,
    end_date: date,
    price_time: time | None,
    intraday_interval: str,
) -> list[dict]:
    cache = CandleCache()
    timeframe = _history_timeframe_key(price_time, intraday_interval)
    missing_ranges = cache.missing_ranges(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, start_date, end_date)

    if not missing_ranges:
        cached_rows = _rows_in_range(cache.rows(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, start_date, end_date), start_date, end_date)
        attempted_ranges = cache.attempted_ranges(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe)
        if not cached_rows and attempted_ranges:
            print(f"[Cache] {source_symbol} -> {yahoo_symbol}: cached range is empty; retrying {start_date} to {end_date}.")
            missing_ranges = [(start_date, end_date)]
        elif _should_retry_stale_trailing_daily_rows(cached_rows, end_date, price_time):
            retry_start = cached_rows[-1]["date"] + timedelta(days=1)
            print(
                f"[Cache] {source_symbol} -> {yahoo_symbol}: cached daily rows end at "
                f"{cached_rows[-1]['date']}; retrying {retry_start} to {end_date}."
            )
            missing_ranges = [(retry_start, end_date)]
        else:
            print(f"[SQLite Cache] {source_symbol} -> {yahoo_symbol}: using cached data for {start_date} to {end_date}.")
            return cached_rows

    for missing_start, missing_end in missing_ranges:
        print(f"[SQLite Cache] {source_symbol} -> {yahoo_symbol}: fetching {missing_start} to {missing_end}.")
        rows = _fetch_uncached_history(
            yf,
            source_symbol,
            yahoo_symbol,
            missing_start,
            missing_end,
            price_time,
            intraday_interval,
        )
        cache.save_rows(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, rows)
        if rows:
            row_dates = [row["date"] for row in rows if isinstance(row.get("date"), date)]
            if row_dates:
                cache.mark_attempted(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, min(row_dates), max(row_dates))

    return _rows_in_range(cache.rows(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, start_date, end_date), start_date, end_date)


def _should_retry_stale_trailing_daily_rows(
    cached_rows: list[dict],
    end_date: date,
    price_time: time | None,
) -> bool:
    if price_time is not None or not cached_rows:
        return False

    latest_date = cached_rows[-1].get("date")
    if not isinstance(latest_date, date):
        return False

    expected_date = _previous_weekday(end_date)
    return latest_date < expected_date


def _previous_weekday(value: date) -> date:
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def _fetch_uncached_history(
    yf,
    source_symbol: str,
    yahoo_symbol: str,
    start_date: date,
    end_date: date,
    price_time: time | None,
    intraday_interval: str,
) -> list[dict]:
    try:
        if price_time is not None:
            return _intraday_history(yf, yahoo_symbol, start_date, end_date, price_time, intraday_interval)
        if yf is None:
            rows = _history_from_chart_api(yahoo_symbol, start_date, end_date)
            return _history_with_nse_fallback(source_symbol, rows, start_date, end_date)
        try:
            rows = _history_from_yfinance(yf, yahoo_symbol, start_date, end_date)
            return _history_with_nse_fallback(source_symbol, rows, start_date, end_date)
        except Exception:
            rows = _history_from_chart_range_api(yahoo_symbol, start_date, end_date)
            return _history_with_nse_fallback(source_symbol, rows, start_date, end_date)
    except Exception as exc:
        _print_yahoo_error(source_symbol, yahoo_symbol, str(exc))
        try:
            if price_time is not None:
                return _intraday_history_from_chart_api(
                    yahoo_symbol,
                    start_date,
                    end_date,
                    price_time,
                    intraday_interval,
                )
            try:
                rows = _history_from_chart_api(yahoo_symbol, start_date, end_date)
                return _history_with_nse_fallback(source_symbol, rows, start_date, end_date)
            except Exception as chart_exc:
                rows = _history_from_nse_index_api(source_symbol, start_date, end_date)
                if rows:
                    print(f"[NSE] {source_symbol}: using NSE index history for {start_date} to {end_date}.")
                    return rows
                raise chart_exc
        except Exception as fallback_exc:
            _print_yahoo_error(source_symbol, yahoo_symbol, f"chart API fallback failed: {fallback_exc}")
            return []


def format_price_table(quotes: Iterable[PriceQuote]) -> str:
    """Format ETF prices as a CLI-friendly table."""

    rows = [
        (
            quote.source_symbol,
            quote.yahoo_symbol,
            "-" if quote.price is None else f"{quote.price:.2f}",
            quote.currency or "-",
            quote.error or "",
        )
        for quote in quotes
    ]

    headers = ("ETF", "Yahoo", "Price", "Currency", "Error")
    widths = [
        max(len(str(row[index])) for row in (headers, *rows))
        for index in range(len(headers))
    ]

    lines = [_format_row(headers, widths), _format_row(tuple("-" * width for width in widths), widths)]
    lines.extend(_format_row(row, widths) for row in rows)
    return "\n".join(lines)


def _quote_from_chart_api(source_symbol: str, yahoo_symbol: str) -> PriceQuote:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?range=1d&interval=1m"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yahoo Finance request failed for {yahoo_symbol}: {exc}") from exc

    error = data.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo Finance returned an error for {yahoo_symbol}: {error}")

    results = data.get("chart", {}).get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo Finance returned no chart data for {yahoo_symbol}")

    meta = results[0].get("meta", {})
    price = meta.get("regularMarketPrice")
    return PriceQuote(
        source_symbol=source_symbol,
        yahoo_symbol=yahoo_symbol,
        price=None if price is None else float(price),
        currency=meta.get("currency"),
        market_time=_parse_epoch_time(meta.get("regularMarketTime")),
    )


def _quote_from_nse_index_api(source_symbol: str, yahoo_symbol: str) -> PriceQuote:
    names = _nse_index_names(source_symbol)
    if not names:
        raise RuntimeError(f"No NSE index fallback configured for {source_symbol}")

    data = _read_nse_json("https://www.nseindia.com/api/allIndices")
    index_rows = data.get("data") or []
    if not isinstance(index_rows, list):
        raise RuntimeError("NSE all-indices response did not contain a data list")

    expected_names = {_normalize_index_name(name) for name in names}
    for index_row in index_rows:
        if not isinstance(index_row, dict):
            continue
        index_name = _normalize_index_name(str(index_row.get("index", "")))
        if index_name not in expected_names:
            continue

        price = _numeric_value(
            index_row.get("last")
            or index_row.get("lastPrice")
            or index_row.get("last_price")
            or index_row.get("close")
        )
        if price is None:
            break
        return PriceQuote(
            source_symbol=source_symbol,
            yahoo_symbol=yahoo_symbol,
            price=price,
            currency="INR",
            market_time=datetime.now(),
        )

    raise RuntimeError(f"NSE returned no live quote for {source_symbol}")


def _history_with_nse_fallback(source_symbol: str, rows: list[dict], start_date: date, end_date: date) -> list[dict]:
    if not _should_try_nse_history(source_symbol, rows, start_date, end_date):
        return rows

    try:
        nse_rows = _history_from_nse_index_api(source_symbol, start_date, end_date)
    except Exception as exc:
        print(f"[NSE] {source_symbol}: index history fallback failed: {exc}")
        return rows

    if nse_rows:
        print(f"[NSE] {source_symbol}: using NSE index history for {start_date} to {end_date}.")
        return nse_rows

    return rows


def _should_try_nse_history(source_symbol: str, rows: list[dict], start_date: date, end_date: date) -> bool:
    if not _nse_index_names(source_symbol):
        return False

    requested_days = (end_date - start_date).days + 1
    if requested_days < 10:
        return not rows

    return len(rows) < 5


def _should_retry_sparse_max_history(source_symbol: str, rows: list[dict]) -> bool:
    return bool(_nse_index_names(source_symbol) and len(rows) < 200)


def _history_from_nse_index_api(source_symbol: str, start_date: date, end_date: date) -> list[dict]:
    if (end_date - start_date).days > 180:
        rows: list[dict] = []
        cursor = start_date
        while cursor <= end_date:
            chunk_end = min(cursor + timedelta(days=75), end_date)
            try:
                rows = _merge_rows(rows, _history_from_nse_index_api_once(source_symbol, cursor, chunk_end))
            except Exception:
                pass
            cursor = chunk_end + timedelta(days=1)

        if rows:
            return rows

    return _history_from_nse_index_api_once(source_symbol, start_date, end_date)


def _history_from_nse_index_api_once(source_symbol: str, start_date: date, end_date: date) -> list[dict]:
    names = _nse_index_names(source_symbol)
    if not names:
        raise RuntimeError(f"No NSE index fallback configured for {source_symbol}")

    errors: list[str] = []
    for index_name in names:
        try:
            rows = _history_from_nse_index_name(index_name, start_date, end_date)
        except Exception as exc:
            errors.append(f"{index_name}: {exc}")
            continue
        if rows:
            return rows

    if errors:
        raise RuntimeError("; ".join(errors))
    raise RuntimeError(f"NSE returned no rows for {source_symbol}")


def _max_history_from_nse_index_api(source_symbol: str) -> list[dict]:
    if not _nse_index_names(source_symbol):
        raise RuntimeError(f"No NSE index fallback configured for {source_symbol}")

    start_date = date.today() - timedelta(days=3650)
    end_date = date.today()
    try:
        rows = _history_from_nse_index_api(source_symbol, start_date, end_date)
        if len(rows) >= 200:
            return [{"date": row["date"], "close": row["close"]} for row in rows]
    except Exception:
        pass

    rows: list[dict] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=75), end_date)
        try:
            rows = _merge_rows(rows, _history_from_nse_index_api_once(source_symbol, cursor, chunk_end))
        except Exception:
            pass
        cursor = chunk_end + timedelta(days=1)

    if not rows:
        raise RuntimeError(f"NSE returned no max history for {source_symbol}")

    return [{"date": row["date"], "close": row["close"]} for row in rows]


def _history_from_nse_index_name(index_name: str, start_date: date, end_date: date) -> list[dict]:
    url = (
        "https://www.nseindia.com/api/historicalOR/indicesHistory"
        f"?indexType={quote(index_name, safe='')}"
        f"&from={start_date.strftime('%d-%m-%Y')}"
        f"&to={end_date.strftime('%d-%m-%Y')}"
    )
    data = _read_nse_json(url)
    index_rows = data.get("data") or []
    if not isinstance(index_rows, list):
        raise RuntimeError("NSE index history response did not contain a data list")

    rows: list[dict] = []
    for index_row in index_rows:
        if not isinstance(index_row, dict):
            continue

        row_date = _parse_nse_index_date(index_row)
        close = _numeric_value(index_row.get("EOD_CLOSE_INDEX_VAL"))
        if row_date is None or close is None:
            continue

        rows.append(
            {
                "date": row_date,
                "open": _numeric_value(index_row.get("EOD_OPEN_INDEX_VAL")) or close,
                "high": _numeric_value(index_row.get("EOD_HIGH_INDEX_VAL")) or close,
                "low": _numeric_value(index_row.get("EOD_LOW_INDEX_VAL")) or close,
                "close": close,
                "volume": _numeric_value(index_row.get("HIT_TRADED_QTY")) or 0.0,
            }
        )

    return [
        row
        for row in sorted(rows, key=lambda item: item["date"])
        if start_date <= row["date"] <= end_date
    ]


def _parse_nse_index_date(index_row: dict) -> date | None:
    timestamp = index_row.get("EOD_TIMESTAMP")
    if isinstance(timestamp, str):
        try:
            return datetime.strptime(timestamp.title(), "%d-%b-%Y").date()
        except ValueError:
            pass

    iso_timestamp = index_row.get("HI_TIMESTAMP")
    if isinstance(iso_timestamp, str):
        try:
            return datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    return None


def _read_nse_json(url: str) -> dict:
    request = Request(url, headers=NSE_HEADERS)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"NSE request failed: {exc}") from exc


def _nse_index_names(source_symbol: str) -> tuple[str, ...]:
    return NSE_INDEX_ALIASES.get(source_symbol.strip().upper(), ())


def _normalize_index_name(value: str) -> str:
    return " ".join(value.strip().upper().split())


def _history_from_yfinance(yf, yahoo_symbol: str, start_date: date, end_date: date) -> list[dict]:
    ticker = yf.Ticker(yahoo_symbol)
    with _quiet_yfinance():
        history = ticker.history(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
        )
    if history.empty:
        raise RuntimeError(f"Yahoo Finance returned no history for {yahoo_symbol}")

    rows: list[dict] = []
    for index, row in history.iterrows():
        close = _first_present(row, "Close")
        if close is None:
            continue
        rows.append(
            {
                "date": index.date(),
                "open": float(_first_present(row, "Open") or close),
                "high": float(_first_present(row, "High") or close),
                "low": float(_first_present(row, "Low") or close),
                "close": float(close),
                "volume": float(_first_present(row, "Volume") or 0),
            }
        )

    return rows


def _max_history_from_yfinance(yf, yahoo_symbol: str) -> list[dict]:
    ticker = yf.Ticker(yahoo_symbol)
    with _quiet_yfinance():
        history = ticker.history(period="max", interval="1d", auto_adjust=False)
    if history.empty:
        raise RuntimeError(f"Yahoo Finance returned no max history for {yahoo_symbol}")

    rows: list[dict] = []
    for index, row in history.iterrows():
        close = _first_present(row, "Close")
        if close is None:
            continue
        rows.append(
            {
                "date": index.date(),
                "close": float(close),
            }
        )

    return rows


def _cached_max_history(source_symbol: str, yahoo_symbol: str, yf) -> list[dict]:
    cache = CandleCache()
    timeframe = "max_daily"
    rows = cache.rows(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, MAX_CACHE_START, MAX_CACHE_END)
    attempted_ranges = cache.attempted_ranges(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe)
    if attempted_ranges and rows and not _should_retry_sparse_max_history(source_symbol, rows):
        print(f"[SQLite Cache] {source_symbol} -> {yahoo_symbol}: using cached max availability.")
        return rows
    if attempted_ranges and not rows:
        print(f"[SQLite Cache] {source_symbol} -> {yahoo_symbol}: cached max availability is empty; retrying.")
    if attempted_ranges and _should_retry_sparse_max_history(source_symbol, rows):
        print(f"[SQLite Cache] {source_symbol} -> {yahoo_symbol}: cached max availability is sparse; retrying.")

    print(f"[SQLite Cache] {source_symbol} -> {yahoo_symbol}: fetching max availability.")
    try:
        fetched_rows = _max_history_from_yfinance(yf, yahoo_symbol) if yf is not None else _max_history_from_chart_api(yahoo_symbol)
    except Exception:
        try:
            fetched_rows = _max_history_from_chart_api(yahoo_symbol)
        except Exception:
            try:
                fetched_rows = _history_from_chart_range(yahoo_symbol, "10y")
            except Exception:
                fetched_rows = _max_history_from_nse_index_api(source_symbol)
    if _should_retry_sparse_max_history(source_symbol, fetched_rows):
        try:
            nse_rows = _max_history_from_nse_index_api(source_symbol)
            if nse_rows:
                print(f"[NSE] {source_symbol}: using NSE index max history.")
                fetched_rows = nse_rows
        except Exception as exc:
            print(f"[NSE] {source_symbol}: max history fallback failed: {exc}")

    rows = _merge_rows([], fetched_rows)
    if rows:
        cache.save_rows(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, rows)
        cache.mark_attempted(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, MAX_CACHE_START, MAX_CACHE_END)
    return rows


def _intraday_history(
    yf,
    yahoo_symbol: str,
    start_date: date,
    end_date: date,
    price_time: time,
    intraday_interval: str,
) -> list[dict]:
    if yf is None:
        return _intraday_history_from_chart_api(yahoo_symbol, start_date, end_date, price_time, intraday_interval)

    ticker = yf.Ticker(yahoo_symbol)
    with _quiet_yfinance():
        history = ticker.history(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval=intraday_interval,
            auto_adjust=False,
        )
    if history.empty:
        raise RuntimeError(f"Yahoo Finance returned no intraday history for {yahoo_symbol}")

    grouped: dict[date, dict] = {}
    for index, row in history.iterrows():
        timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
        if timestamp.time() > price_time:
            continue

        close = _first_present(row, "Close")
        if close is None:
            continue

        grouped[timestamp.date()] = {
            "date": timestamp.date(),
            "time": timestamp.time().isoformat(timespec="minutes"),
            "open": float(_first_present(row, "Open") or close),
            "high": float(_first_present(row, "High") or close),
            "low": float(_first_present(row, "Low") or close),
            "close": float(close),
            "volume": float(_first_present(row, "Volume") or 0),
        }

    return [grouped[day] for day in sorted(grouped)]


def _intraday_history_from_chart_api(
    yahoo_symbol: str,
    start_date: date,
    end_date: date,
    price_time: time,
    intraday_interval: str,
) -> list[dict]:
    period1 = _to_epoch(start_date)
    period2 = _to_epoch(end_date + timedelta(days=1))
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
        f"?period1={period1}&period2={period2}&interval={intraday_interval}"
    )
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yahoo Finance intraday request failed for {yahoo_symbol}: {exc}") from exc

    error = data.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo Finance returned an error for {yahoo_symbol}: {error}")

    results = data.get("chart", {}).get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo Finance returned no intraday history for {yahoo_symbol}")

    result = results[0]
    gmtoffset = int(result.get("meta", {}).get("gmtoffset", 0))
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    grouped: dict[date, dict] = {}
    for index, timestamp in enumerate(timestamps):
        local_timestamp = _local_datetime_from_epoch(timestamp, gmtoffset)
        if local_timestamp.time() > price_time:
            continue

        close = _value_at(closes, index)
        if close is None:
            continue

        grouped[local_timestamp.date()] = {
            "date": local_timestamp.date(),
            "time": local_timestamp.time().isoformat(timespec="minutes"),
            "open": float(_value_at(opens, index) or close),
            "high": float(_value_at(highs, index) or close),
            "low": float(_value_at(lows, index) or close),
            "close": float(close),
            "volume": float(_value_at(volumes, index) or 0),
        }

    return [grouped[day] for day in sorted(grouped)]


def _history_from_chart_api(yahoo_symbol: str, start_date: date, end_date: date) -> list[dict]:
    period1 = _to_epoch(start_date)
    period2 = _to_epoch(end_date + timedelta(days=1))
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yahoo Finance history request failed for {yahoo_symbol}: {exc}") from exc

    error = data.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo Finance returned an error for {yahoo_symbol}: {error}")

    results = data.get("chart", {}).get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo Finance returned no history for {yahoo_symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    rows: list[dict] = []
    for index, timestamp in enumerate(timestamps):
        close = _value_at(closes, index)
        if close is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp).date(),
                "open": float(_value_at(opens, index) or close),
                "high": float(_value_at(highs, index) or close),
                "low": float(_value_at(lows, index) or close),
                "close": float(close),
                "volume": float(_value_at(volumes, index) or 0),
            }
        )

    return rows


def _history_from_chart_range_api(yahoo_symbol: str, start_date: date, end_date: date) -> list[dict]:
    requested_days = max((end_date - start_date).days + 1, 1)
    if requested_days <= 370:
        range_value = "1y"
    elif requested_days <= 370 * 2:
        range_value = "2y"
    elif requested_days <= 370 * 5:
        range_value = "5y"
    else:
        range_value = "10y"

    rows = _history_from_chart_range(yahoo_symbol, range_value)
    filtered = [row for row in rows if start_date <= row["date"] <= end_date]
    if not filtered:
        raise RuntimeError(f"Yahoo Finance returned no range history for {yahoo_symbol}")
    return filtered


def _history_from_chart_range(yahoo_symbol: str, range_value: str) -> list[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?range={range_value}&interval=1d"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yahoo Finance range history request failed for {yahoo_symbol}: {exc}") from exc

    error = data.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo Finance returned an error for {yahoo_symbol}: {error}")

    results = data.get("chart", {}).get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo Finance returned no range history for {yahoo_symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    rows: list[dict] = []
    for index, timestamp in enumerate(timestamps):
        close = _value_at(closes, index)
        if close is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp).date(),
                "open": float(_value_at(opens, index) or close),
                "high": float(_value_at(highs, index) or close),
                "low": float(_value_at(lows, index) or close),
                "close": float(close),
                "volume": float(_value_at(volumes, index) or 0),
            }
        )

    return rows


def _max_history_from_chart_api(yahoo_symbol: str) -> list[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?range=max&interval=1d"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yahoo Finance max history request failed for {yahoo_symbol}: {exc}") from exc

    error = data.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo Finance returned an error for {yahoo_symbol}: {error}")

    results = data.get("chart", {}).get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo Finance returned no max history for {yahoo_symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []

    rows: list[dict] = []
    for index, timestamp in enumerate(timestamps):
        close = _value_at(closes, index)
        if close is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp).date(),
                "close": float(close),
            }
        )

    return rows


def _quote_from_ticker(source_symbol: str, yahoo_symbol: str, ticker) -> PriceQuote:
    with _quiet_yfinance():
        fast_info = ticker.fast_info
        price = _get_fast_info_value(fast_info, "last_price")
        currency = _get_fast_info_value(fast_info, "currency")
        market_time = _parse_market_time(_get_fast_info_value(fast_info, "last_trade_time"))

        if price is None:
            history = ticker.history(period="5d", interval="1d")
            if not history.empty:
                price = float(history["Close"].dropna().iloc[-1])

    return PriceQuote(
        source_symbol=source_symbol,
        yahoo_symbol=yahoo_symbol,
        price=None if price is None else float(price),
        currency=None if currency is None else str(currency),
        market_time=market_time,
    )


def _get_fast_info_value(fast_info, key: str):
    try:
        return fast_info.get(key)
    except AttributeError:
        return getattr(fast_info, key, None)


def _parse_market_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None


def _parse_epoch_time(value) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    return None


def _local_datetime_from_epoch(timestamp: int, gmtoffset: int) -> datetime:
    return datetime.utcfromtimestamp(timestamp + gmtoffset)


def _to_epoch(value: date) -> int:
    return int(datetime.combine(value, time.min).timestamp())


def _value_at(values: list, index: int):
    if index >= len(values):
        return None
    return values[index]


def _first_present(row, key: str):
    value = row.get(key)
    try:
        if value != value:
            return None
    except TypeError:
        return value
    return value


def _availability_from_rows(source_symbol: str, yahoo_symbol: str, rows: list[dict]) -> HistoryAvailability:
    dates = [row["date"] for row in rows if row.get("date") is not None]
    if not dates:
        return HistoryAvailability(
            source_symbol=source_symbol,
            yahoo_symbol=yahoo_symbol,
            first_date=None,
            last_date=None,
            error="Yahoo Finance returned no usable dated rows.",
        )

    return HistoryAvailability(
        source_symbol=source_symbol,
        yahoo_symbol=yahoo_symbol,
        first_date=min(dates),
        last_date=max(dates),
        rows=len(dates),
    )


def _print_yahoo_error(source_symbol: str, yahoo_symbol: str, message: str) -> None:
    print(f"[Yahoo Finance] {source_symbol} -> {yahoo_symbol}: {message}")


def _history_cache_path(yahoo_symbol: str, price_time: time | None, intraday_interval: str) -> Path:
    return HISTORY_CACHE_DIR / f"{_safe_cache_key(yahoo_symbol)}_{_safe_cache_key(_history_timeframe_key(price_time, intraday_interval))}.json"


def _history_timeframe_key(price_time: time | None, intraday_interval: str) -> str:
    return "daily_close" if price_time is None else f"{intraday_interval}_{price_time.isoformat(timespec='minutes')}"


def _availability_cache_path(yahoo_symbol: str) -> Path:
    return AVAILABILITY_CACHE_DIR / f"{_safe_cache_key(yahoo_symbol)}_max_daily.json"


def _safe_cache_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def _load_history_cache(path: Path) -> dict:
    if not path.exists():
        return {"rows": [], "attempted_ranges": []}

    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {"rows": [], "attempted_ranges": []}

    rows = data.get("rows", [])
    attempted_ranges = data.get("attempted_ranges", [])
    if not isinstance(rows, list) or not isinstance(attempted_ranges, list):
        return {"rows": [], "attempted_ranges": []}

    return {
        "rows": [_deserialize_history_row(row) for row in rows if isinstance(row, dict)],
        "attempted_ranges": [
            row
            for row in attempted_ranges
            if isinstance(row, dict) and isinstance(row.get("start"), str) and isinstance(row.get("end"), str)
        ],
    }


def _save_history_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "rows": [_serialize_history_row(row) for row in _merge_rows([], cache["rows"])],
        "attempted_ranges": _merge_ranges(cache["attempted_ranges"]),
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def _serialize_history_row(row: dict) -> dict:
    serialized = dict(row)
    if hasattr(serialized.get("date"), "isoformat"):
        serialized["date"] = serialized["date"].isoformat()
    return serialized


def _deserialize_history_row(row: dict) -> dict:
    deserialized = dict(row)
    row_date = deserialized.get("date")
    if isinstance(row_date, str):
        try:
            deserialized["date"] = datetime.strptime(row_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    return deserialized


def _rows_in_range(rows: list[dict], start_date: date, end_date: date) -> list[dict]:
    return [
        row
        for row in _drop_synthetic_flat_zero_volume_rows(sorted(rows, key=lambda item: item["date"]))
        if isinstance(row.get("date"), date) and start_date <= row["date"] <= end_date
    ]


def _effective_attempted_ranges(attempted_ranges: list[dict], rows: list[dict]) -> list[dict]:
    row_dates = [row["date"] for row in rows if isinstance(row.get("date"), date)]
    if not row_dates:
        return []

    sorted_dates = sorted(set(row_dates))
    ranges: list[dict] = []
    range_start = sorted_dates[0]
    previous_date = sorted_dates[0]

    for row_date in sorted_dates[1:]:
        if row_date > previous_date + timedelta(days=4):
            ranges.append({"start": range_start.isoformat(), "end": previous_date.isoformat()})
            range_start = row_date
        previous_date = row_date

    ranges.append({"start": range_start.isoformat(), "end": previous_date.isoformat()})
    return _merge_ranges(ranges)


def _merge_rows(existing_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    rows_by_date: dict[date, dict] = {}
    for row in [*existing_rows, *new_rows]:
        row_date = row.get("date")
        if isinstance(row_date, date):
            rows_by_date[row_date] = row

    return _drop_synthetic_flat_zero_volume_rows([rows_by_date[row_date] for row_date in sorted(rows_by_date)])


def _drop_synthetic_flat_zero_volume_rows(rows: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for row in rows:
        if cleaned and _is_synthetic_flat_zero_volume_row(row, cleaned[-1]):
            continue
        cleaned.append(row)
    return cleaned


def _is_synthetic_flat_zero_volume_row(row: dict, previous_row: dict) -> bool:
    volume = _numeric_value(row.get("volume"))
    if volume is None or volume != 0:
        return False

    open_price = _numeric_value(row.get("open"))
    high_price = _numeric_value(row.get("high"))
    low_price = _numeric_value(row.get("low"))
    close_price = _numeric_value(row.get("close"))
    previous_close = _numeric_value(previous_row.get("close"))
    if None in {open_price, high_price, low_price, close_price, previous_close}:
        return False

    return (
        _nearly_equal(open_price, high_price)
        and _nearly_equal(high_price, low_price)
        and _nearly_equal(low_price, close_price)
        and _nearly_equal(close_price, previous_close)
    )


def _numeric_value(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nearly_equal(left: float, right: float) -> bool:
    return abs(left - right) < 0.000001


def _missing_ranges(start_date: date, end_date: date, attempted_ranges: list[dict]) -> list[tuple[date, date]]:
    covered = _covered_ranges(start_date, end_date, attempted_ranges)
    if not covered:
        return [(start_date, end_date)]

    missing: list[tuple[date, date]] = []
    cursor = start_date
    for covered_start, covered_end in covered:
        if cursor < covered_start:
            missing.append((cursor, covered_start - timedelta(days=1)))
        cursor = max(cursor, covered_end + timedelta(days=1))

    if cursor <= end_date:
        missing.append((cursor, end_date))

    return [(range_start, range_end) for range_start, range_end in missing if range_start <= range_end]


def _covered_ranges(start_date: date, end_date: date, attempted_ranges: list[dict]) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    for attempted_range in attempted_ranges:
        try:
            range_start = datetime.strptime(attempted_range["start"], "%Y-%m-%d").date()
            range_end = datetime.strptime(attempted_range["end"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue

        clipped_start = max(start_date, range_start)
        clipped_end = min(end_date, range_end)
        if clipped_start <= clipped_end:
            ranges.append((clipped_start, clipped_end))

    ranges.sort()
    merged: list[tuple[date, date]] = []
    for range_start, range_end in ranges:
        if not merged or range_start > merged[-1][1] + timedelta(days=1):
            merged.append((range_start, range_end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], range_end))

    return merged


def _merge_ranges(attempted_ranges: list[dict]) -> list[dict]:
    parsed_ranges: list[tuple[date, date]] = []
    for attempted_range in attempted_ranges:
        try:
            range_start = datetime.strptime(attempted_range["start"], "%Y-%m-%d").date()
            range_end = datetime.strptime(attempted_range["end"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        if range_start <= range_end:
            parsed_ranges.append((range_start, range_end))

    if not parsed_ranges:
        return []

    parsed_ranges.sort()
    merged: list[tuple[date, date]] = []
    for range_start, range_end in parsed_ranges:
        if not merged or range_start > merged[-1][1] + timedelta(days=1):
            merged.append((range_start, range_end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], range_end))

    return [
        {"start": range_start.isoformat(), "end": range_end.isoformat()}
        for range_start, range_end in merged
    ]


class _quiet_yfinance:
    """Temporarily silence yfinance's noisy missing-ticker messages."""

    def __enter__(self):
        self._logger = logging.getLogger("yfinance")
        self._previous_disabled = self._logger.disabled
        self._logger.disabled = True
        self._stderr_fd = os.dup(2)
        self._devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(self._devnull, 2)
        return self

    def __exit__(self, exc_type, exc, traceback):
        os.dup2(self._stderr_fd, 2)
        os.close(self._stderr_fd)
        os.close(self._devnull)
        self._logger.disabled = self._previous_disabled
        return False


def _format_row(row: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(str(value).ljust(width) for value, width in zip(row, widths))


def _try_import_yfinance():
    try:
        import yfinance as yf
    except ImportError:
        return None
    return yf
