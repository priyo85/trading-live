"""Flask app for the live-only 9 EMA swing dashboard."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE
from backtesting.etf_backtester.live.signal_runner import LIVE_CONFIG_PATH, clear_live_ledger, run_live_signals
from backtesting.etf_backtester.live.state import LIVE_REPORT_PATH
from ema_swing_live import icici
from ema_swing_live.storage import INSTANCE_DIR, load_settings, save_json, save_settings


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
                validity=str(payload.get("validity", "day")),
                user_remark=str(payload.get("user_remark", "")),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"ICICI limit order failed: {exc}"}), 500
        return jsonify({"order": order})

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
