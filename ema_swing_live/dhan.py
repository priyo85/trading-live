"""Dhan broker helpers for the EMA Swing live dashboard."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backtesting.market_data.dhanhq import client_id_from_token, load_security_id_map
from ema_swing_live.storage import INSTANCE_DIR, load_json, mask_value, save_json


BASE_URL = os.getenv("DHAN_BASE_URL", "https://api.dhan.co/v2").rstrip("/")
CREDENTIALS_PATH = Path(os.getenv("DHAN_CREDENTIALS_PATH", INSTANCE_DIR / "dhan_credentials.json"))


@dataclass(frozen=True)
class DhanCredentials:
    client_id: str
    access_token: str


def save_credentials(client_id: str, access_token: str) -> DhanCredentials:
    token = str(access_token or "").strip()
    resolved_client_id = str(client_id or "").strip() or client_id_from_token(token)
    if not resolved_client_id:
        raise ValueError("Dhan client ID is required.")
    if not token:
        raise ValueError("Dhan access token is required.")
    credentials = DhanCredentials(client_id=resolved_client_id, access_token=token)
    save_json(CREDENTIALS_PATH, {"client_id": credentials.client_id, "access_token": credentials.access_token})
    seed_environment(credentials)
    return credentials


def load_credentials() -> DhanCredentials | None:
    client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
    access_token = (os.getenv("DHAN_ACCESS_TOKEN") or os.getenv("DHAN_API_TOKEN") or "").strip()
    if client_id and access_token:
        return DhanCredentials(client_id=client_id, access_token=access_token)
    data = load_json(CREDENTIALS_PATH, {})
    client_id = str(data.get("client_id", "")).strip()
    access_token = str(data.get("access_token") or data.get("api_token") or "").strip()
    if not client_id or not access_token:
        return None
    return DhanCredentials(client_id=client_id, access_token=access_token)


def seed_environment(credentials: DhanCredentials | None = None) -> bool:
    credentials = credentials or load_credentials()
    if credentials is None:
        return False
    os.environ["DHAN_CLIENT_ID"] = credentials.client_id
    os.environ["DHAN_ACCESS_TOKEN"] = credentials.access_token
    return True


def credentials_status() -> dict[str, Any]:
    credentials = load_credentials()
    return {
        "configured": credentials is not None,
        "client_id": credentials.client_id if credentials else "",
        "access_token": credentials.access_token if credentials else "",
        "masked_client_id": mask_value(credentials.client_id) if credentials else "",
        "masked_access_token": mask_value(credentials.access_token) if credentials else "",
        "path": str(CREDENTIALS_PATH),
    }


def profile() -> dict[str, Any]:
    return _wrapped("profile", _request_json("GET", "/profile"))


def funds() -> dict[str, Any]:
    return _wrapped("funds", _request_json("GET", "/fundlimit"))


def holdings() -> dict[str, Any]:
    response = _request_json("GET", "/holdings")
    rows = _rows(response)
    return {"ok": True, "rows": [_normalize_holding(row) for row in rows], "response": response}


def positions() -> dict[str, Any]:
    response = _request_json("GET", "/positions")
    rows = _rows(response)
    return {"ok": True, "rows": [_normalize_holding(row) for row in rows], "response": response}


def order_book() -> dict[str, Any]:
    response = _request_json("GET", "/orders")
    rows = [_normalize_order(row) for row in _rows(response)]
    return {"ok": True, "rows": rows, "response": response}


def trade_book(from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    response = _request_json("GET", "/trades")
    rows = [_normalize_trade(row) for row in _rows(response)]
    start = _parse_date(from_date) if from_date else date.today() - timedelta(days=10)
    end = _parse_date(to_date) if to_date else date.today()
    filtered = [row for row in rows if _date_in_range(row.get("date"), start, end)]
    return {"ok": True, "rows": filtered, "response": response}


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> Any:
    credentials = load_credentials()
    if credentials is None:
        raise ValueError("Dhan credentials are not configured.")
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method.upper(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "access-token": credentials.access_token,
            "client-id": credentials.client_id,
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Dhan HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Dhan request failed: {exc.reason}") from exc
    return json.loads(text) if text else {}


def _wrapped(name: str, response: Any) -> dict[str, Any]:
    return {"ok": True, name: response, "response": response}


def _rows(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [row for row in response if isinstance(row, dict)]
    if isinstance(response, dict):
        for key in ("data", "holdings", "positions", "trades", "orders"):
            value = response.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _normalize_holding(row: dict[str, Any]) -> dict[str, Any]:
    symbol = _first_text(row, "tradingSymbol", "symbol", "drvSymbol", "customSymbol")
    quantity = _first_number(row, "totalQty", "availableQty", "netQty", "quantity")
    price = _first_number(row, "avgCostPrice", "averagePrice", "buyAvg", "price")
    value = quantity * price
    margin_amount = _first_number(row, "marginUsed", "marginAmount", "collateralQty")
    mtf_loan = _first_number(row, "mtfLoan", "fundedAmount", "loanAmount")
    return {
        "symbol": _strategy_symbol(symbol),
        "stock_code": symbol,
        "quantity": quantity,
        "price": price,
        "value": value,
        "product": _first_text(row, "productType", "product", "positionType"),
        "funding_mode": "mtf" if _looks_mtf(row) else "delivery",
        "margin_amount": margin_amount,
        "mtf_loan": mtf_loan if mtf_loan > 0 else max(value - margin_amount, 0.0) if _looks_mtf(row) and margin_amount > 0 else 0.0,
        "raw": row,
    }


def _normalize_trade(row: dict[str, Any]) -> dict[str, Any]:
    symbol = _first_text(row, "tradingSymbol", "symbol", "drvSymbol", "customSymbol")
    quantity = _first_number(row, "tradedQuantity", "quantity", "filledQty")
    price = _first_number(row, "tradedPrice", "averageTradedPrice", "price")
    value = quantity * price
    side = _first_text(row, "transactionType", "side").upper() or "BUY"
    return {
        "date": _first_text(row, "createTime", "exchangeTime", "tradeTime", "orderDateTime")[:10],
        "symbol": _strategy_symbol(symbol),
        "stock_code": symbol,
        "side": "SELL" if "SELL" in side else "BUY",
        "quantity": quantity,
        "price": price,
        "value": value,
        "product": _first_text(row, "productType", "product"),
        "funding_mode": "mtf" if _looks_mtf(row) else "delivery",
        "margin_amount": _first_number(row, "marginUsed", "marginAmount"),
        "mtf_loan": _first_number(row, "mtfLoan", "fundedAmount", "loanAmount"),
        "order_id": _first_text(row, "orderId", "order_id", "correlationId"),
        "raw": row,
    }


def _normalize_order(row: dict[str, Any]) -> dict[str, Any]:
    symbol = _first_text(row, "tradingSymbol", "symbol", "drvSymbol", "customSymbol")
    quantity = _first_number(row, "quantity", "orderQuantity", "filledQty", "tradedQuantity")
    price = _first_number(row, "price", "orderPrice", "limitPrice", "averageTradedPrice")
    side = _first_text(row, "transactionType", "side").upper() or "BUY"
    return {
        "date": _first_text(row, "createTime", "exchangeTime", "orderDateTime", "orderTime")[:19],
        "symbol": _strategy_symbol(symbol),
        "stock_code": symbol,
        "side": "SELL" if "SELL" in side else "BUY",
        "quantity": quantity,
        "price": price,
        "product": _first_text(row, "productType", "product"),
        "status": _first_text(row, "orderStatus", "status"),
        "order_id": _first_text(row, "orderId", "order_id", "correlationId"),
        "message": _first_text(row, "omsErrorDescription", "message", "remarks", "legName"),
        "raw": row,
    }


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return str(value).strip()
    return ""


def _first_number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value in {None, ""}:
            continue
        try:
            return float(str(value).replace(",", "").strip())
        except ValueError:
            continue
    return 0.0


def _looks_mtf(row: dict[str, Any]) -> bool:
    text = " ".join(str(value).lower() for value in row.values() if isinstance(value, (str, int, float)))
    return "mtf" in text or "margin" in text


def _strategy_symbol(symbol: str) -> str:
    code = str(symbol or "").strip().upper()
    if not code:
        return ""
    if code.startswith("NSE:"):
        return code
    if code.endswith(".NS"):
        code = code[:-3]
    return f"NSE:{code}"


def _parse_date(value: str | None) -> date:
    text = str(value or "").strip()[:10]
    return datetime.fromisoformat(text).date()


def _date_in_range(value: Any, start: date, end: date) -> bool:
    try:
        current = _parse_date(str(value))
    except ValueError:
        return True
    return start <= current <= end
