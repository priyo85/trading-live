import unittest
from datetime import date

from backtesting.market_data.dhanhq import _historical_rows_from_response


class DhanMarketDataTests(unittest.TestCase):
    def test_historical_rows_from_response(self):
        rows = _historical_rows_from_response(
            {
                "timestamp": [1767148200],
                "open": [10],
                "high": [12],
                "low": [9],
                "close": [11],
                "volume": [1000],
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertIsInstance(rows[0]["date"], date)
        self.assertEqual(rows[0]["close"], 11.0)
        self.assertEqual(rows[0]["volume"], 1000.0)


if __name__ == "__main__":
    unittest.main()
