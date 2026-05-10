"""Flask web UI for ETF swing backtests."""

from __future__ import annotations

import json
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE
from backtesting.etf_backtester.config.signal_sources import SIGNAL_SOURCES, load_signal_sources, save_signal_sources
from backtesting.etf_backtester.config.settings import DEFAULT_CONFIG, STRATEGY_SETTINGS, WEB_UI_SETTINGS
from backtesting.etf_backtester.metrics.performance import cagr, xirr
from backtesting.etf_backtester.reports.multi_summary import build_multi_summary
from backtesting.etf_backtester.reports.period_returns import build_period_returns, report_frequency
from backtesting.etf_backtester.reports.result_store import (
    list_backtest_reports,
    load_backtest_report,
    save_backtest_report,
)
from backtesting.etf_backtester.data.market_data import fetch_current_prices
from backtesting.etf_backtester.live.signal_runner import LIVE_CONFIG_PATH, clear_live_ledger, run_live_signals
from backtesting.etf_backtester.live.state import LIVE_REPORT_PATH, LIVE_STATE_PATH, build_completed_trades, load_live_state, save_live_report, save_live_state
from backtesting.etf_backtester.services.backtest_runner import EmaBacktestRequest, run_ema_backtest
from backtesting.market_data.dhanhq import credentials_status, save_credentials as save_dhan_credentials


