"""ICICI Breeze session and data-test helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from backtesting.etf_backtester.data.icici_breeze import BreezeInstrument, IciciBreezeProvider
from ema_swing_live.storage import INSTANCE_DIR, load_json, mask_value, save_json


CREDENTIALS_PATH = Path(os.getenv("ICICI_BREEZE_CREDENTIALS_PATH", INSTANCE_DIR / "icici_breeze_credentials.json"))
LOGIN_BASE_URL = "https://api.icicidirect.com/apiuser/login?api_key="
GTT_DEFAULT_DAYS = int(os.getenv("ICICI_BREEZE_GTT_DEFAULT_DAYS", "365"))
GTT_SUPPORTED_EXCHANGES = {"NFO"}


@dataclass(frozen=True)
class IciciCredentials:
    api_key: str
    api_secret: str
    session_token: str


def login_url(api_key: str) -> str:
    cleaned = str(api_key or "").strip()
    if not cleaned:
        raise ValueError("ICICI Breeze API key is required.")
    return f"{LOGIN_BASE_URL}{quote(cleaned, safe='')}"


def save_credentials(api_key: str, api_secret: str, session_token: str) -> IciciCredentials:
    existing = load_credentials()
    credentials = IciciCredentials(
        api_key=str(api_key or "").strip() or (existing.api_key if existing else ""),
        api_secret=str(api_secret or "").strip() or (existing.api_secret if existing else ""),
        session_token=str(session_token or "").strip() or (existing.session_token if existing else ""),
    )
    if not credentials.api_key:
        raise ValueError("ICICI Breeze API key is required.")
    if not credentials.api_secret:
        raise ValueError("ICICI Breeze secret key is required.")
    if not credentials.session_token:
        raise ValueError("ICICI Breeze session token is required.")

    save_json(
        CREDENTIALS_PATH,
        {
            "api_key": credentials.api_key,
            "api_secret": credentials.api_secret,
            "session_token": credentials.session_token,
        },
    )
    seed_environment(credentials)
    return credentials


def load_credentials() -> IciciCredentials | None:
    api_key = os.getenv("ICICI_BREEZE_API_KEY") or os.getenv("BREEZE_API_KEY")
    api_secret = os.getenv("ICICI_BREEZE_API_SECRET") or os.getenv("BREEZE_API_SECRET")
    session_token = os.getenv("ICICI_BREEZE_SESSION_TOKEN") or os.getenv("BREEZE_SESSION_TOKEN")
    if api_key and api_secret and session_token:
        return IciciCredentials(api_key=api_key, api_secret=api_secret, session_token=session_token)

    data = load_json(CREDENTIALS_PATH, {})
    api_key = str(data.get("api_key", "")).strip()
    api_secret = str(data.get("api_secret", "")).strip()
    session_token = str(data.get("session_token", "")).strip()
    if not api_key or not api_secret or not session_token:
        return None
    return IciciCredentials(api_key=api_key, api_secret=api_secret, session_token=session_token)


def seed_environment(credentials: IciciCredentials | None = None) -> bool:
    credentials = credentials or load_credentials()
    if credentials is None:
        return False
    os.environ["ICICI_BREEZE_API_KEY"] = credentials.api_key
    os.environ["ICICI_BREEZE_API_SECRET"] = credentials.api_secret
    os.environ["ICICI_BREEZE_SESSION_TOKEN"] = credentials.session_token
    return True


def credentials_status() -> dict[str, Any]:
    credentials = load_credentials()
    return {
        "configured": credentials is not None,
        "api_key": credentials.api_key if credentials else "",
        "api_secret": credentials.api_secret if credentials else "",
        "session_token": credentials.session_token if credentials else "",
        "masked_api_key": mask_value(credentials.api_key) if credentials else "",
        "masked_api_secret": mask_value(credentials.api_secret) if credentials else "",
        "masked_session_token": mask_value(credentials.session_token) if credentials else "",
        "path": str(CREDENTIALS_PATH),
    }


def test_quote(stock_code: str = "GOLDEX", credentials: IciciCredentials | None = None) -> dict[str, Any]:
    client = _client(credentials)
    code = _stock_code(stock_code)
    response = client.get_quotes(
        stock_code=code,
        exchange_code="NSE",
        expiry_date="",
        product_type="cash",
        right="",
        strike_price="",
    )
    success = response.get("Success") if isinstance(response, dict) else None
    row = success[0] if isinstance(success, list) and success else {}
    return {
        "ok": bool(row),
        "stock_code": code,
        "ltp": row.get("ltp") or row.get("last") or row.get("close") if isinstance(row, dict) else None,
        "time": row.get("ltt") if isinstance(row, dict) else None,
        "raw": _safe_response(response),
    }


def test_session(
    api_key: str | None = None,
    api_secret: str | None = None,
    session_token: str | None = None,
    stock_code: str = "GOLDEX",
) -> dict[str, Any]:
    credentials = None
    if api_key or api_secret or session_token:
        existing = load_credentials()
        credentials = IciciCredentials(
            api_key=str(api_key or "").strip() or (existing.api_key if existing else ""),
            api_secret=str(api_secret or "").strip() or (existing.api_secret if existing else ""),
            session_token=str(session_token or "").strip() or (existing.session_token if existing else ""),
        )
    return test_quote(stock_code=stock_code, credentials=credentials)


def build_limit_order_payload(
    symbol: str,
    side: str,
    quantity: int | str,
    limit_price: float | str,
    *,
    validity: str = "day",
    product: str | None = None,
    exchange_code: str | None = None,
    disclosed_quantity: int | str = "0",
    expiry_date: str | None = None,
    right: str | None = None,
    strike_price: str | None = None,
    user_remark: str = "",
) -> dict[str, Any]:
    """Build a Breeze regular limit order payload without touching the network."""

    instrument = _instrument(symbol)
    return {
        "stock_code": instrument.stock_code,
        "exchange_code": (exchange_code or instrument.exchange_code or "NSE").upper(),
        "product": (product or instrument.product_type or "cash").lower(),
        "action": _side(side).lower(),
        "order_type": "limit",
        "stoploss": "",
        "quantity": str(_positive_int(quantity, "Quantity")),
        "price": _price_text(limit_price, "Limit price"),
        "validity": _validity(validity),
        "validity_date": "",
        "disclosed_quantity": str(_non_negative_int(disclosed_quantity, "Disclosed quantity")),
        "expiry_date": expiry_date if expiry_date is not None else instrument.expiry_date,
        "right": (right if right is not None else instrument.right) or "others",
        "strike_price": (strike_price if strike_price is not None else instrument.strike_price) or "0",
        "user_remark": _user_remark(user_remark),
    }


def place_limit_order(
    symbol: str,
    side: str,
    quantity: int | str,
    limit_price: float | str,
    *,
    dry_run: bool = True,
    credentials: IciciCredentials | None = None,
    **payload_options: Any,
) -> dict[str, Any]:
    payload = build_limit_order_payload(
        symbol=symbol,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        **payload_options,
    )
    if dry_run:
        return {"ok": True, "dry_run": True, "payload": payload, "response": None}

    response = _client(credentials).place_order(**payload)
    return {"ok": _response_ok(response), "dry_run": False, "payload": payload, "response": _safe_response(response)}


def order_book(exchange_code: str = "NSE", from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    today = date.today()
    response = _client().get_order_list(
        exchange_code=str(exchange_code or "NSE").upper(),
        from_date=from_date or _breeze_datetime(today - timedelta(days=10)),
        to_date=to_date or _breeze_datetime(today),
    )
    return {"ok": _response_ok(response), "response": _safe_response(response)}


def build_gtt_single_leg_payload(
    symbol: str,
    side: str,
    quantity: int | str,
    trigger_price: float | str,
    limit_price: float | str,
    *,
    expiry_date: str | None = None,
    product: str | None = None,
    exchange_code: str | None = None,
    right: str | None = None,
    strike_price: str | None = None,
    index_or_stock: str = "stock",
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Build a Breeze single-leg GTT payload without touching the network."""

    instrument = _instrument(symbol)
    return {
        "exchange_code": (exchange_code or instrument.exchange_code or "NSE").upper(),
        "stock_code": instrument.stock_code,
        "product": (product or instrument.product_type or "cash").lower(),
        "quantity": str(_positive_int(quantity, "Quantity")),
        "expiry_date": expiry_date or instrument.expiry_date or _breeze_datetime(date.today() + timedelta(days=GTT_DEFAULT_DAYS)),
        "right": (right if right is not None else instrument.right) or "others",
        "strike_price": (strike_price if strike_price is not None else instrument.strike_price) or "0",
        "gtt_type": "single",
        "index_or_stock": index_or_stock or "stock",
        "trade_date": trade_date or _breeze_datetime(date.today()),
        "order_details": [
            {
                "action": _side(side).lower(),
                "order_type": "limit",
                "limit_price": _price_text(limit_price, "Limit price"),
                "trigger_price": _price_text(trigger_price, "Trigger price"),
            }
        ],
    }


