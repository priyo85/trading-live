"""Diagnostic probe for Dhan Live Market Feed WebSocket."""

from __future__ import annotations

import asyncio
import argparse
import json
import struct
import time

import websockets

from backtesting.market_data.dhanhq import load_credentials, load_security_id_map


async def _probe(symbol: str = "RELIANCE", request_code: int = 15, timeout_seconds: float = 8.0) -> None:
    credentials = load_credentials()
    if credentials is None:
        raise RuntimeError("Dhan credentials are not saved.")

    security_id = load_security_id_map()[symbol.upper()]
    uri = (
        "wss://api-feed.dhan.co"
        f"?version=2&token={credentials.access_token}"
        f"&clientId={credentials.client_id}&authType=2"
    )

    start = time.perf_counter()
    async with websockets.connect(uri, ping_interval=None, open_timeout=10) as websocket:
        print("connected_seconds", round(time.perf_counter() - start, 3))
        await websocket.send(
            json.dumps(
                {
                    "RequestCode": request_code,
                    "InstrumentCount": 1,
                    "InstrumentList": [
                        {
                            "ExchangeSegment": "NSE_EQ",
                            "SecurityId": str(security_id),
                        }
                    ],
                }
            )
        )

        deadline = time.perf_counter() + timeout_seconds
        while time.perf_counter() < deadline:
            try:
                message = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=max(0.1, deadline - time.perf_counter()),
                )
            except websockets.ConnectionClosed as exc:
                print("closed", exc.code, exc.reason or "")
                return
            if isinstance(message, str):
                print("text", message[:300])
                continue

            code = message[0] if len(message) >= 1 else None
            length = struct.unpack_from("<H", message, 1)[0] if len(message) >= 3 else None
            exchange = message[3] if len(message) >= 4 else None
            security = struct.unpack_from("<I", message, 4)[0] if len(message) >= 8 else None
            print("binary", len(message), "code", code, "length", length, "exchange", exchange, "security", security)
            if code in (2, 4, 8) and len(message) >= 12:
                ltp = struct.unpack_from("<f", message, 8)[0]
                print("ltp", round(ltp, 2), "seconds", round(time.perf_counter() - start, 3))
                return

    print("no_ltp")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument("--request-code", type=int, default=15)
    args = parser.parse_args()
    asyncio.run(_probe(symbol=args.symbol, request_code=args.request_code))


if __name__ == "__main__":
    main()
