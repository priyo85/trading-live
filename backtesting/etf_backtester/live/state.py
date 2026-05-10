"""JSON ledger storage for live ETF signals and trades."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backtesting.etf_backtester.utils.paths import PACKAGE_ROOT


LIVE_REPORT_DIR = PACKAGE_ROOT / "reports" / "live"
LIVE_STATE_PATH = LIVE_REPORT_DIR / "live_state.json"
LIVE_REPORT_PATH = LIVE_REPORT_DIR / "live_report.json"


def empty_live_state(initial_capital: float) -> dict[str, Any]:
    """Create an empty live trading ledger."""

    return {
        "cash": float(initial_capital),
        "holdings": {},
        "trades": [],
        "completed_trades": [],
        "capital_adjustments": [],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": None,
    }


def build_completed_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair booked BUY and SELL actions into completed round-trip trades."""

    open_buys: dict[str, list[dict[str, Any]]] = {}
    completed: list[dict[str, Any]] = []

    for trade in trades:
        symbol = str(trade.get("symbol", ""))
        side = str(trade.get("side", "")).upper()
        if not symbol:
            continue

        if side == "BUY":
            open_buys.setdefault(symbol, []).append(trade)
            continue

        if side != "SELL" or not open_buys.get(symbol):
            continue

        buy = open_buys[symbol].pop(0)
        buy_value = float(buy.get("value", 0))
        sell_value = float(trade.get("value", 0))
        profit = float(trade.get("profit", sell_value - buy_value))
        completed.append(
            {
                "symbol": symbol,
                "buy_date": buy.get("signal_date") or buy.get("date", ""),
                "sell_date": trade.get("signal_date") or trade.get("date", ""),
                "buy_time": buy.get("time", ""),
                "sell_time": trade.get("time", ""),
                "buy_price": float(buy.get("price", 0)),
                "sell_price": float(trade.get("price", 0)),
                "shares": int(float(trade.get("shares", buy.get("shares", 0)))),
                "buy_value": buy_value,
                "sell_value": sell_value,
                "profit": profit,
                "return_pct": (profit / buy_value) if buy_value > 0 else 0.0,
                "holding_days": _holding_days(buy.get("signal_date") or buy.get("date"), trade.get("signal_date") or trade.get("date")),
                "reason": trade.get("reason", ""),
            }
        )

    return completed


def _holding_days(buy_date: Any, sell_date: Any) -> int | None:
    if not buy_date or not sell_date:
        return None

    try:
        return (datetime.fromisoformat(str(sell_date)).date() - datetime.fromisoformat(str(buy_date)).date()).days
    except ValueError:
        return None


def load_live_state(path: Path = LIVE_STATE_PATH, initial_capital: float = 0.0) -> dict[str, Any]:
    """Load live state, creating an empty ledger if none exists."""

    if not path.exists():
        return empty_live_state(initial_capital)

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected live state object in {path}")

    data.setdefault("cash", float(initial_capital))
    data.setdefault("holdings", {})
    data.setdefault("trades", [])
    data.setdefault("completed_trades", [])
    data.setdefault("capital_adjustments", [])
    return data


def save_live_state(state: dict[str, Any], path: Path = LIVE_STATE_PATH) -> Path:
    """Save live state JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)
    return path


def save_live_report(report: dict[str, Any], path: Path = LIVE_REPORT_PATH) -> Path:
    """Save the latest live signal report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    return path
