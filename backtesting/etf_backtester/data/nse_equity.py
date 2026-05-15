"""NSE daily equity/ETF candle provider."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar

from backtesting.etf_backtester.config.etf_universe import NSE_INDEX_ALIASES, strip_exchange


PROVIDER_NAME = "nse_equity"
NSE_HOME_URL = "https://www.nseindia.com"
NSE_SECURITY_ARCHIVE_URL = "https://www.nseindia.com/api/historical/securityArchives"
NSE_DAILY_BHAVDATA_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_key}.csv"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/reports/equity-stockWatch",
}


def fetch_historical_prices(symbols: Iterable[str], start_date: date, end_date: date) -> tuple[dict[str, list[dict]], list[str]]:
    """Fetch daily OHLCV history from NSE's daily bhavdata/archive APIs."""

    histories: dict[str, list[dict]] = {}
    fallback_symbols: list[str] = []
    supported_symbols: list[str] = []

    for source_symbol in symbols:
        if not _supports_symbol(source_symbol):
            fallback_symbols.append(source_symbol)
            continue
        supported_symbols.append(source_symbol)

    if supported_symbols:
        try:
            histories.update(_fetch_many_from_daily_bhavdata(supported_symbols, start_date, end_date))
        except Exception as exc:
            print(f"[NSE Equity] daily bhavdata failed; trying security archive fallback. {exc}")

    for source_symbol in supported_symbols:
        if histories.get(source_symbol):
            continue
        try:
            rows = _fetch_one(strip_exchange(source_symbol), start_date, end_date)
        except Exception as exc:
            print(f"[NSE Equity] {source_symbol}: history failed; using fallback. {exc}")
            fallback_symbols.append(source_symbol)
            continue

        if rows:
            histories[source_symbol] = rows
        else:
            fallback_symbols.append(source_symbol)

    return histories, fallback_symbols


