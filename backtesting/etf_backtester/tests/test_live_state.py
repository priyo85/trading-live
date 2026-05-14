import unittest

from backtesting.etf_backtester.live.state import reconcile_empty_holdings_cash, reconcile_strategy_cash


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

    def test_reconcile_strategy_cash_uses_mtf_margin_not_full_value(self):
        state = {
            "cash": 0,
            "holdings": {
                "NSE:HNGSNGBEES": {
                    "shares": 185,
                    "entry_price": 539.88,
                    "cost_basis": 99877.80,
                    "mtf_loan": 75557.56,
                }
            },
            "trades": [],
        }

        changed = reconcile_strategy_cash(state, 500000)

        self.assertTrue(changed)
        self.assertAlmostEqual(state["cash"], 475679.76, places=2)