def place_gtt_single_leg_order(
    symbol: str,
    side: str,
    quantity: int | str,
    trigger_price: float | str,
    limit_price: float | str,
    *,
    dry_run: bool = True,
    credentials: IciciCredentials | None = None,
    **payload_options: Any,
) -> dict[str, Any]:
    payload = build_gtt_single_leg_payload(
        symbol=symbol,
        side=side,
        quantity=quantity,
        trigger_price=trigger_price,
        limit_price=limit_price,
        **payload_options,
    )
    if dry_run:
        return {"ok": True, "dry_run": True, "payload": payload, "response": None}
    _validate_real_gtt_payload(payload)

    response = _client(credentials).gtt_single_leg_place_order(**payload)
    return {"ok": _response_ok(response), "dry_run": False, "payload": payload, "response": _safe_response(response)}


def gtt_order_book(exchange_code: str = "NSE", from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    today = date.today()
    response = _client().gtt_order_book(
        exchange_code=str(exchange_code or "NSE").upper(),
        from_date=from_date or _breeze_datetime(today - timedelta(days=GTT_DEFAULT_DAYS)),
        to_date=to_date or _breeze_datetime(today + timedelta(days=GTT_DEFAULT_DAYS)),
    )
    return {"ok": _response_ok(response), "response": _safe_response(response)}


def _client(credentials: IciciCredentials | None = None):
    credentials = credentials or load_credentials()
    if credentials is None:
        raise ValueError("ICICI Breeze credentials are not configured.")
    if not credentials.api_key:
        raise ValueError("ICICI Breeze API key is required.")
    if not credentials.api_secret:
        raise ValueError("ICICI Breeze secret key is required.")
    if not credentials.session_token:
        raise ValueError("ICICI Breeze session token is required.")

    try:
        from breeze_connect import BreezeConnect
    except ImportError as exc:
        raise RuntimeError("breeze-connect is not installed.") from exc
    except Exception as exc:
        raise RuntimeError(f"breeze-connect could not initialize: {exc}") from exc

    client = BreezeConnect(api_key=credentials.api_key)
    client.generate_session(api_secret=credentials.api_secret, session_token=credentials.session_token)
    return client


def _instrument(value: str) -> BreezeInstrument:
    text = str(value or "").strip().upper()
    if not text:
        raise ValueError("Symbol or ICICI stock code is required.")

    provider = IciciBreezeProvider(client=None)
    instrument = provider.instrument(text)
    if instrument is not None:
        return instrument

    if text.endswith(".NS"):
        text = text[:-3]
    if ":" in text:
        raise ValueError(f"ICICI Breeze has no stock code configured for {value}.")
    return BreezeInstrument(stock_code=text)


def _stock_code(value: str) -> str:
    code = str(value or "GOLDEX").strip().upper()
    if code.startswith("NSE:"):
        code = code.split(":", maxsplit=1)[1]
    if code.endswith(".NS"):
        code = code[:-3]
    return code or "GOLDEX"


def _side(value: str) -> str:
    side = str(value or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("Side must be BUY or SELL.")
    return side


def _positive_int(value: int | str, label: str) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a positive whole number.") from None
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive whole number.")
    return parsed


def _non_negative_int(value: int | str, label: str) -> int:
    try:
        parsed = int(float(str(value or "0").strip()))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be zero or a positive whole number.") from None
    if parsed < 0:
        raise ValueError(f"{label} must be zero or a positive whole number.")
    return parsed


def _price_text(value: float | str, label: str) -> str:
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a positive number.") from None
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive number.")
    return f"{parsed:.2f}"


def _validity(value: str) -> str:
    normalized = str(value or "day").strip().lower()
    if normalized not in {"day", "ioc"}:
        raise ValueError("Validity must be day or ioc.")
    return normalized


def _user_remark(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-"})
    return cleaned[:20]


def _breeze_datetime(value: date) -> str:
    return f"{value.isoformat()}T06:00:00.000Z"


def _response_ok(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    status = str(response.get("Status", "")).strip().lower()
    return not error and status not in {"error", "failed", "failure"}


def _validate_real_gtt_payload(payload: dict[str, Any]) -> None:
    exchange_code = str(payload.get("exchange_code", "")).strip().upper()
    if exchange_code not in GTT_SUPPORTED_EXCHANGES:
        raise ValueError(
            "ICICI Breeze rejected NSE cash GTT orders with: Exchange-code should be 'nfo'. "
            "Use dry run only for NSE ETFs/cash, or place the cash GTT from ICICI Direct manually. "
            "This API path is enabled only for NFO GTT orders."
        )


def _safe_response(response: Any) -> Any:
    if not isinstance(response, dict):
        return str(response)
    cleaned = dict(response)
    if "Success" in cleaned and isinstance(cleaned["Success"], list):
        cleaned["Success"] = cleaned["Success"][:2]
    return cleaned
