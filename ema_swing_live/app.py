"""Flask app for the live-only 9 EMA swing dashboard."""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE
from backtesting.etf_backtester.data.icici_breeze import load_icici_symbol_aliases
from backtesting.etf_backtester.live.signal_runner import LIVE_CONFIG_PATH, _apply_actions, clear_live_ledger, run_live_signals
from backtesting.etf_backtester.live.state import LIVE_REPORT_PATH, LIVE_STATE_PATH, load_live_state, reconcile_strategy_cash, save_live_report, save_live_state
from ema_swing_live import broker_gateway, database, dhan, icici
from ema_swing_live.storage import INSTANCE_DIR, load_json, load_settings, save_json, save_settings


BROKER_ORDERS_PATH = INSTANCE_DIR / "broker_orders.json"
LOG_PATH = INSTANCE_DIR / "ema_swing_live.log"
LOG_SETTINGS_PATH = INSTANCE_DIR / "log_settings.json"
LOGGER = logging.getLogger(__name__)


def create_app() -> Flask:
    _configure_logging()
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
            broker_codes=_broker_codes(),
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
                "dhan": dhan.credentials_status(),
                "log_settings": _load_log_settings(),
                "storage": {"database_path": str(database.DB_PATH), "mode": "sqlite_mirror"},
                "sync": _sync_status(),
                "broker_gateway": broker_gateway.status(),
                "live_config": _load_live_config(),
                "live_state": _load_live_state(),
                "broker_orders": _load_broker_orders(),
                "report": _load_latest_report(),
            }
        )

    @app.get("/api/sync/export")
    def api_sync_export():
        if not _is_logged_in() and not _valid_sync_token():
            return jsonify({"error": "Sync token required."}), 403
        return jsonify(_sync_export_payload())

    @app.post("/api/sync/pull")
    @_login_required
    def api_sync_pull():
        payload = request.get_json(silent=True) or {}
        remote_url = str(payload.get("remote_url") or os.getenv("EMA_SWING_REMOTE_URL", "")).strip()
        token = str(payload.get("token") or os.getenv("EMA_SWING_SYNC_TOKEN", "")).strip()
        if not remote_url:
            return jsonify({"error": "Remote EC2 URL is required."}), 400
        try:
            remote_payload = _fetch_remote_sync(remote_url, token)
            applied = _apply_sync_payload(remote_payload)
        except Exception as exc:
            return jsonify({"error": f"Sync pull failed: {exc}"}), 500
        return jsonify({"applied": applied, "status": _sync_status(), **_sync_export_payload()})

    @app.post("/api/broker-gateway")
    def api_broker_gateway():
        if not _valid_broker_gateway_token():
            return jsonify({"error": "Broker gateway token required."}), 403
        payload = request.get_json(silent=True) or {}
        try:
            result = _execute_broker_gateway_operation(
                str(payload.get("operation", "")),
                payload.get("params") if isinstance(payload.get("params"), dict) else {},
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Broker gateway operation failed: {exc}"}), 500
        return jsonify(result)

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
            old_initial_capital = float(config.get("initial_capital", 0) or 0)
            capital_delta = 0.0
            settings_updates: dict[str, Any] = {}

            if "initial_capital" in payload:
                initial_capital = float(payload.get("initial_capital"))
                if initial_capital <= 0:
                    raise ValueError("Initial capital must be greater than zero.")
                config["initial_capital"] = initial_capital
                capital_delta = initial_capital - old_initial_capital

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
            live_state = _apply_capital_delta(capital_delta, old_initial_capital, config)
            settings = save_settings(settings_updates) if settings_updates else load_settings()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live config update failed: {exc}"}), 500
        return jsonify({"config": config, "settings": settings, "live_state": live_state})

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
        return jsonify(
            {
                "report": run.report,
                "live_state": _load_live_state(),
                "report_path": str(run.report_path),
                "state_path": str(run.state_path),
            }
        )

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
        if broker_gateway.icici_enabled():
            try:
                payload = broker_gateway.call("icici.credentials_status")
                payload["gateway"] = broker_gateway.status()
                return jsonify(payload)
            except Exception as exc:
                return jsonify({"credentials": {"configured": False}, "gateway": broker_gateway.status(), "error": str(exc)})
        return jsonify({"credentials": icici.credentials_status()})

    @app.post("/api/icici/login-url")
    @_login_required
    def api_icici_login_url():
        payload = request.get_json(silent=True) or {}
        try:
            if broker_gateway.icici_enabled():
                return jsonify(
                    broker_gateway.call(
                        "icici.login_url",
                        {"api_key": str(payload.get("api_key", ""))},
                    )
                )
            return jsonify({"url": icici.login_url(str(payload.get("api_key", "")))})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI login URL failed: {exc}"}), 500

    @app.post("/api/icici/session")
    @_login_required
    def api_icici_session():
        payload = request.get_json(silent=True) or {}
        try:
            api_key = str(payload.get("api_key", "")).strip()
            api_secret = str(payload.get("api_secret", "")).strip()
            session_token = str(payload.get("session_token", "")).strip()
            if broker_gateway.icici_enabled():
                return jsonify(
                    broker_gateway.call(
                        "icici.session",
                        {
                            "api_key": api_key,
                            "api_secret": api_secret,
                            "session_token": session_token,
                            "stock_code": str(payload.get("stock_code", "GOLDEX")),
                        },
                    )
                )
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

    @app.post("/api/dhan/session")
    @_login_required
    def api_dhan_session():
        payload = request.get_json(silent=True) or {}
        try:
            dhan.save_credentials(
                client_id=str(payload.get("client_id", "")),
                access_token=str(payload.get("access_token", "")),
            )
            profile = dhan.profile()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Dhan session test failed: {exc}"}), 500
        return jsonify({"credentials": dhan.credentials_status(), "profile": profile})

    @app.get("/api/dhan/summary")
    @_login_required
    def api_dhan_summary():
        try:
            payload = {
                "credentials": dhan.credentials_status(),
                "profile": dhan.profile(),
                "funds": dhan.funds(),
                "holdings": dhan.holdings(),
                "positions": dhan.positions(),
                "orders": dhan.order_book(),
            }
            _save_broker_snapshot("dhan", "summary", payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Dhan summary fetch failed: {exc}"}), 500
        return jsonify(payload)

    @app.get("/api/dhan/trades")
    @_login_required
    def api_dhan_trades():
        try:
            trades = dhan.trade_book(
                from_date=_optional_text(request.args.get("from_date")),
                to_date=_optional_text(request.args.get("to_date")),
            )
            _save_broker_snapshot("dhan", "trades", {"trades": trades})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Dhan trade book fetch failed: {exc}"}), 500
        return jsonify({"trades": trades})

    @app.post("/api/dhan/import/holding")
    @_login_required
    def api_dhan_import_holding():
        payload = request.get_json(silent=True) or {}
        try:
            state = _import_broker_holding(payload.get("row") or payload, broker="dhan")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Dhan holding import failed: {exc}"}), 500
        return jsonify({"state": state})

    @app.post("/api/dhan/import/trade")
    @_login_required
    def api_dhan_import_trade():
        payload = request.get_json(silent=True) or {}
        try:
            state = _import_broker_trade(payload.get("row") or payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Dhan trade import failed: {exc}"}), 500
        return jsonify({"state": state})

    @app.post("/api/icici/save")
    @_login_required
    def api_icici_save():
        payload = request.get_json(silent=True) or {}
        try:
            if broker_gateway.icici_enabled():
                return jsonify(
                    broker_gateway.call(
                        "icici.save",
                        {
                            "api_key": str(payload.get("api_key", "")),
                            "api_secret": str(payload.get("api_secret", "")),
                            "session_token": str(payload.get("session_token", "")),
                        },
                    )
                )
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
            if broker_gateway.icici_enabled():
                return jsonify(
                    broker_gateway.call(
                        "icici.test_quote",
                        {"stock_code": str(payload.get("stock_code", "GOLDEX"))},
                    )
                )
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
        if broker_gateway.icici_enabled():
            try:
                payload = broker_gateway.call("icici.connection", {"stock_code": stock_code})
                payload["gateway"] = broker_gateway.status()
                return jsonify(payload)
            except Exception as exc:
                return jsonify(
                    {
                        "connected": False,
                        "error": str(exc),
                        "credentials": {"configured": False},
                        "gateway": broker_gateway.status(),
                    }
                )
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
            order_params = {
                "symbol": str(payload.get("symbol", "")),
                "side": str(payload.get("side", "")),
                "quantity": payload.get("quantity", ""),
                "limit_price": payload.get("limit_price", ""),
                "dry_run": bool(payload.get("dry_run", True)),
                "product": str(payload.get("product", "cash")),
                "validity": str(payload.get("validity", "day")),
                "user_remark": str(payload.get("user_remark", "")),
            }
            if broker_gateway.icici_enabled():
                return jsonify(broker_gateway.call("icici.limit_order", order_params))
            order = icici.place_limit_order(
                symbol=order_params["symbol"],
                side=order_params["side"],
                quantity=order_params["quantity"],
                limit_price=order_params["limit_price"],
                dry_run=order_params["dry_run"],
                product=order_params["product"],
                validity=order_params["validity"],
                user_remark=order_params["user_remark"],
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
            order_params = {
                "symbol": str(report_action.get("symbol", "")),
                "side": str(report_action.get("side", "")),
                "quantity": quantity,
                "limit_price": price,
                "product": product,
                "dry_run": dry_run,
                "validity": str(payload.get("validity", "day")),
                "user_remark": "emaswing",
            }
            if broker_gateway.icici_enabled():
                order = broker_gateway.call("icici.limit_order", order_params).get("order", {})
            else:
                order = icici.place_limit_order(**order_params)
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
            params = {
                "exchange_code": str(request.args.get("exchange_code", "NSE")),
                "from_date": _optional_text(request.args.get("from_date")),
                "to_date": _optional_text(request.args.get("to_date")),
            }
            if broker_gateway.icici_enabled():
                orders = broker_gateway.call("icici.order_book", params).get("orders", {})
            else:
                orders = icici.order_book(**params)
            _save_broker_snapshot("icici", "orders", {"orders": orders})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI order book failed: {exc}"}), 500
        return jsonify({"orders": orders})

    @app.get("/api/icici/portfolio")
    @_login_required
    def api_icici_portfolio():
        try:
            params = {
                "exchange_code": str(request.args.get("exchange_code", "NSE")),
                "from_date": _optional_text(request.args.get("from_date")),
                "to_date": _optional_text(request.args.get("to_date")),
                "stock_code": str(request.args.get("stock_code", "")),
                "portfolio_type": str(request.args.get("portfolio_type", "")),
            }
            if broker_gateway.icici_enabled():
                payload = broker_gateway.call("icici.portfolio", params)
            else:
                payload = {
                    "funds": icici.funds(),
                    "demat_holdings": icici.demat_holdings(),
                    "portfolio_holdings": icici.portfolio_holdings(**params),
                    "positions": icici.portfolio_positions(),
                }
            _save_broker_snapshot("icici", "portfolio", payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI portfolio fetch failed: {exc}"}), 500
        return jsonify(payload)

    @app.get("/api/icici/trades")
    @_login_required
    def api_icici_trades():
        try:
            params = {
                "exchange_code": str(request.args.get("exchange_code", "NSE")),
                "from_date": _optional_text(request.args.get("from_date")),
                "to_date": _optional_text(request.args.get("to_date")),
                "product_type": str(request.args.get("product_type", "")),
                "action": str(request.args.get("action", "")),
                "stock_code": str(request.args.get("stock_code", "")),
            }
            if broker_gateway.icici_enabled():
                trades = broker_gateway.call("icici.trades", params).get("trades", {})
            else:
                trades = icici.trade_book(**params)
            _save_broker_snapshot("icici", "trades", {"trades": trades})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI trade book fetch failed: {exc}"}), 500
        return jsonify({"trades": trades})

    @app.get("/api/logs")
    @_login_required
    def api_logs():
        lines = int(request.args.get("lines", "300") or 300)
        return jsonify({"settings": _load_log_settings(), "path": str(LOG_PATH), "lines": _tail_log(lines)})

    @app.post("/api/logs/settings")
    @_login_required
    def api_logs_settings():
        payload = request.get_json(silent=True) or {}
        settings = _save_log_settings(
            enabled=bool(payload.get("enabled", True)),
            level=str(payload.get("level", "INFO")),
        )
        return jsonify({"settings": settings})

    @app.post("/api/icici/import/holding")
    @_login_required
    def api_icici_import_holding():
        payload = request.get_json(silent=True) or {}
        try:
            state = _import_broker_holding(payload.get("row") or payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI holding import failed: {exc}"}), 500
        return jsonify({"state": state})

    @app.post("/api/icici/import/trade")
    @_login_required
    def api_icici_import_trade():
        payload = request.get_json(silent=True) or {}
        try:
            state = _import_broker_trade(payload.get("row") or payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI trade import failed: {exc}"}), 500
        return jsonify({"state": state})

    @app.post("/api/icici/order/cancel")
    @_login_required
    def api_icici_order_cancel():
        payload = request.get_json(silent=True) or {}
        try:
            order_id = str(payload.get("order_id", ""))
            params = {"exchange_code": str(payload.get("exchange_code", "NSE")), "order_id": order_id}
            if broker_gateway.icici_enabled():
                cancel = broker_gateway.call("icici.cancel_order", params).get("cancel", {})
            else:
                cancel = icici.cancel_order(**params)
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
            params = {
                "symbol": str(payload.get("symbol", "")),
                "side": str(payload.get("side", "")),
                "quantity": payload.get("quantity", ""),
                "trigger_price": payload.get("trigger_price", ""),
                "limit_price": payload.get("limit_price", ""),
                "dry_run": bool(payload.get("dry_run", True)),
                "expiry_date": _optional_text(payload.get("expiry_date")),
                "trade_date": _optional_text(payload.get("trade_date")),
            }
            if broker_gateway.icici_enabled():
                order = broker_gateway.call("icici.gtt_single", params).get("order", {})
            else:
                order = icici.place_gtt_single_leg_order(**params)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI GTT order failed: {exc}"}), 500
        return jsonify({"order": order})

    @app.get("/api/icici/gtt/book")
    @_login_required
    def api_icici_gtt_book():
        try:
            params = {
                "exchange_code": str(request.args.get("exchange_code", "NSE")),
                "from_date": _optional_text(request.args.get("from_date")),
                "to_date": _optional_text(request.args.get("to_date")),
            }
            if broker_gateway.icici_enabled():
                orders = broker_gateway.call("icici.gtt_book", params).get("orders", {})
            else:
                orders = icici.gtt_order_book(**params)
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


def _broker_codes() -> dict[str, dict[str, str]]:
    aliases = load_icici_symbol_aliases()
    codes: dict[str, dict[str, str]] = {}
    for symbol in ETF_UNIVERSE:
        value = aliases.get(symbol, "")
        icici_code = str(value.get("stock_code", "")) if isinstance(value, dict) else str(value or "")
        dhan_code = symbol.split(":", maxsplit=1)[-1]
        codes[symbol] = {"icici": icici_code or dhan_code, "dhan": dhan_code}
    return codes


def _icici_reverse_aliases() -> dict[str, str]:
    aliases = load_icici_symbol_aliases()
    reverse: dict[str, str] = {}
    for symbol, value in aliases.items():
        stock_code = str(value.get("stock_code") if isinstance(value, dict) else value).strip().upper()
        if stock_code:
            reverse[stock_code] = str(symbol).strip().upper()
    return reverse


def _strategy_symbol_from_broker(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    if symbol.endswith(".NS"):
        symbol = symbol[:-3]
    if symbol.startswith("NSE:"):
        code = symbol.split(":", maxsplit=1)[1]
        return _icici_reverse_aliases().get(code, symbol)
    return _icici_reverse_aliases().get(symbol, f"NSE:{symbol}")


def _load_log_settings() -> dict[str, Any]:
    data = load_json(LOG_SETTINGS_PATH, {"enabled": True, "level": "INFO"})
    level = str(data.get("level", "INFO")).upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        level = "INFO"
    return {"enabled": bool(data.get("enabled", True)), "level": level}


def _save_log_settings(enabled: bool, level: str) -> dict[str, Any]:
    settings = {"enabled": bool(enabled), "level": str(level or "INFO").upper()}
    if settings["level"] not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        settings["level"] = "INFO"
    save_json(LOG_SETTINGS_PATH, settings)
    _configure_logging()
    LOGGER.info("Log settings updated: enabled=%s level=%s", settings["enabled"], settings["level"])
    return settings


def _configure_logging() -> None:
    settings = _load_log_settings()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings["level"], logging.INFO) if settings["enabled"] else logging.CRITICAL + 1)
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == LOG_PATH for handler in root.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)


def _tail_log(lines: int) -> list[str]:
    if not LOG_PATH.exists():
        return []
    keep = max(min(lines, 2000), 50)
    with LOG_PATH.open(encoding="utf-8", errors="replace") as file:
        return file.readlines()[-keep:]


def _load_latest_report() -> dict[str, Any] | None:
    if not LIVE_REPORT_PATH.exists():
        return None
    with LIVE_REPORT_PATH.open(encoding="utf-8-sig") as file:
        report = json.load(file)
    if not isinstance(report, dict):
        raise ValueError(f"Expected live report object in {LIVE_REPORT_PATH}")
    return report


def _sync_status() -> dict[str, Any]:
    remote_url = os.getenv("EMA_SWING_REMOTE_URL", "").strip()
    token = os.getenv("EMA_SWING_SYNC_TOKEN", "").strip()
    return {
        "remote_url": remote_url,
        "remote_configured": bool(remote_url),
        "token_configured": bool(token),
        "export_token_required": bool(token),
    }


def _sync_export_payload() -> dict[str, Any]:
    return {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "settings": load_settings(),
        "live_config": _load_live_config(),
        "live_state": _load_live_state(),
        "report": _load_latest_report(),
        "broker_orders": _load_broker_orders(),
        "storage": {"database_path": str(database.DB_PATH), "mode": "sqlite_mirror"},
    }


def _fetch_remote_sync(remote_url: str, token: str) -> dict[str, Any]:
    url = urljoin(remote_url.rstrip("/") + "/", "api/sync/export")
    headers = {"Accept": "application/json"}
    if token:
        headers["X-EMA-Swing-Sync-Token"] = token
    request_obj = Request(url, headers=headers, method="GET")
    with urlopen(request_obj, timeout=30) as response:
        text = response.read().decode("utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Remote sync response was not a JSON object.")
    if data.get("error"):
        raise ValueError(str(data["error"]))
    return data


def _apply_sync_payload(payload: dict[str, Any]) -> dict[str, Any]:
    applied: dict[str, Any] = {}
    settings = payload.get("settings")
    if isinstance(settings, dict):
        save_settings(settings)
        applied["settings"] = True

    config = payload.get("live_config")
    if isinstance(config, dict):
        save_json(LIVE_CONFIG_PATH, config)
        applied["live_config"] = True

    live_state = payload.get("live_state")
    if isinstance(live_state, dict):
        save_live_state(live_state, LIVE_STATE_PATH)
        applied["live_state"] = True

    report = payload.get("report")
    if isinstance(report, dict):
        save_live_report(report, LIVE_REPORT_PATH)
        applied["report"] = True

    broker_orders = payload.get("broker_orders")
    if isinstance(broker_orders, list):
        _save_broker_orders([row for row in broker_orders if isinstance(row, dict)])
        applied["broker_orders"] = True

    database.append_audit(
        "pull",
        "sync",
        str(payload.get("exported_at", "")),
        {"remote_exported_at": payload.get("exported_at"), "applied": applied},
    )
    return applied


def _valid_sync_token() -> bool:
    expected = os.getenv("EMA_SWING_SYNC_TOKEN", "").strip()
    supplied = str(request.headers.get("X-EMA-Swing-Sync-Token", "")).strip()
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def _valid_broker_gateway_token() -> bool:
    expected = (
        os.getenv("EMA_SWING_BROKER_GATEWAY_TOKEN", "").strip()
        or os.getenv("EMA_SWING_SYNC_TOKEN", "").strip()
    )
    supplied = str(request.headers.get(broker_gateway.TOKEN_HEADER, "")).strip()
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def _execute_broker_gateway_operation(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    if operation == "icici.credentials_status":
        return {"credentials": icici.credentials_status()}
    if operation == "icici.login_url":
        return {"url": icici.login_url(str(params.get("api_key", "")))}
    if operation == "icici.session":
        api_key = str(params.get("api_key", "")).strip()
        api_secret = str(params.get("api_secret", "")).strip()
        session_token = str(params.get("session_token", "")).strip()
        test = icici.test_session(
            api_key=api_key,
            api_secret=api_secret,
            session_token=session_token,
            stock_code=str(params.get("stock_code", "GOLDEX")),
        )
        icici.save_credentials(api_key=api_key, api_secret=api_secret, session_token=session_token)
        return {"credentials": icici.credentials_status(), "test": test}
    if operation == "icici.save":
        icici.save_credentials(
            api_key=str(params.get("api_key", "")),
            api_secret=str(params.get("api_secret", "")),
            session_token=str(params.get("session_token", "")),
        )
        return {"credentials": icici.credentials_status()}
    if operation == "icici.connection":
        test = icici.test_quote(stock_code=str(params.get("stock_code", "GOLDEX")))
        return {"connected": bool(test.get("ok")), "test": test, "credentials": icici.credentials_status()}
    if operation == "icici.test_quote":
        return {"test": icici.test_quote(stock_code=str(params.get("stock_code", "GOLDEX")))}
    if operation == "icici.limit_order":
        return {
            "order": icici.place_limit_order(
                symbol=str(params.get("symbol", "")),
                side=str(params.get("side", "")),
                quantity=params.get("quantity"),
                limit_price=params.get("limit_price"),
                dry_run=bool(params.get("dry_run", True)),
                product=str(params.get("product", "cash")),
                validity=str(params.get("validity", "day")),
                user_remark=str(params.get("user_remark", "emaswing")),
            )
        }
    if operation == "icici.gtt_single":
        return {
            "order": icici.place_gtt_single_leg_order(
                symbol=str(params.get("symbol", "")),
                side=str(params.get("side", "")),
                quantity=params.get("quantity"),
                trigger_price=params.get("trigger_price"),
                limit_price=params.get("limit_price"),
                dry_run=bool(params.get("dry_run", True)),
                expiry_date=_optional_text(params.get("expiry_date")),
                trade_date=_optional_text(params.get("trade_date")),
            )
        }
    if operation == "icici.gtt_book":
        return {
            "orders": icici.gtt_order_book(
                exchange_code=str(params.get("exchange_code", "NSE")),
                from_date=_optional_text(params.get("from_date")),
                to_date=_optional_text(params.get("to_date")),
            )
        }
    if operation == "icici.order_book":
        return {
            "orders": icici.order_book(
                exchange_code=str(params.get("exchange_code", "NSE")),
                from_date=_optional_text(params.get("from_date")),
                to_date=_optional_text(params.get("to_date")),
            )
        }
    if operation == "icici.portfolio":
        payload = {
            "funds": icici.funds(),
            "demat_holdings": icici.demat_holdings(),
            "portfolio_holdings": icici.portfolio_holdings(
                exchange_code=str(params.get("exchange_code", "NSE")),
                from_date=_optional_text(params.get("from_date")),
                to_date=_optional_text(params.get("to_date")),
                stock_code=str(params.get("stock_code", "")),
                portfolio_type=str(params.get("portfolio_type", "")),
            ),
            "positions": icici.portfolio_positions(),
        }
        _save_broker_snapshot("icici", "portfolio", payload)
        return payload
    if operation == "icici.trades":
        trades = icici.trade_book(
            exchange_code=str(params.get("exchange_code", "NSE")),
            from_date=_optional_text(params.get("from_date")),
            to_date=_optional_text(params.get("to_date")),
            product_type=str(params.get("product_type", "")),
            action=str(params.get("action", "")),
            stock_code=str(params.get("stock_code", "")),
        )
        _save_broker_snapshot("icici", "trades", {"trades": trades})
        return {"trades": trades}
    if operation == "icici.cancel_order":
        return {
            "cancel": icici.cancel_order(
                exchange_code=str(params.get("exchange_code", "NSE")),
                order_id=str(params.get("order_id", "")),
            )
        }
    raise ValueError(f"Unsupported broker gateway operation: {operation}")


def _load_live_state() -> dict[str, Any]:
    config = _load_live_config()
    state = load_live_state(LIVE_STATE_PATH, initial_capital=float(config.get("initial_capital", 0)))
    changed = _repair_strategy_holdings(state)
    if reconcile_strategy_cash(state, float(config.get("initial_capital", 0))):
        changed = True
    if changed:
        save_live_state(state, LIVE_STATE_PATH)
    return state


def _repair_strategy_holdings(state: dict[str, Any]) -> bool:
    holdings = state.get("holdings")
    if not isinstance(holdings, dict):
        return False

    changed = False
    repaired: dict[str, Any] = {}
    for key, holding in list(holdings.items()):
        if not isinstance(holding, dict):
            continue
        symbol = _strategy_symbol_from_broker(holding.get("symbol") or key)
        row = dict(holding)
        if symbol and symbol != row.get("symbol"):
            row["symbol"] = symbol
            changed = True

        cost_basis = float(row.get("cost_basis", 0) or 0)
        if cost_basis <= 0:
            cost_basis = float(row.get("shares", 0) or 0) * float(row.get("entry_price", 0) or 0)
            row["cost_basis"] = cost_basis
        margin_used = float(row.get("margin_used", 0) or 0)
        mtf_loan = float(row.get("mtf_loan", 0) or 0)
        if margin_used > 0 and mtf_loan <= 0 and cost_basis > margin_used:
            row["funding_mode"] = "mtf"
            row["mtf_loan"] = max(cost_basis - margin_used, 0.0)
            changed = True

        details = _latest_signal_details(symbol)
        if not row.get("entry_ema") and details.get("entry_ema"):
            row["entry_ema"] = details["entry_ema"]
            changed = True
        if not row.get("entry_low") and details.get("entry_low"):
            row["entry_low"] = details["entry_low"]
            changed = True

        repaired[symbol or str(key)] = row
        if symbol and symbol != key:
            changed = True

    if changed:
        state["holdings"] = repaired
    return changed


def _apply_capital_delta(capital_delta: float, old_initial_capital: float, config: dict[str, Any]) -> dict[str, Any]:
    state = load_live_state(LIVE_STATE_PATH, initial_capital=old_initial_capital)
    if abs(capital_delta) < 0.005:
        return state
    state["cash"] = float(state.get("cash", old_initial_capital) or 0) + capital_delta
    state.setdefault("capital_adjustments", []).append(
        {
            "date": datetime.now().date().isoformat(),
            "amount": capital_delta,
            "reason": "initial_capital_update",
            "initial_capital": float(config.get("initial_capital", 0) or 0),
        }
    )
    save_live_state(state, LIVE_STATE_PATH)
    return state


def _load_broker_orders() -> list[dict[str, Any]]:
    data = load_json(BROKER_ORDERS_PATH, {"orders": []})
    orders = data.get("orders", [])
    return orders if isinstance(orders, list) else []


def _save_broker_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    save_json(BROKER_ORDERS_PATH, {"orders": orders[-200:]})
    return orders[-200:]


def _save_broker_snapshot(broker: str, snapshot_type: str, data: dict[str, Any]) -> None:
    try:
        database.save_broker_snapshot(broker, snapshot_type, data)
    except Exception:
        LOGGER.exception("Could not save %s %s broker snapshot", broker, snapshot_type)


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


def _latest_signal_details(symbol: str) -> dict[str, float]:
    report = _load_latest_report() or {}
    for row in report.get("signal_rows", []):
        if str(row.get("symbol", "")).strip().upper() == str(symbol or "").strip().upper():
            return {
                "entry_ema": float(row.get("source_ema", 0) or 0),
                "entry_low": float(row.get("source_low") or row.get("source_price") or row.get("price") or 0),
                "cmp": float(row.get("price", 0) or 0),
            }
    return {"entry_ema": 0.0, "entry_low": 0.0, "cmp": 0.0}


def _book_report_action(action_id: str, quantity: Any, price: Any, product: str, broker_order_id: str = "") -> dict[str, Any]:
    action = _report_action(action_id)
    config = _load_live_config()
    state = _load_live_state()
    booked = _action_with_order_values(action, state, quantity=quantity, price=price, product=product, broker_order_id=broker_order_id)
    _apply_actions(state, [booked], config)
    _repair_strategy_holdings(state)
    reconcile_strategy_cash(state, float(config.get("initial_capital", 0)))
    save_live_state(state, LIVE_STATE_PATH)
    return state


def _import_broker_holding(row: Any, broker: str = "icici") -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("Broker holding row is required.")
    symbol = _strategy_symbol_from_broker(row.get("symbol") or row.get("stock_code"))
    if not symbol:
        raise ValueError("Broker row has no symbol.")
    shares = int(_positive_number(row.get("quantity"), f"{symbol} quantity"))
    price = _positive_number(row.get("price"), f"{symbol} price")
    value = float(row.get("value", shares * price) or shares * price)
    margin_amount = float(row.get("margin_amount", 0) or 0)
    funding_mode = "mtf" if str(row.get("funding_mode", "")).lower() == "mtf" or (margin_amount > 0 and value > margin_amount) else "delivery"
    mtf_loan = float(row.get("mtf_loan", 0) or 0)
    if funding_mode == "mtf" and mtf_loan <= 0 and margin_amount > 0:
        mtf_loan = max(value - margin_amount, 0.0)

    config = _load_live_config()
    state = _load_live_state()
    holdings = state.setdefault("holdings", {})
    previous = holdings.get(symbol)
    previous_cash_required = 0.0
    if previous:
        previous_cash_required = float(previous.get("cost_basis", 0) or 0) - float(previous.get("mtf_loan", 0) or 0)
    cash_required = value - mtf_loan if funding_mode == "mtf" else value
    signal_details = _latest_signal_details(symbol)
    entry_date = _date_text(row.get("date") or row.get("buy_date") or row.get("purchase_date"))
    holdings[symbol] = {
        "symbol": symbol,
        "shares": shares,
        "entry_price": price,
        "entry_date": entry_date,
        "cost_basis": value,
        "funding_mode": funding_mode,
        "mtf_loan": mtf_loan,
        "margin_used": margin_amount,
        "broker": broker,
        "entry_ema": signal_details.get("entry_ema", 0.0),
        "entry_low": signal_details.get("entry_low", 0.0),
    }
    state["cash"] = float(state.get("cash", config["initial_capital"]) or 0) + previous_cash_required - cash_required
    reconcile_strategy_cash(state, float(config.get("initial_capital", 0)))
    save_live_state(state, LIVE_STATE_PATH)
    return state


def _import_broker_trade(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("Broker trade row is required.")
    action = _broker_row_action(row)
    config = _load_live_config()
    state = _load_live_state()
    if action["side"] == "SELL":
        holding = state.get("holdings", {}).get(action["symbol"], {})
        action["mtf_loan_repayment"] = float(holding.get("mtf_loan", 0) or 0)
        action["cash_delta"] = float(action["value"]) - float(action["mtf_loan_repayment"])
        action["profit"] = float(action["value"]) - float(holding.get("cost_basis", action["value"]) or action["value"])
    _apply_actions(state, [action], config)
    _repair_strategy_holdings(state)
    reconcile_strategy_cash(state, float(config.get("initial_capital", 0)))
    save_live_state(state, LIVE_STATE_PATH)
    return state


def _broker_row_action(row: dict[str, Any]) -> dict[str, Any]:
    symbol = _strategy_symbol_from_broker(row.get("symbol") or row.get("stock_code"))
    side = str(row.get("side", "")).strip().upper()
    if not symbol:
        raise ValueError("Broker trade row has no symbol.")
    if side not in {"BUY", "SELL"}:
        raise ValueError("Broker trade row must be BUY or SELL.")
    shares = int(_positive_number(row.get("quantity"), f"{symbol} quantity"))
    price = _positive_number(row.get("price"), f"{symbol} price")
    value = float(row.get("value", shares * price) or shares * price)
    mtf_loan = float(row.get("mtf_loan", 0) or 0)
    margin_amount = float(row.get("margin_amount", 0) or 0)
    funding_mode = "mtf" if str(row.get("funding_mode", "")).lower() == "mtf" or (margin_amount > 0 and value > margin_amount) else "delivery"
    if funding_mode == "mtf" and mtf_loan <= 0 and margin_amount > 0:
        mtf_loan = max(value - margin_amount, 0.0)
    if funding_mode == "mtf" and mtf_loan <= 0 and side == "BUY":
        raise ValueError("ICICI row did not include MTF loan or margin amount. Import from Portfolio after ICICI updates the position.")
    return {
        "side": side,
        "symbol": symbol,
        "date": _date_text(row.get("date")),
        "signal_date": _date_text(row.get("date")),
        "price": price,
        "shares": shares,
        "value": value,
        "cash_required": value - mtf_loan if funding_mode == "mtf" else value,
        "funding_mode": funding_mode,
        "mtf_loan": mtf_loan,
        "broker_order_id": str(row.get("order_id", "")).strip(),
        "broker": str(row.get("broker", "")).strip(),
        "reason": "icici_import",
    }


def _action_with_order_values(action: dict[str, Any], state: dict[str, Any], quantity: Any, price: Any, product: str, broker_order_id: str) -> dict[str, Any]:
    booked = dict(action)
    shares = int(_positive_number(quantity if quantity is not None else action.get("shares"), "Quantity"))
    order_price = _positive_number(price if price is not None else action.get("price"), "Price")
    value = shares * order_price
    funding_mode = "mtf" if str(product).strip().lower() == "mtf" else "delivery"
    mtf_multiple = max(float(_load_live_config().get("mtf_funded_multiple", 3) or 3), 1.0)
    estimated_margin = value / mtf_multiple if funding_mode == "mtf" and booked.get("side") == "BUY" else value
    estimated_loan = max(value - estimated_margin, 0.0) if funding_mode == "mtf" and booked.get("side") == "BUY" else 0.0
    booked.update(
        {
            "shares": shares,
            "price": order_price,
            "value": value,
            "broker_order_id": broker_order_id,
            "funding_mode": funding_mode,
            "mtf_loan": estimated_loan,
            "margin_used": estimated_margin if funding_mode == "mtf" and booked.get("side") == "BUY" else 0.0,
            "cash_required": estimated_margin if funding_mode == "mtf" and booked.get("side") == "BUY" else value,
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


def _date_text(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if text else datetime.now().date().isoformat()


def _normalize_live_state(payload: dict[str, Any]) -> dict[str, Any]:
    current = _load_live_state()
    config = _load_live_config()
    state = dict(current)
    state["holdings"] = _normalize_holdings(payload.get("holdings", current.get("holdings", {})))
    state["trades"] = _normalize_trades(payload.get("trades", current.get("trades", [])))
    if "cash" in payload:
        state["cash"] = float(payload.get("cash", current.get("cash", 0)) or 0)
    else:
        state["cash"] = float(current.get("cash", config.get("initial_capital", 0)) or 0)
    state["completed_trades"] = []
    state.setdefault("capital_adjustments", current.get("capital_adjustments", []))
    state.setdefault("created_at", current.get("created_at", datetime.now().isoformat(timespec="seconds")))
    _repair_strategy_holdings(state)
    reconcile_strategy_cash(state, float(config.get("initial_capital", 0)))
    return state


def _normalize_holdings(value: Any) -> dict[str, Any]:
    rows = value.values() if isinstance(value, dict) else value
    if not isinstance(rows, list) and not hasattr(rows, "__iter__"):
        raise ValueError("Holdings must be a list or object.")
    holdings: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _strategy_symbol_from_broker(row.get("symbol"))
        if not symbol:
            continue
        shares = int(_positive_number(row.get("shares"), f"{symbol} shares"))
        entry_price = _positive_number(row.get("entry_price"), f"{symbol} entry price")
        cost_basis = float(row.get("cost_basis", shares * entry_price) or shares * entry_price)
        margin_used = float(row.get("margin_used", 0) or 0)
        mtf_loan = float(row.get("mtf_loan", 0) or 0)
        funding_mode = str(row.get("funding_mode", "delivery")).strip().lower()
        if funding_mode not in {"delivery", "mtf"}:
            funding_mode = "delivery"
        if margin_used > 0 and mtf_loan <= 0 and cost_basis > margin_used:
            funding_mode = "mtf"
            mtf_loan = max(cost_basis - margin_used, 0.0)
        details = _latest_signal_details(symbol)
        holdings[symbol] = {
            "symbol": symbol,
            "shares": shares,
            "entry_price": entry_price,
            "entry_date": str(row.get("entry_date", "")).strip() or datetime.now().date().isoformat(),
            "cost_basis": cost_basis,
            "funding_mode": funding_mode,
            "mtf_loan": mtf_loan,
            "margin_used": margin_used,
            "broker": str(row.get("broker", "")).strip(),
            "entry_ema": float(row.get("entry_ema", 0) or details.get("entry_ema", 0) or 0),
            "entry_low": float(row.get("entry_low", 0) or details.get("entry_low", 0) or 0),
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
                "broker": str(row.get("broker", "")).strip(),
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
    if normalized in {"auto", "dhan", "dhanhq"}:
        dhan.seed_environment()
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
