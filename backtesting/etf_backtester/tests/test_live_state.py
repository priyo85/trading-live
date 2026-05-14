import unittest

from backtesting.etf_backtester.live.state import reconcile_empty_holdings_cash


class LiveStateTests(unittest.TestCase):
    def test_reconcile_empty_holdings_cash_resets_stale_negative_cash(self):
        state = {"cash": -503990.13, "holdings": {}, "trades": []}

        changed = reconcile_empty_holdings_cash(state, 500000)

        self.assertTrue(changed)
        self.assertEqual(state["cash"], 500000)

    def test_reconcile_empty_holdings_cash_keeps_completed_profit(self):
        state = {
            "cash": 1000,
            "holdings": {},
            "trades": [
                {
                    "side": "BUY",
                    "symbol": "NSE:ABC",
                    "shares": 10,
                    "price": 100,
                    "value": 1000,
                    "signal_date": "2026-01-01",
                },
                {
                    "side": "SELL",
                    "symbol": "NSE:ABC",
                    "shares": 10,
                    "price": 110,
                    "value": 1100,
                    "profit": 100,
                    "signal_date": "2026-01-10",
                },
            ],
        }

        changed = reconcile_empty_holdings_cash(state, 500000)

        self.assertTrue(changed)
        self.assertEqual(state["cash"], 500100)
