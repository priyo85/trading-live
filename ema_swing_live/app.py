"""Flask app for the live-only 9 EMA swing dashboard."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE
from backtesting.etf_backtester.live.signal_runner import LIVE_CONFIG_PATH, _apply_actions, clear_live_ledger, run_live_signals
from backtesting.etf_backtester.live.state import LIVE_REPORT_PATH, LIVE_STATE_PATH, load_live_state, save_live_state
from ema_swing_live import icici
from ema_swing_live.storage import INSTANCE_DIR, load_json, load_settings, save_json, save_settings


BROKER_ORDERS_PATH = INSTANCE_DIR / "broker_orders.json"


def create_app() -> Flask:
    app = Flask(__name__, instance_path=str(INSTANCE_DIR), instance_relative_config=False)
    app.secret_key = os.getenv("EMA_SWING_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY") or "change-this-before-ec2"

    @app.get("/login")
    def login():
        if _is_logged_in():
            return redirect(url_for("index"))
        return render_template("login.html", error="")

    @app.post("/login")
    def login_post():
        username = str(request.form.get("username", "")).strip()
        password = str(request.form.get("password", ""))
        if _valid_login(username, password):
            session["authenticated"] = True
            session["username"] = username
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid login."), 401

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @_login_required
    def index():
        return render_template(
            "index.html",
            etf_universe=list(ETF_UNIVERSE),
            today=datetime.now().date().isoformat(),
            username=session.get("username", "admin"),
        )

    @app.get("/api/status")
    @_login_required
    def api_status():
        return jsonify(
            {
                "settings": load_settings(),
                "icici": icici.credentials_status(),
                "live_config": _load_live_config(),
                "live_state": _load_live_state(),
                "broker_orders": _load_broker_orders(),
                "report": _load_latest_report(),
            }
        )

    @app.get("/api/live/config")
    @_login_required
    def api_live_config():
            return jsonify({"config": _load_live_config(), "settings": load_settings(), "symbols": list(ETF_UNIVERSE)})

    @app.post("/api/live/config")
    @_login_required
    def api_live_config_update():
        payload = request.get_json(silent=True) or {}
        try:
            config = _load_live_config()
            settings_updates: dict[str, Any] = {}

            if "initial_capital" in payload:
                initial_capital = float(payload.get("initial_capital"))
                if initial_capital <= 0:
                    raise ValueError("Initial capital must be greater than zero.")
                config["initial_capital"] = initial_capital

            if "max_positions" in payload:
                max_positions = int(payload.get("max_positions"))
                if max_positions <= 0:
                    raise ValueError("Max positions must be greater than zero.")
                config["max_positions"] = max_positions

            if "symbols" in payload:
                config["symbols"] = _normalize_symbols(payload.get("symbols"))

            if "data_provider" in payload:
                provider = str(payload.get("data_provider", "auto")).strip().lower()
                if provider not in {"auto", "dhan", "dhanhq", "icici", "breeze", "icici_breeze", "yahoo"}:
                    raise ValueError("Unknown data provider.")
                settings_updates["data_provider"] = "icici" if provider in {"breeze", "icici_breeze"} else provider

            save_json(LIVE_CONFIG_PATH, config)
            settings = save_settings(settings_updates) if settings_updates else load_settings()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live config update failed: {exc}"}), 500
        return jsonify({"config": config, "settings": settings})

    @app.get("/api/live/report")
    @_login_required
    def api_live_report():
        return jsonify({"report": _load_latest_report()})

    @app.post("/api/live/run")
    @_login_required
    def api_live_run():
        payload = request.get_json(silent=True) or {}
        try:
            _apply_provider_environment(str(payload.get("data_provider") or load_settings()["data_provider"]))
            selected_action_ids = payload.get("selected_action_ids")
            if selected_action_ids is not None and not isinstance(selected_action_ids, list):
                raise ValueError("selected_action_ids must be a list.")

            price_mode = str(payload.get("price_mode", "current")).strip().lower()
            run = run_live_signals(
                apply_actions=bool(payload.get("apply_actions", False)),
                selected_action_ids=selected_action_ids,
                use_current_price=price_mode == "current",
                use_daily_close=price_mode == "daily_close",
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live signal run failed: {exc}"}), 500
        return jsonify({"report": run.report, "report_path": str(run.report_path), "state_path": str(run.state_path)})

    @app.post("/api/live/clear")
    @_login_required
    def api_live_clear():
        try:
            state = clear_live_ledger()
        except Exception as exc:
            return jsonify({"error": f"Live ledger clear failed: {exc}"}), 500
        return jsonify({"state": state, "report": None})

    @app.get("/api/live/state")
    @_login_required
    def api_live_state():
        return jsonify({"state": _load_live_state()})

    @app.put("/api/live/state")
    @_login_required
    def api_live_state_update():
        payload = request.get_json(silent=True) or {}
        try:
            state = _normalize_live_state(payload)
            save_live_state(state, LIVE_STATE_PATH)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live state update failed: {exc}"}), 500
        return jsonify({"state": state})

    @app.post("/api/live/book-action")
    @_login_required
    def api_live_book_action():
        payload = request.get_json(silent=True) or {}
        try:
            state = _book_report_action(
                action_id=str(payload.get("action_id", "")),
                quantity=payload.get("quantity"),
                price=payload.get("price"),
                product=str(payload.get("product", "cash")),
                broker_order_id=str(payload.get("broker_order_id", "")),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live action booking failed: {exc}"}), 500
        return jsonify({"state": state})

    @app.get("/api/icici/status")
    @_login_required
    def api_icici_status():
        return jsonify({"credentials": icici.credentials_status()})

    @app.post("/api/icici/login-url")
    @_login_required
    def api_icici_login_url():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify({"url": icici.login_url(str(payload.get("api_key", "")))})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/icici/session")
    @_login_required
    def api_icici_session():
        payload = request.get_json(silent=True) or {}
        try:
            api_key = str(payload.get("api_key", "")).strip()
            api_secret = str(payload.get("api_secret", "")).strip()
            session_token = str(payload.get("session_token", "")).strip()
            test = icici.test_session(
                api_key=api_key,
                api_secret=api_secret,
                session_token=session_token,
                stock_code=str(payload.get("stock_code", "GOLDEX")),
            )
            icici.save_credentials(
                api_key=api_key,
                api_secret=api_secret,
                session_token=session_token,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI session test failed: {exc}"}), 500
        return jsonify({"credentials": icici.credentials_status(), "test": test})

    @app.post("/api/icici/save")
    @_login_required
    def api_icici_save():
        payload = request.get_json(silent=True) or {}
        try:
            icici.save_credentials(
                api_key=str(payload.get("api_key", "")),
                api_secret=str(payload.get("api_secret", "")),
                session_token=str(payload.get("session_token", "")),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI credential save failed: {exc}"}), 500
        return jsonify({"credentials": icici.credentials_status()})

    @app.post("/api/icici/test")
    @_login_required
    def api_icici_test():
        payload = request.get_json(silent=True) or {}
        try:
            test = icici.test_quote(str(payload.get("stock_code", "GOLDEX")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI quote test failed: {exc}"}), 500
        return jsonify({"test": test})

    @app.get("/api/icici/connection")
    @_login_required
    def api_icici_connection():
        stock_code = str(request.args.get("stock_code", "GOLDEX"))
        try:
            test = icici.test_quote(stock_code)
            connected = bool(test.get("ok"))
        except Exception as exc:
            return jsonify({"connected": False, "error": str(exc), "credentials": icici.credentials_status()})
        return jsonify({"connected": connected, "test": test, "credentials": icici.credentials_status()})

    @app.post("/api/icici/order/limit")
    @_login_required
    def api_icici_limit_order():
        payload = request.get_json(silent=True) or {}
        try:
            order = icici.place_limit_order(
                symbol=str(payload.get("symbol", "")),
                side=str(payload.get("side", "")),
                quantity=payload.get("quantity", ""),
                limit_price=payload.get("limit_price", ""),
                dry_run=bool(payload.get("dry_run", True)),
                product=str(payload.get("product", "cash")),
                validity=str(payload.get("validity", "day")),
                user_remark=str(payload.get("user_remark", "")),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI limit order failed: {exc}"}), 500
        return jsonify({"order": order})

    @app.post("/api/icici/action-order")
    @_login_required
    def api_icici_action_order():
        payload = request.get_json(silent=True) or {}
        try:
            report_action = _report_action(str(payload.get("action_id", "")))
            dry_run = bool(payload.get("dry_run", True))
            product = str(payload.get("product", report_action.get("funding_mode", "delivery")))
            if product == "delivery":
                product = "cash"
            quantity = payload.get("quantity", report_action.get("shares", ""))
            price = payload.get("price", report_action.get("price", ""))
            order = icici.place_limit_order(
                symbol=str(report_action.get("symbol", "")),
                side=str(report_action.get("side", "")),
                quantity=quantity,
                limit_price=price,
                product=product,
                dry_run=dry_run,
                validity=str(payload.get("validity", "day")),
                user_remark="emaswing",
            )
            entry = _record_broker_order(report_action, order, product=product, quantity=quantity, price=price)
            booked_state = None
            if order.get("ok") and not dry_run and bool(payload.get("book_on_success", True)):
                broker_order_id = _broker_order_id(order.get("response"))
                booked_state = _book_report_action(
                    action_id=str(report_action.get("id", "")),
                    quantity=quantity,
                    price=price,
                    product=product,
                    broker_order_id=broker_order_id,
                )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI action order failed: {exc}"}), 500
        return jsonify({"order": order, "broker_order": entry, "broker_orders": _load_broker_orders(), "state": booked_state})

    @app.get("/api/broker/orders")
    @_login_required
    def api_broker_orders():
        return jsonify({"broker_orders": _load_broker_orders()})

    @app.delete("/api/broker/orders/<order_log_id>")
    @_login_required
    def api_broker_order_delete(order_log_id: str):
        orders = [order for order in _load_broker_orders() if str(order.get("id", "")) != order_log_id]
        return jsonify({"broker_orders": _save_broker_orders(orders)})

    @app.get("/api/icici/order/book")
    @_login_required
    def api_icici_order_book():
        try:
            orders = icici.order_book(
                exchange_code=str(request.args.get("exchange_code", "NSE")),
                from_date=_optional_text(request.args.get("from_date")),
                to_date=_optional_text(request.args.get("to_date")),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI order book failed: {exc}"}), 500
        return jsonify({"orders": orders})

    @app.post("/api/icici/order/cancel")
    @_login_required
    def api_icici_order_cancel():
        payload = request.get_json(silent=True) or {}
        try:
            order_id = str(payload.get("order_id", ""))
            cancel = icici.cancel_order(exchange_code=str(payload.get("exchange_code", "NSE")), order_id=order_id)
            orders = _load_broker_orders()
            for order in orders:
                if str(order.get("broker_order_id", "")) == order_id:
                    order["cancel_response"] = cancel.get("response")
                    order["cancel_ok"] = bool(cancel.get("ok"))
                    order["message"] = _broker_order_message(cancel.get("response")) or order.get("message", "")
            _save_broker_orders(orders)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI order cancel failed: {exc}"}), 500
        return jsonify({"cancel": cancel, "broker_orders": _load_broker_orders()})

    @app.post("/api/icici/gtt/single")
    @_login_required
    def api_icici_gtt_single():
        payload = request.get_json(silent=True) or {}
        try:
            order = icici.place_gtt_single_leg_order(
                symbol=str(payload.get("symbol", "")),
                side=str(payload.get("side", "")),
                quantity=payload.get("quantity", ""),
                trigger_price=payload.get("trigger_price", ""),
                limit_price=payload.get("limit_price", ""),
                dry_run=bool(payload.get("dry_run", True)),
                expiry_date=_optional_text(payload.get("expiry_date")),
                trade_date=_optional_text(payload.get("trade_date")),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI GTT order failed: {exc}"}), 500
        return jsonify({"order": order})

    @app.get("/api/icici/gtt/book")
    @_login_required
    def api_icici_gtt_book():
        try:
            orders = icici.gtt_order_book(
                exchange_code=str(request.args.get("exchange_code", "NSE")),
                from_date=_optional_text(request.args.get("from_date")),
                to_date=_optional_text(request.args.get("to_date")),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI GTT order book failed: {exc}"}), 500
        return jsonify({"orders": orders})

    return app


def _login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _is_logged_in():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Login required."}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def _is_logged_in() -> bool:
    return bool(session.get("authenticated"))


def _valid_login(username: str, password: str) -> bool:
    expected_username = os.getenv("EMA_SWING_APP_USERNAME", "admin")
    expected_password = os.getenv("EMA_SWING_APP_PASSWORD", "admin")
    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(password, expected_password)


def _load_live_config() -> dict[str, Any]:
    with Path(LIVE_CONFIG_PATH).open(encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Expected live config object in {LIVE_CONFIG_PATH}")
    return data


def _load_latest_report() -> dict[str, Any] | None:
    if not LIVE_REPORT_PATH.exists():
        return None
    with LIVE_REPORT_PATH.open(encoding="utf-8-sig") as file:
        report = json.load(file)
    if not isinstance(report, dict):
        raise ValueError(f"Expected live report object in {LIVE_REPORT_PATH}")
    return report


def _load_live_state() -> dict[str, Any]:
    config = _load_live_config()
    return load_live_state(LIVE_STATE_PATH, initial_capital=float(config.get("initial_capital", 0)))


def _load_broker_orders() -> list[dict[str, Any]]:
    data = load_json(BROKER_ORDERS_PATH, {"orders": []})
    orders = data.get("orders", [])
    return orders if isinstance(orders, list) else []


def _save_broker_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    save_json(BROKER_ORDERS_PATH, {"orders": orders[-200:]})
    return orders[-200:]


def _record_broker_order(action: dict[str, Any], order: dict[str, Any], product: str, quantity: Any, price: Any) -> dict[str, Any]:
    response = order.get("response") if isinstance(order, dict) else {}
    entry = {
        "id": uuid4().hex,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action_id": action.get("id", ""),
        "symbol": action.get("symbol", ""),
        "side": action.get("side", ""),
        "product": product,
        "quantity": _positive_number(quantity, "Quantity"),
        "price": _positive_number(price, "Price"),
        "dry_run": bool(order.get("dry_run", True)),
        "ok": bool(order.get("ok")),
        "broker_order_id": _broker_order_id(response),
        "message": _broker_order_message(response),
        "payload": order.get("payload"),
        "response": response,
    }
    orders = _load_broker_orders()
    orders.append(entry)
    _save_broker_orders(orders)
    return entry


def _broker_order_id(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    success = response.get("Success")
    if isinstance(success, dict):
        return str(success.get("order_id", "")).strip()
    return ""


def _broker_order_message(response: Any) -> str:
    if not isinstance(response, dict):
        return str(response or "")
    if response.get("Error"):
        return str(response.get("Error"))
    success = response.get("Success")
    if isinstance(success, dict):
        return str(success.get("message") or success.get("order_id") or "")
    return str(response.get("Status", ""))


def _report_action(action_id: str) -> dict[str, Any]:
    report = _load_latest_report()
    if not report:
        raise ValueError("Run signals before placing action orders.")
    for action in report.get("actions", []):
        if str(action.get("id", "")) == action_id:
            return dict(action)
    raise ValueError("Action was not found in the latest signal report.")


def _book_report_action(action_id: str, quantity: Any, price: Any, product: str, broker_order_id: str = "") -> dict[str, Any]:
    action = _report_action(action_id)
    config = _load_live_config()
    state = _load_live_state()
    booked = _action_with_order_values(action, state, quantity=quantity, price=price, product=product, broker_order_id=broker_order_id)
    _apply_actions(state, [booked], config)
    save_live_state(state, LIVE_STATE_PATH)
    return state


def _action_with_order_values(action: dict[str, Any], state: dict[str, Any], quantity: Any, price: Any, product: str, broker_order_id: str) -> dict[str, Any]:
    booked = dict(action)
    shares = int(_positive_number(quantity if quantity is not None else action.get("shares"), "Quantity"))
    order_price = _positive_number(price if price is not None else action.get("price"), "Price")
    value = shares * order_price
    funding_mode = "mtf" if str(product).strip().lower() == "mtf" else "delivery"
    booked.update(
        {
            "shares": shares,
            "price": order_price,
            "value": value,
            "broker_order_id": broker_order_id,
            "funding_mode": funding_mode,
            "mtf_loan": value if funding_mode == "mtf" and booked.get("side") == "BUY" else 0.0,
            "cash_required": 0.0 if funding_mode == "mtf" and booked.get("side") == "BUY" else value,
        }
    )
    if booked.get("side") == "SELL":
        holding = state.get("holdings", {}).get(booked.get("symbol"), {})
        mtf_loan = float(holding.get("mtf_loan", 0) or 0)
        cost_basis = float(holding.get("cost_basis", shares * float(holding.get("entry_price", order_price))) or 0)
        booked["mtf_loan_repayment"] = mtf_loan
        booked["cash_delta"] = value - mtf_loan
        booked["profit"] = value - cost_basis
    return booked


def _normalize_live_state(payload: dict[str, Any]) -> dict[str, Any]:
    current = _load_live_state()
    state = dict(current)
    state["cash"] = float(payload.get("cash", current.get("cash", 0)) or 0)
    state["holdings"] = _normalize_holdings(payload.get("holdings", current.get("holdings", {})))
    state["trades"] = _normalize_trades(payload.get("trades", current.get("trades", [])))
    state["completed_trades"] = []
    state.setdefault("capital_adjustments", current.get("capital_adjustments", []))
    state.setdefault("created_at", current.get("created_at", datetime.now().isoformat(timespec="seconds")))
    return state


def _normalize_holdings(value: Any) -> dict[str, Any]:
    rows = value.values() if isinstance(value, dict) else value
    if not isinstance(rows, list) and not hasattr(rows, "__iter__"):
        raise ValueError("Holdings must be a list or object.")
    holdings: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        shares = int(_positive_number(row.get("shares"), f"{symbol} shares"))
        entry_price = _positive_number(row.get("entry_price"), f"{symbol} entry price")
        funding_mode = str(row.get("funding_mode", "delivery")).strip().lower()
        if funding_mode not in {"delivery", "mtf"}:
            funding_mode = "delivery"
        holdings[symbol] = {
            "symbol": symbol,
            "shares": shares,
            "entry_price": entry_price,
            "entry_date": str(row.get("entry_date", "")).strip() or datetime.now().date().isoformat(),
            "cost_basis": float(row.get("cost_basis", shares * entry_price) or shares * entry_price),
            "funding_mode": funding_mode,
            "mtf_loan": float(row.get("mtf_loan", 0) or 0),
        }
    return holdings


def _normalize_trades(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Booked ledger must be a list.")
    trades: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).strip().upper()
        side = str(row.get("side", "")).strip().upper()
        if not symbol or side not in {"BUY", "SELL"}:
            continue
        shares = int(_positive_number(row.get("shares"), f"{symbol} ledger shares"))
        price = _positive_number(row.get("price"), f"{symbol} ledger price")
        trade = dict(row)
        trade.update(
            {
                "id": str(row.get("id") or f"MANUAL_{uuid4().hex[:10]}"),
                "symbol": symbol,
                "side": side,
                "shares": shares,
                "price": price,
                "value": float(row.get("value", shares * price) or shares * price),
                "date": str(row.get("date", "")).strip() or datetime.now().date().isoformat(),
                "signal_date": str(row.get("signal_date", row.get("date", ""))).strip() or datetime.now().date().isoformat(),
                "reason": str(row.get("reason", "manual")),
                "funding_mode": str(row.get("funding_mode", "delivery")).strip().lower(),
                "broker_order_id": str(row.get("broker_order_id", "")).strip(),
            }
        )
        trades.append(trade)
    return trades


def _positive_number(value: Any, label: str) -> float:
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a positive number.") from None
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive number.")
    return parsed


def _normalize_symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_symbols = [part.strip().upper() for part in value.replace("\n", ",").split(",")]
    elif isinstance(value, list):
        raw_symbols = [str(part).strip().upper() for part in value]
    else:
        raise ValueError("Symbols must be a list or comma-separated text.")

    symbols = [symbol for symbol in raw_symbols if symbol]
    invalid = [symbol for symbol in symbols if symbol not in ETF_UNIVERSE]
    if invalid:
        raise ValueError(f"Unknown ETF symbols: {', '.join(invalid)}")
    return symbols


def _apply_provider_environment(provider: str) -> None:
    normalized = provider.strip().lower()
    if normalized in {"breeze", "icici_breeze"}:
        normalized = "icici"
    if normalized == "yahoo":
        normalized = "none"
    if normalized == "icici":
        icici.seed_environment()
    if normalized in {"auto", "dhan", "dhanhq", "icici", "none"}:
        os.environ["ETF_DATA_PROVIDER"] = normalized


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def main() -> None:
    host = os.getenv("EMA_SWING_HOST", "0.0.0.0")
    port = int(os.getenv("EMA_SWING_PORT", "8080"))
    debug = os.getenv("EMA_SWING_DEBUG", "").lower() in {"1", "true", "yes"}
    create_app().run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
