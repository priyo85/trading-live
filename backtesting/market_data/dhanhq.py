"""DhanHQ live quote provider.

The provider uses Dhan's bulk marketfeed LTP endpoint, which is much faster
than fetching one quote per symbol. Credentials are read from environment
variables first, with an optional local credentials JSON fallback.
"""

from __future__ import annotations

import csv
import base64
import binascii
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://api.dhan.co/v2"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CREDENTIALS_PATH = PROJECT_ROOT / "stockanalysis" / "dhanhq" / "data" / "dhan-cred-lima.json"
DEFAULT_SCRIP_MASTER_PATH = PROJECT_ROOT / "stockanalysis" / "dhanhq" / "data" / "api-scrip-master.csv"
SAVED_CREDENTIALS_PATH = PROJECT_ROOT / "backtesting" / "market_data" / "dhan_credentials.json"
PROVIDER_NAME = "dhanhq"
QuoteT = TypeVar("QuoteT")


@dataclass(frozen=True)
class DhanCredentials:
    client_id: str
    access_token: str


def fetch_dhan_current_prices(
    symbols: Iterable[str],
    quote_factory: Callable[..., QuoteT],
) -> tuple[list[QuoteT], list[str]]:
    """Fetch live prices for mapped NSE_EQ symbols.

    Returns a tuple of Dhan quotes and symbols that should be handled by the
    caller's fallback provider.
    """

    symbol_list = list(symbols)
    credentials = load_credentials()
    if credentials is None:
        return [], symbol_list

    security_map = load_security_id_map()
    security_ids_by_symbol: dict[str, str] = {}
    fallback_symbols: list[str] = []
    for source_symbol in symbol_list:
        trading_symbol = normalize_trading_symbol(source_symbol)
        security_id = security_map.get(trading_symbol)
        if security_id:
            security_ids_by_symbol[source_symbol] = security_id
        else:
            fallback_symbols.append(source_symbol)

    if not security_ids_by_symbol:
        return [], fallback_symbols

    start = time.perf_counter()
    prices: dict[str, float] = {}
    try:
        prices.update(fetch_holdings_prices(credentials))
    except Exception as exc:
        print(f"[DhanHQ] holdings snapshot failed. {exc}")

    missing_security_ids = [
        security_id
        for source_symbol, security_id in security_ids_by_symbol.items()
        if str(security_id) not in prices and normalize_trading_symbol(source_symbol) not in prices
    ]
    if missing_security_ids:
        try:
            prices.update(fetch_ltp_batch(credentials, missing_security_ids))
        except Exception as exc:
            print(f"[DhanHQ] market data quote failed; using fallback provider for uncovered symbols. {exc}")

    elapsed = time.perf_counter() - start
    quotes: list[QuoteT] = []
    market_time = datetime.now()
    for source_symbol, security_id in security_ids_by_symbol.items():
        price = prices.get(str(security_id))
        if price is None:
            price = prices.get(normalize_trading_symbol(source_symbol))
        if price is None:
            fallback_symbols.append(source_symbol)
            continue
        quotes.append(
            quote_factory(
                source_symbol=source_symbol,
                yahoo_symbol=f"DHAN:{security_id}",
                price=float(price),
                currency="INR",
                market_time=market_time,
            )
        )

    if quotes:
        print(f"[DhanHQ] fetched {len(quotes)}/{len(symbol_list)} live quotes in {elapsed:.2f}s.")
    return quotes, fallback_symbols


def fetch_ltp_batch(credentials: DhanCredentials, security_ids: Iterable[str]) -> dict[str, float]:
    """Fetch LTP values for many Dhan security IDs in one HTTP call."""

    ids = sorted({int(str(security_id)) for security_id in security_ids if str(security_id).strip()})
    if not ids:
        return {}

    payload = json.dumps({"NSE_EQ": ids}).encode("utf-8")
    request = Request(
        f"{BASE_URL}/marketfeed/ltp",
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "access-token": credentials.access_token,
            "client-id": credentials.client_id,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:200]}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    if not isinstance(data, dict) or data.get("status") != "success":
        raise RuntimeError(f"unexpected response: {data!r}")

    rows = data.get("data", {}).get("NSE_EQ", {})
    prices: dict[str, float] = {}
    if isinstance(rows, dict):
        for security_id, row in rows.items():
            if isinstance(row, dict) and isinstance(row.get("last_price"), (int, float)):
                prices[str(security_id)] = float(row["last_price"])
    return prices


