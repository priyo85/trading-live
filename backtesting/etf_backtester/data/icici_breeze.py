"""ICICI Direct Breeze market data provider."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from backtesting.etf_backtester.config.etf_universe import strip_exchange
from backtesting.etf_backtester.config.json_loader import load_json_config
from backtesting.etf_backtester.data.yahoo_finance import PriceQuote


ICICI_SYMBOL_ALIASES_PATH = Path(__file__).resolve().parents[1] / "config" / "icici_symbol_aliases.json"
PROVIDER_NAME = "icici_breeze"


@dataclass(frozen=True)
class BreezeCredentials:
    api_key: str
    api_secret: str
    session_token: str


@dataclass(frozen=True)
class BreezeInstrument:
    stock_code: str
    exchange_code: str = "NSE"
    product_type: str = "cash"
    expiry_date: str = ""
    right: str = ""
    strike_price: str = ""


class IciciBreezeProvider:
    """Historical and quote data via ICICI Direct Breeze."""

    name = PROVIDER_NAME

    def __init__(self, client, aliases: dict[str, str] | None = None) -> None:
        self.client = client
        self.aliases = aliases or load_icici_symbol_aliases()

    def supports_symbol(self, source_symbol: str) -> bool:
        return self.instrument(source_symbol) is not None

    def stock_code(self, source_symbol: str) -> str | None:
        instrument = self.instrument(source_symbol)
        return instrument.stock_code if instrument else None

    def instrument(self, source_symbol: str) -> BreezeInstrument | None:
        normalized = source_symbol.strip().upper()
        if normalized in self.aliases:
            return _instrument_from_alias(self.aliases[normalized])
        if not normalized.startswith("NSE:"):
            return None

        stock_code = strip_exchange(normalized)
        if stock_code.startswith("NIFTY_") or stock_code.startswith("CNX"):
            return None
        return BreezeInstrument(stock_code=stock_code)

    def historical_prices(
        self,
        source_symbol: str,
        start_date: date,
        end_date: date,
        price_time: time | None = None,
        intraday_interval: str = "5m",
    ) -> list[dict]:
        instrument = self.instrument(source_symbol)
        if instrument is None:
            raise RuntimeError(f"ICICI Breeze has no stock code configured for {source_symbol}")

        interval = _breeze_interval(price_time, intraday_interval)
        rows: list[dict] = []
        chunk_days = 30 if price_time is not None else 365
        cursor = start_date
        while cursor <= end_date:
            chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
            rows.extend(self._historical_chunk(instrument, interval, cursor, chunk_end, price_time))
            cursor = chunk_end + timedelta(days=1)

        return _merge_rows(rows)

    def quote(self, source_symbol: str) -> PriceQuote:
        instrument = self.instrument(source_symbol)
        if instrument is None:
            raise RuntimeError(f"ICICI Breeze has no stock code configured for {source_symbol}")

        response = self.client.get_quotes(
            stock_code=instrument.stock_code,
            exchange_code=instrument.exchange_code,
            expiry_date=instrument.expiry_date,
            product_type=instrument.product_type,
            right=instrument.right,
            strike_price=instrument.strike_price,
        )
        item = _first_success(response)
        price = _numeric_value(item.get("ltp") or item.get("last") or item.get("close"))
        if price is None:
            raise RuntimeError(f"ICICI Breeze returned no LTP for {source_symbol}")

        return PriceQuote(
            source_symbol=source_symbol,
            yahoo_symbol=f"ICICI:{instrument.exchange_code}:{instrument.stock_code}",
            price=price,
            currency="INR",
            market_time=_parse_quote_time(item.get("ltt")),
        )

    def _historical_chunk(
        self,
        instrument: BreezeInstrument,
        interval: str,
        start_date: date,
        end_date: date,
        price_time: time | None,
    ) -> list[dict]:
        response = self.client.get_historical_data_v2(
            interval=interval,
            from_date=_breeze_date(start_date, start_of_day=True),
            to_date=_breeze_date(end_date, start_of_day=False),
            stock_code=instrument.stock_code,
            exchange_code=instrument.exchange_code,
            product_type=instrument.product_type,
            expiry_date=instrument.expiry_date,
            right=instrument.right,
            strike_price=instrument.strike_price,
        )
        rows = _success_rows(response)
        if price_time is None:
            return [_history_row(row, include_time=False) for row in rows]

        grouped: dict[date, dict] = {}
        for row in rows:
            parsed = _history_row(row, include_time=True)
            row_time = _parse_row_time(parsed.get("time"))
            if row_time is None or row_time > price_time:
                continue
            grouped[parsed["date"]] = parsed
        return [grouped[row_date] for row_date in sorted(grouped)]


def create_provider_from_env() -> tuple[IciciBreezeProvider | None, str | None]:
    credentials = _credentials_from_env()
    if credentials is None:
        return None, "ICICI Breeze credentials are not configured"

    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        return None, "breeze-connect is not installed"

    client = BreezeConnect(api_key=credentials.api_key)
    client.generate_session(api_secret=credentials.api_secret, session_token=credentials.session_token)
    return IciciBreezeProvider(client), None


def load_icici_symbol_aliases(path: str | Path = ICICI_SYMBOL_ALIASES_PATH) -> dict[str, str | dict[str, Any]]:
    data = load_json_config(path)
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError(f"Expected aliases object in {path}")
    parsed: dict[str, str | dict[str, Any]] = {}
    for source_symbol, value in aliases.items():
        normalized_source = str(source_symbol).strip().upper()
        if not normalized_source:
            continue
        if isinstance(value, dict):
            stock_code = str(value.get("stock_code", "")).strip().upper()
            if not stock_code:
                continue
            parsed[normalized_source] = {
                "stock_code": stock_code,
                "exchange_code": str(value.get("exchange_code", "NSE")).strip().upper() or "NSE",
                "product_type": str(value.get("product_type", "cash")).strip().lower() or "cash",
                "expiry_date": str(value.get("expiry_date", "")).strip(),
                "right": str(value.get("right", "")).strip().lower(),
                "strike_price": str(value.get("strike_price", "")).strip(),
            }
            continue

        stock_code = str(value).strip().upper()
        if stock_code:
            parsed[normalized_source] = stock_code

    return parsed


def _instrument_from_alias(value: str | dict[str, Any]) -> BreezeInstrument:
    if isinstance(value, dict):
        return BreezeInstrument(
            stock_code=str(value.get("stock_code", "")).strip().upper(),
            exchange_code=str(value.get("exchange_code", "NSE")).strip().upper() or "NSE",
            product_type=str(value.get("product_type", "cash")).strip().lower() or "cash",
            expiry_date=str(value.get("expiry_date", "")).strip(),
            right=str(value.get("right", "")).strip().lower(),
            strike_price=str(value.get("strike_price", "")).strip(),
        )
    return BreezeInstrument(stock_code=str(value).strip().upper())


def _credentials_from_env() -> BreezeCredentials | None:
    api_key = os.getenv("ICICI_BREEZE_API_KEY") or os.getenv("BREEZE_API_KEY")
    api_secret = os.getenv("ICICI_BREEZE_API_SECRET") or os.getenv("BREEZE_API_SECRET")
    session_token = os.getenv("ICICI_BREEZE_SESSION_TOKEN") or os.getenv("BREEZE_SESSION_TOKEN")
    if not api_key or not api_secret or not session_token:
        return None
    return BreezeCredentials(api_key=api_key, api_secret=api_secret, session_token=session_token)


def _breeze_interval(price_time: time | None, intraday_interval: str) -> str:
    if price_time is None:
        return "1day"

    interval = intraday_interval.strip().lower()
    mapping = {
        "1m": "1minute",
        "1min": "1minute",
        "1minute": "1minute",
        "5m": "5minute",
        "5min": "5minute",
        "5minute": "5minute",
        "30m": "30minute",
        "30min": "30minute",
        "30minute": "30minute",
    }
    if interval not in mapping:
        raise ValueError("ICICI Breeze supports intraday intervals: 1m, 5m, 30m")
    return mapping[interval]


def _breeze_date(value: date, start_of_day: bool) -> str:
    clock = "00:00:00" if start_of_day else "23:59:59"
    return f"{value.isoformat()}T{clock}.000Z"


def _success_rows(response: dict[str, Any]) -> list[dict]:
    error = response.get("Error") if isinstance(response, dict) else None
    if error:
        raise RuntimeError(f"ICICI Breeze error: {error}")
    success = response.get("Success") if isinstance(response, dict) else None
    if not isinstance(success, list):
        raise RuntimeError("ICICI Breeze response did not include a Success list")
    return [row for row in success if isinstance(row, dict)]


def _first_success(response: dict[str, Any]) -> dict:
    rows = _success_rows(response)
    if not rows:
        raise RuntimeError("ICICI Breeze response returned no rows")
    return rows[0]


def _history_row(row: dict, include_time: bool) -> dict:
    timestamp = _parse_history_datetime(row.get("datetime"))
    close = _numeric_value(row.get("close"))
    if timestamp is None or close is None:
        raise RuntimeError(f"ICICI Breeze returned unusable history row: {row}")

    parsed = {
        "date": timestamp.date(),
        "open": _numeric_value(row.get("open")) or close,
        "high": _numeric_value(row.get("high")) or close,
        "low": _numeric_value(row.get("low")) or close,
        "close": close,
        "volume": _numeric_value(row.get("volume")) or 0.0,
    }
    if include_time:
        parsed["time"] = timestamp.time().isoformat(timespec="minutes")
    return parsed


def _parse_history_datetime(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_quote_time(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%y %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_row_time(value) -> time | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _numeric_value(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_rows(rows: Iterable[dict]) -> list[dict]:
    rows_by_key: dict[tuple[date, str], dict] = {}
    for row in rows:
        row_date = row.get("date")
        if not isinstance(row_date, date):
            continue
        rows_by_key[(row_date, str(row.get("time") or ""))] = row
    return [rows_by_key[key] for key in sorted(rows_by_key)]
