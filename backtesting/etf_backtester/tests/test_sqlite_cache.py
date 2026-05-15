from datetime import date

from backtesting.etf_backtester.data.sqlite_cache import CandleCache


def test_candle_cache_merges_attempted_ranges(tmp_path):
    cache = CandleCache(tmp_path / "market_data.sqlite")
    cache.mark_attempted("provider", "NSE:TEST", "daily_close", date(2026, 1, 1), date(2026, 1, 10))
    cache.mark_attempted("provider", "NSE:TEST", "daily_close", date(2026, 1, 11), date(2026, 1, 20))

    assert cache.missing_ranges("provider", "NSE:TEST", "daily_close", date(2026, 1, 1), date(2026, 1, 25)) == [
        (date(2026, 1, 21), date(2026, 1, 25))
    ]


def test_candle_cache_round_trips_rows(tmp_path):
    cache = CandleCache(tmp_path / "market_data.sqlite")
    cache.save_rows(
        "provider",
        "NSE:TEST",
        "daily_close",
        [
            {
                "date": date(2026, 1, 1),
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": 1000,
            }
        ],
    )

    assert cache.rows("provider", "NSE:TEST", "daily_close", date(2026, 1, 1), date(2026, 1, 1))[0]["close"] == 11.0


def test_candle_cache_metadata_roundtrip(tmp_path):
    cache = CandleCache(tmp_path / "market_data.sqlite")

    cache.set_metadata("max_refresh:TEST", "empty")

    assert cache.get_metadata("max_refresh:TEST") == "empty"
    assert cache.get_metadata("missing") is None