def create_app() -> Flask:
    """Create the ETF backtester web app."""

    app = Flask(__name__)

    @app.get("/")
    def index():
        ema_defaults = STRATEGY_SETTINGS["ema_trend"]
        ema_atr_defaults = STRATEGY_SETTINGS["ema_atr_confirmed"]
        rsi_defaults = STRATEGY_SETTINGS["rsi_50_cross"]
        return render_template(
            "index.html",
            etf_universe=ETF_UNIVERSE,
            signal_sources=SIGNAL_SOURCES,
            strategies=STRATEGY_SETTINGS,
            defaults={
                "initial_capital": DEFAULT_CONFIG.initial_capital,
                "max_positions": DEFAULT_CONFIG.max_positions,
                "start_date": DEFAULT_CONFIG.default_start_date,
                "end_date": datetime.today().date().isoformat(),
                "ema_window": ema_defaults["window"],
                "atr_window": ema_atr_defaults["atr_window"],
                "atr_multiplier": ema_atr_defaults["atr_multiplier"],
                "confirmation_days": ema_atr_defaults["confirmation_days"],
                "rsi_window": rsi_defaults["window"],
                "strategy_name": ema_defaults["display_name"],
                "rank_buy_candidates_by_ath": DEFAULT_CONFIG.rank_buy_candidates_by_ath,
                "rotate_to_stronger_candidates": DEFAULT_CONFIG.rotate_to_stronger_candidates,
                "compound_positions": DEFAULT_CONFIG.compound_positions,
                "buy_all_overflow_signals": False,
                "mtf_mode": "off",
                "extra_capital_limit_multiplier": 1.0,
                "max_overflow_positions": 2,
                "extra_capital_interest_rate_daily_pct": 0.0,
                "monthly_capital_addition": 0.0,
                "withdrawal_target": 0.0,
                "monthly_withdrawal_amount": 0.0,
                "price_time": DEFAULT_CONFIG.price_time,
            },
        )

    @app.post("/api/backtest")
    def api_backtest():
        try:
            backtest_request = _parse_backtest_request(request.get_json(silent=True) or {})
            run = run_ema_backtest(backtest_request)
            result = run.result
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Backtest failed: {exc}"}), 500

        frequency = report_frequency(
            result.equity_curve,
            DEFAULT_CONFIG.yearly_report_threshold_years,
        )
        period_returns = build_period_returns(result.equity_curve, frequency)
        price_time = (
            backtest_request.price_time.isoformat(timespec="minutes")
            if backtest_request.price_time
            else "Daily close"
        )
        serialized_trades = [_serialize_row(row) for row in result.trades]
        response_data = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "summary": build_multi_summary(result),
            "cagr": cagr(result.equity_curve),
            "xirr": xirr(result.capital_flows),
            "capital_flows": [_serialize_row(row) for row in result.capital_flows],
            "total_capital_added": result.total_capital_added,
            "total_capital_withdrawn": result.total_capital_withdrawn,
            "total_extra_capital": result.total_extra_capital,
            "max_extra_capital_used": result.max_extra_capital_used,
            "extra_capital_balance": result.extra_capital_balance,
            "total_extra_capital_interest": result.total_extra_capital_interest,
            "period_report_frequency": frequency,
            "period_returns": [_serialize_row(row.__dict__) for row in period_returns],
            "equity_curve": [_serialize_row(row) for row in result.equity_curve],
            "trades": serialized_trades,
            "trade_ledger": _build_backtest_trade_ledger(serialized_trades),
            "realized_profit": result.realized_profit,
            "unrealized_profit": result.unrealized_profit,
            "open_positions": [_serialize_row(row) for row in result.open_positions],
            "per_symbol_report": [_serialize_row(row) for row in result.per_symbol_report],
            "skipped_symbols": result.skipped_symbols,
            "price_time": price_time,
            "condition_identifier": run.condition_identifier,
            "signal_sources": run.signal_sources,
            "config": _request_config(backtest_request),
        }
        saved_path = save_backtest_report(response_data, run.condition_identifier)
        response_data["saved_report_path"] = str(saved_path)

        return jsonify(response_data)

    @app.get("/api/reports")
    def api_reports():
        return jsonify({"reports": list_backtest_reports()})

    @app.get("/api/reports/<report_id>")
    def api_report(report_id: str):
        try:
            return jsonify(load_backtest_report(report_id))
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 404

    @app.get("/api/live/report")
    def api_live_report():
        try:
            state = _load_live_state_snapshot()
            if not LIVE_REPORT_PATH.exists():
                completed_trades = _completed_trades_from_state(state)
                return jsonify({"report": _manual_live_report(state, completed_trades) if completed_trades or state.get("holdings") or state.get("capital_adjustments") else None})
            with LIVE_REPORT_PATH.open(encoding="utf-8") as file:
                report = json.load(file)
            ledger_trades = state.get("trades", report.get("ledger_trades", []))
            report["ledger_trades"] = ledger_trades
            report["completed_trades"] = _completed_trades_from_state(state)
            report["holdings"] = _live_holdings_from_state(state, report.get("holdings", []))
            report["cash"] = float(state.get("cash", report.get("cash", 0)))
            report["equity"] = _live_equity(report["cash"], report["holdings"])
            report["capital_adjustments"] = state.get("capital_adjustments", [])
            report["config"] = _load_live_config_snapshot()
            report["capital_base"] = _capital_base(report["config"], state)
            report["mtf"] = _live_mtf_report(report["config"], report["holdings"], report["cash"])
            report["xirr"] = _live_report_xirr(report["config"], state, report["equity"])
            report["trades_count"] = len(ledger_trades)
            return jsonify({"report": report})
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/live/run")
    def api_live_run():
        payload = request.get_json(silent=True) or {}
        apply_actions = bool(payload.get("apply_actions", False))
        selected_action_ids = payload.get("selected_action_ids")
        if selected_action_ids is not None and not isinstance(selected_action_ids, list):
            return jsonify({"error": "selected_action_ids must be a list."}), 400
        if apply_actions:
            try:
                report = _apply_selected_live_report_actions(selected_action_ids)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            except Exception as exc:
                return jsonify({"error": f"Live action apply failed: {exc}"}), 500

            return jsonify({
                "report": report,
                "report_path": str(LIVE_REPORT_PATH),
                "state_path": str(LIVE_STATE_PATH),
            })

        try:
            run = run_live_signals(
                apply_actions=apply_actions,
                selected_action_ids=selected_action_ids,
                run_date=None,
                run_time=None,
                use_current_price=True,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live signal run failed: {exc}"}), 500

        return jsonify({
            "report": run.report,
            "report_path": str(run.report_path),
            "state_path": str(run.state_path),
        })

    @app.post("/api/live/clear")
    def api_live_clear():
        try:
            state = clear_live_ledger()
        except Exception as exc:
            return jsonify({"error": f"Live ledger clear failed: {exc}"}), 500

        return jsonify({"state": state, "report": None})

    @app.post("/api/live/ledger")
    def api_live_ledger_update():
        payload = request.get_json(silent=True) or {}
        try:
            config = _load_live_config_snapshot()
            state = load_live_state(initial_capital=float(config["initial_capital"]))
            holdings = _normalize_live_holdings(payload.get("holdings", []))
            completed_trades = _normalize_completed_trades(payload.get("completed_trades", []))
            state["holdings"] = {holding["symbol"]: holding for holding in holdings}
            state["completed_trades"] = completed_trades
            state["trades"] = []
            state["cash"] = _cash_from_manual_ledger(config, holdings, completed_trades)
            save_live_state(state)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live ledger update failed: {exc}"}), 500

        return jsonify({
            "state": state,
            "completed_trades": completed_trades,
            "holdings": list(state["holdings"].values()),
        })

    @app.get("/api/live/config")
    def api_live_config():
        try:
            return jsonify({"config": _load_live_config_snapshot()})
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/live/config")
    def api_live_config_update():
        payload = request.get_json(silent=True) or {}
        try:
            config = _load_live_config_snapshot()
            max_positions = int(payload.get("max_positions", config.get("max_positions", DEFAULT_CONFIG.max_positions)))
            if max_positions <= 0:
                raise ValueError("Max live ETFs must be greater than zero.")
            config["max_positions"] = max_positions
            config["mtf_enabled"] = bool(payload.get("mtf_enabled", config.get("mtf_enabled", False)))
            config["mtf_broker"] = str(payload.get("mtf_broker", config.get("mtf_broker", "ICICI Direct Prime 4999"))).strip() or "ICICI Direct Prime 4999"
            config["mtf_pledged_liquidcase_value"] = _bounded_float(payload.get("mtf_pledged_liquidcase_value", config.get("mtf_pledged_liquidcase_value", 0)), "Pledged LiquidCASE value", 0, None)
            config["mtf_cash_buffer_pct"] = _bounded_float(payload.get("mtf_cash_buffer_pct", config.get("mtf_cash_buffer_pct", 20)), "MTF cash buffer", 0, 100)
            config["mtf_funded_multiple"] = _bounded_float(payload.get("mtf_funded_multiple", config.get("mtf_funded_multiple", 3)), "MTF funded multiple", 0, 5)
            config["mtf_collateral_haircut_pct"] = _bounded_float(payload.get("mtf_collateral_haircut_pct", config.get("mtf_collateral_haircut_pct", 6)), "MTF collateral haircut", 0, 100)
            config["mtf_interest_rate_annual_pct"] = _bounded_float(payload.get("mtf_interest_rate_annual_pct", config.get("mtf_interest_rate_annual_pct", 9.65)), "MTF annual interest", 0, 100)
            _save_json(LIVE_CONFIG_PATH, config)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Live config update failed: {exc}"}), 500

        return jsonify({"config": config})

    @app.get("/api/live/dhan-credentials")
    def api_dhan_credentials():
        return jsonify({"credentials": credentials_status()})

    @app.post("/api/live/dhan-credentials")
    def api_dhan_credentials_update():
        payload = request.get_json(silent=True) or {}
        try:
            save_dhan_credentials(
                client_id=str(payload.get("client_id", "")).strip(),
                access_token=str(payload.get("access_token", "")).strip(),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Dhan credentials update failed: {exc}"}), 500

        return jsonify({"credentials": credentials_status()})

    @app.post("/api/live/capital-ledger")
    def api_live_capital_ledger_update():
        payload = request.get_json(silent=True) or {}
        try:
            config = _load_live_config_snapshot()
            state = load_live_state(initial_capital=float(config["initial_capital"]))
            old_adjustments = state.get("capital_adjustments", [])
            old_total = _capital_adjustment_total(old_adjustments)
            new_adjustments = _normalize_capital_adjustments(payload.get("capital_adjustments", []))
            new_total = _capital_adjustment_total(new_adjustments)
            cash_after = float(state.get("cash", config["initial_capital"])) + (new_total - old_total)
            if cash_after < 0:
                raise ValueError("Capital ledger edit cannot make cash negative.")
            state["capital_adjustments"] = new_adjustments
            state["cash"] = cash_after
            save_live_state(state)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Capital ledger update failed: {exc}"}), 500

        return jsonify({"state": state, "capital_adjustments": new_adjustments})

    @app.post("/api/live/capital")
    def api_live_capital_update():
        payload = request.get_json(silent=True) or {}
        try:
            config = _load_live_config_snapshot()
            state = load_live_state(initial_capital=float(config["initial_capital"]))
            adjustment = _normalize_capital_adjustment(payload)
            cash_after = float(state.get("cash", config["initial_capital"])) + adjustment["amount"]
            if cash_after < 0:
                raise ValueError("Capital reduction cannot make cash negative.")
            state.setdefault("capital_adjustments", []).append(adjustment)
            state["cash"] = cash_after
            save_live_state(state)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Capital update failed: {exc}"}), 500

        return jsonify({"state": state, "adjustment": adjustment})

    @app.get("/api/signal-sources")
    def api_signal_sources():
        return jsonify({"signal_sources": load_signal_sources()})

    @app.post("/api/signal-sources")
    def api_signal_sources_update():
        payload = request.get_json(silent=True) or {}
        try:
            mapping = _normalize_signal_source_updates(payload.get("signal_sources", {}))
            saved = save_signal_sources(mapping)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Signal source mapping update failed: {exc}"}), 500

        return jsonify({"signal_sources": saved})

    return app


def run_web_ui(
    host: str = WEB_UI_SETTINGS["host"],
    port: int = int(WEB_UI_SETTINGS["port"]),
    debug: bool = False,
) -> None:
    """Launch the browser-based UI."""

    app = create_app()
    app.run(host=host, port=port, debug=debug)


def _parse_backtest_request(payload: dict) -> EmaBacktestRequest:
    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("Select at least one ETF.")

    invalid_symbols = [symbol for symbol in symbols if symbol not in ETF_UNIVERSE]
    if invalid_symbols:
        raise ValueError(f"Unknown ETF symbol: {', '.join(invalid_symbols)}")

    initial_capital = float(payload.get("initial_capital", DEFAULT_CONFIG.initial_capital))
    if initial_capital <= 0:
        raise ValueError("Initial capital must be greater than zero.")

    max_positions = int(payload.get("max_positions", DEFAULT_CONFIG.max_positions))
    if max_positions <= 0:
        raise ValueError("Max ETFs to buy must be greater than zero.")

    strategy_name = str(payload.get("strategy", "ema_trend")).strip()
    if strategy_name not in {
        "ema_trend",
        "weekly_ema_cross",
        "ema_entry_low_sell",
        "ema_atr_confirmed",
        "ema_atr_sell_band",
        "rsi_50_cross",
        "rsi_divergence_staged",
    }:
        raise ValueError("Unknown strategy.")

    ema_window = int(payload.get("ema_window", STRATEGY_SETTINGS["ema_trend"]["window"]))
    if ema_window <= 1:
        raise ValueError("EMA window must be greater than one.")
    atr_window = int(payload.get("atr_window", STRATEGY_SETTINGS["ema_atr_confirmed"]["atr_window"]))
    if atr_window <= 1:
        raise ValueError("ATR window must be greater than one.")
    atr_multiplier = float(payload.get("atr_multiplier", STRATEGY_SETTINGS["ema_atr_confirmed"]["atr_multiplier"]))
    if atr_multiplier < 0:
        raise ValueError("ATR multiplier cannot be negative.")
    confirmation_days = int(payload.get("confirmation_days", STRATEGY_SETTINGS["ema_atr_confirmed"]["confirmation_days"]))
    if confirmation_days <= 0:
        raise ValueError("Confirmation days must be greater than zero.")
    if strategy_name == "weekly_ema_cross" and confirmation_days not in {2, 3}:
        raise ValueError("Weekly EMA confirmation must be 2 or 3 candles.")
    rsi_window = int(payload.get("rsi_window", STRATEGY_SETTINGS["rsi_50_cross"]["window"]))
    if rsi_window <= 1:
        raise ValueError("RSI window must be greater than one.")
    if "candidate_ranking" in payload:
        candidate_ranking = str(payload.get("candidate_ranking", "ath")).strip()
    else:
        candidate_ranking = "ath" if payload.get("rank_buy_candidates_by_ath", DEFAULT_CONFIG.rank_buy_candidates_by_ath) else "none"
    if candidate_ranking not in {"none", "ath", "momentum_20_60"}:
        raise ValueError("Unknown candidate ranking mode.")
    rank_buy_candidates_by_ath = candidate_ranking == "ath"
    rotate_to_stronger_candidates = bool(payload.get(
        "rotate_to_stronger_candidates",
        DEFAULT_CONFIG.rotate_to_stronger_candidates,
    ))
    if candidate_ranking == "none":
        rotate_to_stronger_candidates = False
    compound_positions = bool(payload.get("compound_positions", DEFAULT_CONFIG.compound_positions))
    mtf_mode = str(payload.get("mtf_mode", "overflow" if payload.get("buy_all_overflow_signals", False) else "off")).strip()
    if mtf_mode not in {"off", "overflow", "normal"}:
        raise ValueError("Unknown MTF mode.")
    buy_all_overflow_signals = mtf_mode == "overflow"
    extra_capital_limit_multiplier = float(payload.get("extra_capital_limit_multiplier", 1.0) or 0)
    if extra_capital_limit_multiplier < 0:
        raise ValueError("MTF cap multiplier cannot be negative.")
    max_overflow_positions = _parse_optional_nonnegative_int(
        payload.get("max_overflow_positions", 2),
        "Max extra MTF ETFs per signal day",
    )
    extra_capital_interest_rate_daily = float(payload.get("extra_capital_interest_rate_daily", 0) or 0)
    if extra_capital_interest_rate_daily < 0:
        raise ValueError("MTF interest rate cannot be negative.")
    monthly_capital_addition = float(payload.get("monthly_capital_addition", 0) or 0)
    if monthly_capital_addition < 0:
        raise ValueError("Monthly capital addition cannot be negative.")
    withdrawal_target = _parse_optional_positive_float(
        payload.get("withdrawal_target", 0),
        "Withdrawal target",
    )
    monthly_withdrawal_amount = float(payload.get("monthly_withdrawal_amount", 0) or 0)
    if monthly_withdrawal_amount < 0:
        raise ValueError("Monthly withdrawal amount cannot be negative.")
    if withdrawal_target is None and monthly_withdrawal_amount > 0:
        raise ValueError("Withdrawal target is required when monthly withdrawal amount is set.")
    price_time = (
        None
        if strategy_name in {
            "ema_trend",
            "weekly_ema_cross",
            "rsi_50_cross",
            "rsi_divergence_staged",
            "ema_entry_low_sell",
            "ema_atr_confirmed",
            "ema_atr_sell_band",
        }
        else _parse_time(payload.get("price_time", DEFAULT_CONFIG.price_time), "price time")
    )
    signal_sources = _parse_signal_sources(payload.get("signal_sources"), symbols)

    start_date = _parse_date(payload.get("start_date"), "start date")
    end_date = _parse_date(payload.get("end_date"), "end date")
    if start_date > end_date:
        raise ValueError("Start date must be before or equal to end date.")

    return EmaBacktestRequest(
        symbols=symbols,
        initial_capital=initial_capital,
        max_positions=max_positions,
        start_date=start_date,
        end_date=end_date,
        strategy_name=strategy_name,
        ema_window=ema_window,
        atr_window=atr_window,
        atr_multiplier=atr_multiplier,
        confirmation_days=confirmation_days,
        rsi_window=rsi_window,
        candidate_ranking=candidate_ranking,
        rank_buy_candidates_by_ath=rank_buy_candidates_by_ath,
        rotate_to_stronger_candidates=rotate_to_stronger_candidates,
        compound_positions=compound_positions,
        buy_all_overflow_signals=buy_all_overflow_signals,
        mtf_mode=mtf_mode,
        extra_capital_limit_multiplier=extra_capital_limit_multiplier,
        max_overflow_positions=max_overflow_positions,
        extra_capital_interest_rate_daily=extra_capital_interest_rate_daily,
        monthly_capital_addition=monthly_capital_addition,
        withdrawal_target=withdrawal_target,
        monthly_withdrawal_amount=monthly_withdrawal_amount,
        price_time=price_time,
        intraday_interval=DEFAULT_CONFIG.intraday_interval,
        signal_sources=signal_sources,
    )


def _parse_date(value, label: str):
    if not isinstance(value, str):
        raise ValueError(f"Invalid {label}. Use YYYY-MM-DD.")

    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {label}. Use YYYY-MM-DD.") from exc


def _parse_time(value, label: str):
    if value in (None, ""):
        return None

    if not isinstance(value, str):
        raise ValueError(f"Invalid {label}. Use HH:MM.")

    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"Invalid {label}. Use HH:MM.") from exc


def _parse_optional_nonnegative_int(value, label: str) -> int | None:
    if value in (None, "", "all"):
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a whole number.") from exc
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative.")
    return parsed


def _parse_optional_positive_float(value, label: str) -> float | None:
    if value in (None, ""):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative.")
    return parsed if parsed > 0 else None


def _serialize_row(row: dict) -> dict:
    serialized = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    return serialized


def _load_live_state_snapshot() -> dict:
    if not LIVE_STATE_PATH.exists():
        return {"holdings": {}, "trades": [], "completed_trades": [], "capital_adjustments": []}

    with LIVE_STATE_PATH.open(encoding="utf-8") as file:
        state = json.load(file)
    if not isinstance(state, dict):
        raise ValueError(f"Expected live state object in {LIVE_STATE_PATH}")
    state.setdefault("holdings", {})
    state.setdefault("trades", [])
    state.setdefault("completed_trades", [])
    state.setdefault("capital_adjustments", [])
    return state


def _completed_trades_from_state(state: dict) -> list[dict]:
    return [
        *state.get("completed_trades", []),
        *build_completed_trades(state.get("trades", [])),
    ]


def _apply_selected_live_report_actions(selected_action_ids: list[str] | None) -> dict:
    if not LIVE_REPORT_PATH.exists():
        raise ValueError("Generate live signals before applying actions.")

    with LIVE_REPORT_PATH.open(encoding="utf-8") as file:
        report = json.load(file)
    if not isinstance(report, dict):
        raise ValueError(f"Expected live report object in {LIVE_REPORT_PATH}")

    report_actions = [action for action in report.get("actions", []) if isinstance(action, dict)]
    selected_ids = set(selected_action_ids or [str(action.get("id", "")) for action in report_actions])
    selected_actions = [
        action
        for index, action in enumerate(report_actions)
        if (
            str(action.get("id", "")) in selected_ids
            or f"index:{index}" in selected_ids
        ) and str(action.get("side", "")).upper() in {"BUY", "SELL"}
    ]
    if not selected_actions:
        raise ValueError("No selected live actions matched the latest generated report. Generate signals again and retry.")

    config = _load_live_config_snapshot()
    state = load_live_state(LIVE_STATE_PATH, initial_capital=float(config["initial_capital"]))
    _apply_live_actions_to_state(state, selected_actions, config)
    save_live_state(state, LIVE_STATE_PATH)

    report["mode"] = "applied"
    report["actions"] = selected_actions
    report["ledger_trades"] = state.get("trades", [])
    report["completed_trades"] = _completed_trades_from_state(state)
    report["holdings"] = _live_holdings_from_state(state, report.get("holdings", []))
    report["cash"] = float(state.get("cash", config["initial_capital"]))
    report["equity"] = _live_equity(report["cash"], report["holdings"])
    report["capital_adjustments"] = state.get("capital_adjustments", [])
    report["config"] = config
    report["capital_base"] = _capital_base(config, state)
    report["mtf"] = _live_mtf_report(config, report["holdings"], report["cash"])
    report["xirr"] = _live_report_xirr(config, state, report["equity"])
    report["trades_count"] = len(state.get("trades", []))
    save_live_report(report, LIVE_REPORT_PATH)
    return report


def _apply_live_actions_to_state(state: dict, actions: list[dict], config: dict) -> None:
    holdings = state.setdefault("holdings", {})
    trades = state.setdefault("trades", [])
    completed_trades = state.setdefault("completed_trades", [])
    cash = float(state.get("cash", config["initial_capital"]))

    for action in actions:
        symbol = str(action.get("symbol", "")).strip()
        if str(action.get("side", "")).upper() == "SELL" and symbol in holdings:
            holding = holdings[symbol]
            if not _has_open_live_buy(trades, symbol):
                completed_trades.append(_completed_trade_from_holding(symbol, holding, action))
            cash += float(action.get("cash_delta", action.get("value", 0)) or 0)
            holdings.pop(symbol, None)
            trades.append(action)

    for action in actions:
        symbol = str(action.get("symbol", "")).strip()
        if str(action.get("side", "")).upper() == "BUY" and symbol and symbol not in holdings:
            shares = int(float(action.get("shares", 0)))
            price = float(action.get("price", 0))
            value = float(action.get("value", shares * price))
            cash -= float(action.get("cash_required", value) or 0)
            holdings[symbol] = {
                "symbol": symbol,
                "shares": shares,
                "entry_price": price,
                "entry_date": action.get("date") or action.get("signal_date", ""),
                "cost_basis": value,
                "funding_mode": str(action.get("funding_mode", "delivery")).lower(),
                "mtf_loan": float(action.get("mtf_loan", 0) or 0),
            }
            trades.append(action)

    state["cash"] = cash


def _has_open_live_buy(trades: list[dict], symbol: str) -> bool:
    open_buys = 0
    for trade in trades:
        if str(trade.get("symbol", "")).strip() != symbol:
            continue
        side = str(trade.get("side", "")).upper()
        if side == "BUY":
            open_buys += 1
        elif side == "SELL" and open_buys > 0:
            open_buys -= 1
    return open_buys > 0


def _completed_trade_from_holding(symbol: str, holding: dict, sell_action: dict) -> dict:
    shares = int(float(sell_action.get("shares", holding.get("shares", 0)) or 0))
    buy_price = float(holding.get("entry_price", 0) or 0)
    sell_price = float(sell_action.get("price", 0) or 0)
    buy_value = float(holding.get("cost_basis", shares * buy_price) or 0)
    sell_value = float(sell_action.get("value", shares * sell_price) or 0)
    profit = float(sell_action.get("profit", sell_value - buy_value) or 0)
    buy_date = holding.get("entry_date", "")
    sell_date = sell_action.get("signal_date") or sell_action.get("date", "")
    return {
        "symbol": symbol,
        "buy_date": buy_date,
        "sell_date": sell_date,
        "buy_time": holding.get("time", ""),
        "sell_time": sell_action.get("time", ""),
        "buy_price": buy_price,
        "sell_price": sell_price,
        "shares": shares,
        "buy_value": buy_value,
        "sell_value": sell_value,
        "profit": profit,
        "return_pct": (profit / buy_value) if buy_value > 0 else 0.0,
        "holding_days": _holding_days_between(buy_date, sell_date),
        "reason": sell_action.get("reason", ""),
    }


def _holding_days_between(buy_date, sell_date) -> int | None:
    if not buy_date or not sell_date:
        return None
    try:
        return (datetime.fromisoformat(str(sell_date)).date() - datetime.fromisoformat(str(buy_date)).date()).days
    except ValueError:
        return None


def _build_backtest_trade_ledger(trades: list[dict]) -> list[dict]:
    open_buys: dict[str, list[dict]] = {}
    ledger: list[dict] = []

    for trade in trades:
        symbol = trade.get("symbol", "")
        side = str(trade.get("side", "")).upper()
        if side == "BUY":
            open_buys.setdefault(symbol, []).append(trade)
            continue

        if side != "SELL" or not open_buys.get(symbol):
            continue

        buys = open_buys.pop(symbol)
        quantity = int(float(trade.get("shares", 0) or 0))
        if quantity <= 0:
            quantity = int(sum(float(buy.get("shares", 0) or 0) for buy in buys))
        total_invested = sum(
            _trade_value_or_default(buy, int(float(buy.get("shares", 0) or 0)))
            for buy in buys
        )
        total_sold = _trade_value_or_default(trade, quantity)
        realized_profit = float(trade.get("profit", total_sold - total_invested) or 0)
        first_buy = buys[0]
        average_buy_price = total_invested / quantity if quantity > 0 else 0.0
        ledger.append({
            "status": "Closed",
            "symbol": symbol,
            "buy_date": first_buy.get("date", ""),
            "buy_time": first_buy.get("time", ""),
            "buy_price": average_buy_price,
            "quantity": quantity,
            "total_invested": total_invested,
            "sell_date": trade.get("date", ""),
            "sell_time": trade.get("time", ""),
            "sell_price": float(trade.get("price", 0) or 0),
            "total_sold": total_sold,
            "realized_profit": realized_profit,
            "profit_pct": realized_profit / total_invested if total_invested > 0 else 0.0,
            "holding_days": trade.get("holding_days", ""),
            "entry_low": trade.get("entry_low", first_buy.get("entry_low")),
            "entry_ema": trade.get("entry_ema", first_buy.get("entry_ema")),
            "reason": trade.get("reason", ""),
        })

    for symbol, buys in open_buys.items():
        quantity = int(sum(float(buy.get("shares", 0) or 0) for buy in buys))
        total_invested = sum(
            _trade_value_or_default(buy, int(float(buy.get("shares", 0) or 0)))
            for buy in buys
        )
        first_buy = buys[0]
        ledger.append({
            "status": "Open",
            "symbol": symbol,
            "buy_date": first_buy.get("date", ""),
            "buy_time": first_buy.get("time", ""),
            "buy_price": total_invested / quantity if quantity > 0 else 0.0,
            "quantity": quantity,
            "total_invested": total_invested,
            "sell_date": "",
            "sell_time": "",
            "sell_price": None,
            "total_sold": None,
            "realized_profit": None,
            "profit_pct": None,
            "holding_days": "",
            "entry_low": first_buy.get("entry_low"),
            "entry_ema": first_buy.get("entry_ema"),
            "reason": "",
        })

    return ledger


def _trade_value_or_default(trade: dict, quantity: int) -> float:
    try:
        value = float(trade.get("value", 0) or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value > 0:
        return value
    return quantity * float(trade.get("price", 0) or 0)


def _manual_live_report(state: dict, completed_trades: list[dict]) -> dict:
    config = _load_live_config_snapshot()
    holdings = _live_holdings_from_state(state)
    cash = float(state.get("cash", 0))
    equity = _live_equity(cash, holdings)
    return {
        "run_date": "",
        "run_time": "",
        "signal_time": "manual",
        "price_note": "Manual ledger with current market prices",
        "mode": "ledger",
        "config": config,
        "cash": cash,
        "equity": equity,
        "xirr": _live_report_xirr(config, state, equity),
        "capital_base": _capital_base(config=config, state=state),
        "mtf": _live_mtf_report(config, holdings, cash),
        "capital_adjustments": state.get("capital_adjustments", []),
        "actions": [],
        "holdings": holdings,
        "signals": {},
        "trades_count": len(state.get("trades", [])),
        "ledger_trades": state.get("trades", []),
        "completed_trades": completed_trades,
    }


def _live_holdings_from_state(state: dict, existing_holdings: list[dict] | None = None) -> list[dict]:
    existing_by_symbol = {
        row.get("symbol"): row
        for row in (existing_holdings or [])
        if isinstance(row, dict) and row.get("symbol")
    }
    symbols = sorted(state.get("holdings", {}).keys())
    current_prices = _current_prices_by_symbol(symbols)
    holdings = []
    for holding in sorted(state.get("holdings", {}).values(), key=lambda row: row.get("symbol", "")):
        symbol = holding.get("symbol", "")
        existing = existing_by_symbol.get(symbol, {})
        shares = float(holding.get("shares", 0))
        entry_price = float(holding.get("entry_price", 0))
        cost_basis = float(holding.get("cost_basis", shares * entry_price))
        last_price = current_prices.get(symbol, _float_or_default(existing.get("last_price"), entry_price))
        market_value = shares * last_price
        holdings.append({
            "symbol": symbol,
            "shares": shares,
            "entry_price": entry_price,
            "entry_date": holding.get("entry_date", ""),
            "last_price": last_price,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "unrealized_profit": market_value - cost_basis,
            "funding_mode": holding.get("funding_mode", "delivery"),
            "mtf_loan": float(holding.get("mtf_loan", 0) or 0),
            "signal": existing.get("signal", 0),
        })
    return holdings


def _live_equity(cash: float, holdings: list[dict]) -> float:
    market_value = sum(float(row.get("market_value", 0) or 0) for row in holdings)
    mtf_loan = sum(float(row.get("mtf_loan", 0) or 0) for row in holdings)
    return float(cash) + market_value - mtf_loan


def _live_mtf_report(config: dict, holdings: list[dict], cash: float | None = None) -> dict:
    loan_balance = sum(float(row.get("mtf_loan", 0) or 0) for row in holdings)
    delivery_value = sum(
        float(row.get("market_value", 0) or 0)
        for row in holdings
        if str(row.get("funding_mode", "delivery")).lower() != "mtf"
    )
    liquidcase = float(config.get("mtf_pledged_liquidcase_value", 0) or 0)
    haircut = float(config.get("mtf_collateral_haircut_pct", 0) or 0) / 100.0
    multiple = float(config.get("mtf_funded_multiple", 0) or 0)
    collateral = max((liquidcase + delivery_value) * (1 - haircut), 0.0)
    limit = collateral * multiple
    daily_rate = float(config.get("mtf_interest_rate_annual_pct", 0) or 0) / 100.0 / 365.0
    required_cash_buffer = float(config.get("initial_capital", 0) or 0) * float(config.get("mtf_cash_buffer_pct", 0) or 0) / 100.0
    available = max(limit - loan_balance, 0.0)
    if cash is not None and float(cash) < required_cash_buffer:
        available = 0.0
    return {
        "enabled": bool(config.get("mtf_enabled", False)),
        "broker": config.get("mtf_broker", ""),
        "liquidcase": liquidcase,
        "delivery_collateral_value": delivery_value,
        "collateral": collateral,
        "limit": limit,
        "loan_balance": loan_balance,
        "available": available,
        "required_cash_buffer": required_cash_buffer,
        "daily_interest": loan_balance * daily_rate,
        "daily_interest_rate": daily_rate,
    }


def _current_prices_by_symbol(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}

    prices: dict[str, float] = {}
    for quote in fetch_current_prices(symbols):
        if quote.price is not None:
            prices[quote.source_symbol] = float(quote.price)
    return prices


def _float_or_default(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _load_live_config_snapshot() -> dict:
    if not LIVE_CONFIG_PATH.exists():
        return {"initial_capital": DEFAULT_CONFIG.initial_capital}
    with LIVE_CONFIG_PATH.open(encoding="utf-8") as file:
        config = json.load(file)
    if not isinstance(config, dict):
        raise ValueError(f"Expected live config object in {LIVE_CONFIG_PATH}")
    config.setdefault("initial_capital", DEFAULT_CONFIG.initial_capital)
    config.setdefault("max_positions", DEFAULT_CONFIG.max_positions)
    config.setdefault("mtf_enabled", False)
    config.setdefault("mtf_broker", "ICICI Direct Prime 4999")
    config.setdefault("mtf_interest_rate_annual_pct", 9.65)
    config.setdefault("mtf_funded_multiple", 3.0)
    config.setdefault("mtf_collateral_haircut_pct", 6.0)
    config.setdefault("mtf_cash_buffer_pct", 20.0)
    config.setdefault("mtf_pledged_liquidcase_value", 0.0)
    return config


def _save_json(path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def _bounded_float(value, label: str, minimum: float, maximum: float | None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if parsed < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{label} cannot be greater than {maximum}.")
    return parsed


def _normalize_live_holdings(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("holdings must be a list.")

    holdings: list[dict] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Each holding must be an object.")
        symbol = _normalize_live_symbol(row.get("symbol"))
        if symbol in seen:
            raise ValueError(f"Duplicate live holding: {symbol}")
        seen.add(symbol)
        shares = int(float(row.get("shares", 0)))
        entry_price = float(row.get("entry_price", 0))
        entry_date = _date_string(row.get("entry_date"), "holding execution date")
        if shares <= 0 or entry_price <= 0:
            raise ValueError(f"Invalid holding values for {symbol}.")
        cost_basis = _positive_float_or_default(
            row.get("cost_basis") or row.get("invested_value"),
            shares * entry_price,
        )
        funding_mode = str(row.get("funding_mode", "delivery")).strip().lower()
        if funding_mode not in {"delivery", "mtf"}:
            raise ValueError(f"Funding mode must be delivery or mtf for {symbol}.")
        mtf_loan = _bounded_float(row.get("mtf_loan", 0) or 0, f"MTF loan for {symbol}", 0, None)
        holdings.append({
            "symbol": symbol,
            "shares": shares,
            "entry_price": entry_price,
            "entry_date": entry_date,
            "cost_basis": cost_basis,
            "funding_mode": funding_mode,
            "mtf_loan": mtf_loan,
        })
    return holdings


def _normalize_completed_trades(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("completed_trades must be a list.")

    trades: list[dict] = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Each completed trade must be an object.")
        symbol = _normalize_live_symbol(row.get("symbol"))
        shares = int(float(row.get("shares", 0)))
        buy_date = _date_string(row.get("buy_date"), "buy date")
        sell_date = _date_string(row.get("sell_date"), "sell date")
        buy_price = float(row.get("buy_price", 0))
        sell_price = float(row.get("sell_price", 0))
        if shares <= 0 or buy_price <= 0 or sell_price <= 0:
            raise ValueError(f"Invalid completed trade values for {symbol}.")
        buy_value = _positive_float_or_default(row.get("buy_value"), shares * buy_price)
        sell_value = _positive_float_or_default(row.get("sell_value"), shares * sell_price)
        profit = float(row.get("profit") if row.get("profit") not in (None, "") else sell_value - buy_value)
        trades.append({
            "symbol": symbol,
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_time": str(row.get("buy_time", "")),
            "sell_time": str(row.get("sell_time", "")),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "shares": shares,
            "buy_value": buy_value,
            "sell_value": sell_value,
            "profit": profit,
            "return_pct": (profit / buy_value) if buy_value > 0 else 0.0,
            "holding_days": _holding_days_from_strings(buy_date, sell_date),
            "reason": str(row.get("reason", "manual")),
        })
    return trades


def _normalize_live_symbol(value) -> str:
    symbol = str(value or "").strip().upper()
    if symbol not in ETF_UNIVERSE:
        raise ValueError(f"Unknown ETF symbol: {symbol}")
    return symbol


def _date_string(value, label: str) -> str:
    return _parse_date(value, label).isoformat()


def _holding_days_from_strings(buy_date: str, sell_date: str) -> int:
    return (_parse_date(sell_date, "sell date") - _parse_date(buy_date, "buy date")).days


def _positive_float_or_default(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return parsed if parsed > 0 else float(default)


def _cash_from_manual_ledger(config: dict, holdings: list[dict], completed_trades: list[dict]) -> float:
    state = load_live_state(initial_capital=float(config.get("initial_capital", DEFAULT_CONFIG.initial_capital)))
    initial_capital = _capital_base(config, state)
    realized_profit = sum(float(trade.get("profit", 0)) for trade in completed_trades)
    cash_invested = sum(
        float(holding.get("cost_basis", 0)) - float(holding.get("mtf_loan", 0) or 0)
        for holding in holdings
    )
    return initial_capital + realized_profit - cash_invested


def _capital_base(config: dict, state: dict) -> float:
    initial_capital = float(config.get("initial_capital", DEFAULT_CONFIG.initial_capital))
    return initial_capital + sum(
        float(row.get("amount", 0))
        for row in state.get("capital_adjustments", [])
        if isinstance(row, dict)
    )


def _live_report_xirr(config: dict, state: dict, ending_equity: float, ending_date=None) -> float:
    final_date = ending_date or datetime.today().date()
    flows = [
        {
            "date": _flow_date(state.get("created_at"), final_date),
            "amount": -float(config.get("initial_capital", DEFAULT_CONFIG.initial_capital)),
        }
    ]
    for row in state.get("capital_adjustments", []):
        if not isinstance(row, dict):
            continue
        amount = float(row.get("amount", 0) or 0)
        if amount:
            flows.append({"date": _flow_date(row.get("date"), final_date), "amount": -amount})
    flows.append({"date": final_date, "amount": float(ending_equity)})
    return xirr(flows)


def _flow_date(value, fallback):
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return fallback


def _normalize_capital_adjustment(payload: dict) -> dict:
    amount = float(payload.get("amount", 0))
    if amount == 0:
        raise ValueError("Capital adjustment amount cannot be zero.")
    adjustment_date = _date_string(payload.get("date"), "capital adjustment date")
    note = str(payload.get("note", "")).strip()
    return {
        "date": adjustment_date,
        "amount": amount,
        "note": note,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _normalize_capital_adjustments(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("capital_adjustments must be a list.")

    adjustments: list[dict] = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Each capital adjustment must be an object.")
        adjustment = _normalize_capital_adjustment(row)
        created_at = str(row.get("created_at", "")).strip()
        if created_at:
            adjustment["created_at"] = created_at
        adjustments.append(adjustment)
    return adjustments


def _capital_adjustment_total(adjustments: list[dict]) -> float:
    return sum(
        float(row.get("amount", 0))
        for row in adjustments
        if isinstance(row, dict)
    )


def _normalize_signal_source_updates(value) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("signal_sources must be an object.")

    mapping: dict[str, str] = {}
    for etf_symbol, source_symbol in value.items():
        etf = str(etf_symbol or "").strip().upper()
        source = str(source_symbol or "").strip().upper()
        if not etf and not source:
            continue
        if etf not in ETF_UNIVERSE:
            raise ValueError(f"Unknown ETF symbol in mapping: {etf}")
        if not source:
            raise ValueError(f"Signal source is required for {etf}.")
        mapping[etf] = source
    return mapping


def _request_config(backtest_request: EmaBacktestRequest) -> dict:
    return {
        "symbols": backtest_request.symbols,
        "initial_capital": backtest_request.initial_capital,
        "max_positions": backtest_request.max_positions,
        "start_date": backtest_request.start_date.isoformat(),
        "end_date": backtest_request.end_date.isoformat(),
        "strategy": backtest_request.strategy_name,
        "ema_window": backtest_request.ema_window,
        "atr_window": backtest_request.atr_window,
        "atr_multiplier": backtest_request.atr_multiplier,
        "confirmation_days": backtest_request.confirmation_days,
        "rsi_window": backtest_request.rsi_window,
        "candidate_ranking": backtest_request.candidate_ranking,
        "rank_buy_candidates_by_ath": backtest_request.rank_buy_candidates_by_ath,
        "rotate_to_stronger_candidates": backtest_request.rotate_to_stronger_candidates,
        "compound_positions": backtest_request.compound_positions,
        "buy_all_overflow_signals": backtest_request.buy_all_overflow_signals,
        "mtf_mode": backtest_request.mtf_mode,
        "extra_capital_limit_multiplier": backtest_request.extra_capital_limit_multiplier,
        "max_overflow_positions": backtest_request.max_overflow_positions,
        "extra_capital_interest_rate_daily": backtest_request.extra_capital_interest_rate_daily,
        "monthly_capital_addition": backtest_request.monthly_capital_addition,
        "withdrawal_target": backtest_request.withdrawal_target,
        "monthly_withdrawal_amount": backtest_request.monthly_withdrawal_amount,
        "price_time": (
            backtest_request.price_time.isoformat(timespec="minutes")
            if backtest_request.price_time
            else None
        ),
        "intraday_interval": backtest_request.intraday_interval,
        "signal_sources": backtest_request.signal_sources or {},
    }


def _parse_signal_sources(value, selected_symbols: list[str]) -> dict[str, str] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid signal source mapping.")

    selected = set(selected_symbols)
    mapping: dict[str, str] = {}
    for etf_symbol, source_symbol in value.items():
        if etf_symbol not in selected:
            continue
        if source_symbol in (None, ""):
            mapping[etf_symbol] = etf_symbol
        elif isinstance(source_symbol, str):
            mapping[etf_symbol] = source_symbol.strip().upper()
        else:
            raise ValueError("Invalid signal source mapping.")

    return {symbol: mapping.get(symbol, symbol) for symbol in selected_symbols}
