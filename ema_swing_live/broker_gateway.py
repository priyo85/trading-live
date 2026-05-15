"""Optional EC2 broker gateway client for static-IP broker calls."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


TOKEN_HEADER = "X-EMA-Swing-Broker-Gateway-Token"


def status() -> dict[str, Any]:
    url = gateway_url()
    token = gateway_token()
    return {
        "configured": bool(url and token),
        "url": url,
        "token_configured": bool(token),
        "icici_enabled": icici_enabled(),
        "dhan_orders_enabled": dhan_orders_enabled(),
    }


def gateway_url() -> str:
    return os.getenv("EMA_SWING_BROKER_GATEWAY_URL", "").strip()


def gateway_token() -> str:
    return (
        os.getenv("EMA_SWING_BROKER_GATEWAY_TOKEN", "").strip()
        or os.getenv("EMA_SWING_SYNC_TOKEN", "").strip()
    )


def icici_enabled() -> bool:
    value = os.getenv("EMA_SWING_BROKER_GATEWAY_ICICI", "1").strip().lower()
    return value not in {"0", "false", "no", "off"} and bool(gateway_url() and gateway_token())


def dhan_orders_enabled() -> bool:
    value = os.getenv("EMA_SWING_BROKER_GATEWAY_DHAN_ORDERS", "0").strip().lower()
    return value in {"1", "true", "yes", "on"} and bool(gateway_url() and gateway_token())


def call(operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = gateway_url()
    token = gateway_token()
    if not url or not token:
        raise RuntimeError("Broker gateway is not configured.")

    endpoint = urljoin(url.rstrip("/") + "/", "api/broker-gateway")
    body = json.dumps({"operation": operation, "params": params or {}}).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            TOKEN_HEADER: token,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Broker gateway HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Broker gateway unavailable: {exc.reason}") from exc

    payload = json.loads(text) if text else {}
    if not isinstance(payload, dict):
        raise RuntimeError("Broker gateway returned a non-object response.")
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload
