from datetime import date

from backtesting.etf_backtester.data.yahoo_finance import PriceQuote, _should_retry_stale_trailing_daily_rows, format_price_table


def test_format_price_table_includes_quote_values():
    table = format_price_table(
        [
            PriceQuote(
                source_symbol="NSE:GOLDBEES",
                yahoo_symbol="GOLDBEES.NS",
                price=100.5,
                currency="INR",
            )
        ]
    )

    assert "NSE:GOLDBEES" in table
    assert "GOLDBEES.NS" in table
    assert "100.50" in table


def test_daily_cache_retries_when_attempted_range_covers_stale_tail():
    rows = [{"date": date(2026, 5, 4), "close": 100.0}]

    assert _should_retry_stale_trailing_daily_rows(rows, date(2026, 5, 10), None)


def test_daily_cache_does_not_retry_when_latest_weekday_is_present():
    rows = [{"date": date(2026, 5, 8), "close": 100.0}]

    assert not _should_retry_stale_trailing_daily_rows(rows, date(2026, 5, 10), None)
