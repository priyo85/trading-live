"""Default settings for ETF swing strategy backtests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backtesting.etf_backtester.config.json_loader import load_json_config


SETTINGS_PATH = Path(__file__).with_suffix(".json")


def load_settings(path: str | Path = SETTINGS_PATH) -> dict:
    """Load project settings from JSON."""

    return load_json_config(path)


_SETTINGS = load_settings()
_BACKTEST_SETTINGS = _SETTINGS["backtest"]
WEB_UI_SETTINGS = _SETTINGS["web_ui"]
STRATEGY_SETTINGS = _SETTINGS["strategies"]


@dataclass(frozen=True)
class BacktestConfig:
    """Execution and portfolio assumptions for a single backtest run."""

    initial_capital: float = float(_BACKTEST_SETTINGS["initial_capital"])
    commission_rate: float = float(_BACKTEST_SETTINGS["commission_rate"])
    slippage_rate: float = float(_BACKTEST_SETTINGS["slippage_rate"])
    position_fraction: float = float(_BACKTEST_SETTINGS["position_fraction"])
    max_positions: int = int(_BACKTEST_SETTINGS["max_positions"])
    default_start_date: str = str(_BACKTEST_SETTINGS["default_start_date"])
    rank_buy_candidates_by_ath: bool = bool(_BACKTEST_SETTINGS["rank_buy_candidates_by_ath"])
    price_time: str = str(_BACKTEST_SETTINGS["price_time"])
    intraday_interval: str = str(_BACKTEST_SETTINGS["intraday_interval"])
    yearly_report_threshold_years: int = int(_BACKTEST_SETTINGS["yearly_report_threshold_years"])
    rotate_to_stronger_candidates: bool = bool(_BACKTEST_SETTINGS["rotate_to_stronger_candidates"])
    compound_positions: bool = bool(_BACKTEST_SETTINGS["compound_positions"])


DEFAULT_CONFIG = BacktestConfig()
