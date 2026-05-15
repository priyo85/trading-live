import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backtesting.etf_backtester.data.yahoo_finance import PriceQuote
from backtesting.etf_backtester.indicators.moving_average import exponential_moving_average
from backtesting.etf_backtester.live.signal_runner import run_live_signals


class LiveSignalRunnerTests(unittest.TestCase):
    def test_cmp_mode_keeps_signal_ema_on_daily_series(self):
        symbol = "NSE:HNGSNGBEES"
        start = date(2026, 1, 1)
        rows = [
            {
                "date": start + timedelta(days=index),
                "open": 100 + index,
                "high": 100 + index,
                "low": 100 + index,
                "close": 100 + index,
                "volume": 1000,
            }
            for index in range(10)
        ]
        expected_ema = exponential_moving_average([float(row["close"]) for row in rows], 9)[-1]

        def fake_history(symbols, start_date, end_date, price_time=None, intraday_interval="5m"):
            return {requested: list(rows) for requested in symbols}

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            state_path = root / "state.json"
            report_path = root / "report.json"
            config_path.write_text(
                json.dumps(
                    {
                        "candidate_ranking": "ath",
                        "compound_positions": True,
                        "ema_window": 9,
                        "initial_capital": 100000,
                        "intraday_interval": "5m",
                        "lookback_days": 30,
                        "max_positions": 3,
                        "mtf_enabled": False,
                        "price_mode": "daily_close",
                        "price_time": "15:15",
                        "signal_source_mode": "self",
                        "strategy": "ema_trend",
                        "symbols": [symbol],
                    }
                ),
                encoding="utf-8",
            )

            with patch("backtesting.etf_backtester.live.signal_runner.fetch_historical_prices", side_effect=fake_history):
                with patch(
                    "backtesting.etf_backtester.live.signal_runner.fetch_current_prices",
                    return_value=[PriceQuote(source_symbol=symbol, yahoo_symbol="TEST", price=200.0)],
                ):
                    with patch("backtesting.etf_backtester.live.signal_runner.fetch_max_close_history", return_value={symbol: rows}):
                        run = run_live_signals(
                            config_path=config_path,
                            state_path=state_path,
                            report_path=report_path,
                            run_date=rows[-1]["date"],
                            use_current_price=True,
                        )

        signal_row = run.report["signal_rows"][0]
        self.assertEqual(signal_row["source_price"], rows[-1]["close"])
        self.assertAlmostEqual(signal_row["source_ema"], expected_ema)
        self.assertEqual(signal_row["price"], 200.0)


if __name__ == "__main__":
    unittest.main()
