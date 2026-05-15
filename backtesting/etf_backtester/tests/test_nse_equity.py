from datetime import date

from backtesting.etf_backtester.data.nse_equity import _rows_from_payload


def test_rows_from_nse_security_archive_payload():
    rows = _rows_from_payload(
        {
            "data": [
                {
                    "_CH_SYMBOL": "HNGSNGBEES",
                    "_CH_SERIES": "EQ",
                    "_CH_TIMESTAMP": "15-May-2026",
                    "_CH_OPENING_PRICE": "565.98",
                    "_CH_TRADE_HIGH_PRICE": "565.98",
                    "_CH_TRADE_LOW_PRICE": "536.50",
                    "_CH_CLOSING_PRICE": "537.84",
                    "_CH_TOT_TRADED_QTY": "1,23,456",
                },
                {
                    "_CH_SYMBOL": "HNGSNGBEES",
                    "_CH_SERIES": "BE",
                    "_CH_TIMESTAMP": "15-May-2026",
                    "_CH_CLOSING_PRICE": "999.00",
                },
            ]
        }
    )

    assert rows == [
        {
            "date": date(2026, 5, 15),
            "open": 565.98,
            "high": 565.98,
            "low": 536.5,
            "close": 537.84,
            "volume": 123456.0,
        }
    ]


def test_rows_from_nse_security_archive_csv_payload():
    rows = _rows_from_payload(
        [
            {
                "SYMBOL": "HNGSNGBEES",
                " SERIES": "EQ",
                " DATE1": "15-May-2026",
                " OPEN_PRICE": "565.98",
                " HIGH_PRICE": "565.98",
                " LOW_PRICE": "536.50",
                " CLOSE_PRICE": "537.84",
                " TTL_TRD_QNTY": "123456",
            }
        ]
    )

    assert rows[0]["date"] == date(2026, 5, 15)
    assert rows[0]["close"] == 537.84