def fetch_holdings_prices(credentials: DhanCredentials) -> dict[str, float]:
    """Fetch last traded prices available in Dhan holdings.

    This uses Trading API portfolio data, not Data API marketfeed. It only
    returns instruments currently present in the account holdings.
    """

    request = Request(
        f"{BASE_URL}/holdings",
        headers={
            "Accept": "application/json",
            "access-token": credentials.access_token,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"holdings HTTP {exc.code}: {body[:200]}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    if not isinstance(data, list):
        return {}

    prices: dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        price = row.get("lastTradedPrice")
        security_id = str(row.get("securityId", "")).strip()
        symbol = normalize_trading_symbol(str(row.get("tradingSymbol", "")))
        if not isinstance(price, (int, float)):
            continue
        if security_id:
            prices[security_id] = float(price)
        if symbol:
            prices[symbol] = float(price)
    return prices


def load_credentials() -> DhanCredentials | None:
    """Load Dhan credentials from env or a local JSON file."""

    client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
    access_token = (os.getenv("DHAN_ACCESS_TOKEN") or os.getenv("DHAN_API_TOKEN") or "").strip()
    if client_id and access_token:
        return DhanCredentials(client_id=client_id, access_token=access_token)

    credentials_path = Path(os.getenv("DHAN_CREDENTIALS_PATH", "") or SAVED_CREDENTIALS_PATH)
    credentials = _load_credentials_file(credentials_path)
    if credentials is not None:
        return credentials

    if credentials_path != DEFAULT_CREDENTIALS_PATH:
        return _load_credentials_file(DEFAULT_CREDENTIALS_PATH)
    return None


def credentials_status() -> dict[str, str | bool]:
    """Return UI-safe Dhan credential status."""

    credentials = load_credentials()
    return {
        "configured": credentials is not None,
        "client_id": credentials.client_id if credentials else "",
        "masked_client_id": _mask_value(credentials.client_id) if credentials else "",
        "path": str(Path(os.getenv("DHAN_CREDENTIALS_PATH", "") or SAVED_CREDENTIALS_PATH)),
    }


def save_credentials(client_id: str, access_token: str) -> DhanCredentials:
    """Persist Dhan credentials for the next UI/live quote run."""

    token = str(access_token or "").strip()
    resolved_client_id = str(client_id or "").strip() or client_id_from_token(token)
    if not resolved_client_id:
        raise ValueError("Dhan client ID is required when it cannot be read from the token.")
    if not token:
        raise ValueError("Dhan access token is required.")

    credentials = DhanCredentials(client_id=resolved_client_id, access_token=token)
    SAVED_CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SAVED_CREDENTIALS_PATH.open("w", encoding="utf-8") as file:
        json.dump({"client_id": credentials.client_id, "api_token": credentials.access_token}, file, indent=2)

    load_credentials.cache_clear() if hasattr(load_credentials, "cache_clear") else None
    return credentials


def client_id_from_token(access_token: str) -> str:
    """Extract dhanClientId from a JWT payload when available."""

    parts = str(access_token or "").strip().split(".")
    if len(parts) < 2:
        return ""
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}").decode("utf-8")
        data = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return ""
    return str(data.get("dhanClientId", "")).strip()


def _load_credentials_file(credentials_path: Path) -> DhanCredentials | None:
    if not credentials_path.exists():
        return None

    try:
        with credentials_path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[DhanHQ] credentials could not be read from {credentials_path}: {exc}")
        return None

    client_id = str(data.get("client_id", "")).strip()
    access_token = str(data.get("api_token") or data.get("access_token") or "").strip()
    if not client_id or not access_token:
        return None
    return DhanCredentials(client_id=client_id, access_token=access_token)


def _mask_value(value: str) -> str:
    if len(value) <= 4:
        return value
    return f"{value[:3]}...{value[-2:]}"


@lru_cache(maxsize=1)
def load_security_id_map() -> dict[str, str]:
    """Load NSE_EQ trading symbol to Dhan security ID mapping."""

    master_path = Path(os.getenv("DHAN_SCRIP_MASTER_PATH", "") or DEFAULT_SCRIP_MASTER_PATH)
    if not master_path.exists():
        return {}

    mapping: dict[str, str] = {}
    with master_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row.get("SEM_EXM_EXCH_ID") != "NSE":
                continue
            if row.get("SEM_SEGMENT") != "E" or row.get("SEM_SERIES") != "EQ":
                continue
            symbol = str(row.get("SEM_TRADING_SYMBOL", "")).strip().upper()
            security_id = str(row.get("SEM_SMST_SECURITY_ID", "")).strip()
            if symbol and security_id:
                mapping[symbol] = security_id
    return mapping


def normalize_trading_symbol(source_symbol: str) -> str:
    """Convert app symbols like NSE:RELIANCE or RELIANCE.NS to Dhan symbols."""

    symbol = source_symbol.split(":", maxsplit=1)[-1].strip().upper()
    if symbol.endswith(".NS"):
        symbol = symbol[:-3]
    if symbol.endswith("-EQ"):
        symbol = symbol[:-3]
    return symbol