def _fetch_one(nse_symbol: str, start_date: date, end_date: date) -> list[dict]:
    rows: list[dict] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=90), end_date)
        rows.extend(_fetch_chunk(nse_symbol, cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return _merge_rows(rows, start_date, end_date)


def _fetch_many_from_daily_bhavdata(symbols: list[str], start_date: date, end_date: date) -> dict[str, list[dict]]:
    source_by_ticker = {strip_exchange(symbol): symbol for symbol in symbols}
    rows_by_symbol: dict[str, list[dict]] = {symbol: [] for symbol in symbols}
    cursor = start_date
    successful_fetches = 0

    while cursor <= end_date:
        if cursor.weekday() >= 5:
            cursor += timedelta(days=1)
            continue

        try:
            records = _read_daily_bhavdata(cursor)
        except RuntimeError:
            cursor += timedelta(days=1)
            continue

        successful_fetches += 1
        for record in records:
            ticker = _first_text(record, "SYMBOL")
            if not ticker:
                continue
            source_symbol = source_by_ticker.get(ticker.upper())
            if source_symbol is None:
                continue
            parsed_rows = _rows_from_payload([record], cursor, cursor)
            if parsed_rows:
                rows_by_symbol[source_symbol].extend(parsed_rows)

        cursor += timedelta(days=1)

    if successful_fetches == 0:
        raise RuntimeError("NSE daily bhavdata returned no downloadable dates.")

    return {
        symbol: _merge_rows(rows, start_date, end_date)
        for symbol, rows in rows_by_symbol.items()
        if rows
    }


def _read_daily_bhavdata(value: date) -> list[dict]:
    url = NSE_DAILY_BHAVDATA_URL.format(date_key=value.strftime("%d%m%Y"))
    text = _read_plain_url(url, with_nse_cookie=False)
    return [_normalize_record(record) for record in csv.DictReader(StringIO(text))]


def _fetch_chunk(nse_symbol: str, start_date: date, end_date: date) -> list[dict]:
    last_error: Exception | None = None
    for url in _security_archive_urls(nse_symbol, start_date, end_date):
        try:
            return _rows_from_payload(_read_nse_payload(url), start_date, end_date)
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def _security_archive_urls(nse_symbol: str, start_date: date, end_date: date) -> list[str]:
    base_params = {
        "from": start_date.strftime("%d-%m-%Y"),
        "to": end_date.strftime("%d-%m-%Y"),
        "symbol": nse_symbol,
        "dataType": "priceVolumeDeliverable",
    }
    urls = []
    for series in ("EQ", "ALL"):
        params = {**base_params, "series": series}
        urls.append(f"{NSE_SECURITY_ARCHIVE_URL}?{urlencode(params)}")
    return urls


def _read_nse_payload(url: str) -> object:
    text = _read_plain_url(url, with_nse_cookie=True)
    stripped = text.lstrip()
    if not stripped:
        return {}
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    return [_normalize_record(record) for record in csv.DictReader(StringIO(text))]


def _read_plain_url(url: str, with_nse_cookie: bool) -> str:
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    try:
        if with_nse_cookie:
            opener.open(Request(NSE_HOME_URL, headers=NSE_HEADERS), timeout=20).close()
        with opener.open(Request(url, headers=NSE_HEADERS), timeout=30) as response:
            return response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"NSE request failed: {exc}") from exc


def _rows_from_payload(payload: object, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
    if isinstance(payload, dict):
        records = payload.get("data") or payload.get("records") or payload.get("rows") or []
    else:
        records = payload

    if not isinstance(records, list):
        return []

    rows: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record = _normalize_record(record)
        series = _first_text(record, "SERIES", "CH_SERIES", "_CH_SERIES", "series")
        if series and series.upper() != "EQ":
            continue

        row_date = _parse_date(_first_present(record, "CH_TIMESTAMP", "_CH_TIMESTAMP", "TIMESTAMP", "mTIMESTAMP", "DATE1", "Date", "DATE", "date"))
        close = _number(_first_present(record, "CH_CLOSING_PRICE", "_CH_CLOSING_PRICE", "CLOSE_PRICE", "CLOSE", "Close", "close", "CH_LAST_TRADED_PRICE", "LAST_PRICE"))
        if row_date is None or close is None:
            continue
        if start_date and row_date < start_date:
            continue
        if end_date and row_date > end_date:
            continue

        rows.append(
            {
                "date": row_date,
                "open": _number(_first_present(record, "CH_OPENING_PRICE", "_CH_OPENING_PRICE", "OPEN_PRICE", "OPEN", "Open", "open")) or close,
                "high": _number(_first_present(record, "CH_TRADE_HIGH_PRICE", "_CH_TRADE_HIGH_PRICE", "HIGH_PRICE", "HIGH", "High", "high")) or close,
                "low": _number(_first_present(record, "CH_TRADE_LOW_PRICE", "_CH_TRADE_LOW_PRICE", "LOW_PRICE", "LOW", "Low", "low")) or close,
                "close": close,
                "volume": _number(_first_present(record, "CH_TOT_TRADED_QTY", "_CH_TOT_TRADED_QTY", "TTL_TRD_QNTY", "VOLUME", "Volume", "volume")) or 0.0,
            }
        )

    return sorted(rows, key=lambda item: item["date"])


def _supports_symbol(source_symbol: str) -> bool:
    normalized = source_symbol.strip().upper()
    if not normalized.startswith("NSE:"):
        return False
    return normalized not in NSE_INDEX_ALIASES


def _merge_rows(rows: list[dict], start_date: date, end_date: date) -> list[dict]:
    merged: dict[date, dict] = {}
    for row in rows:
        row_date = row.get("date")
        if isinstance(row_date, date) and start_date <= row_date <= end_date:
            merged[row_date] = row
    return [merged[row_date] for row_date in sorted(merged)]


def _first_present(record: dict, *keys: str):
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _normalize_record(record: dict) -> dict:
    return {str(key).strip(): value for key, value in record.items()}


def _first_text(record: dict, *keys: str) -> str | None:
    value = _first_present(record, *keys)
    if value is None:
        return None
    return str(value).strip()


def _number(value) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(text.title(), fmt).date()
        except ValueError:
            continue
    return None
