from datetime import time

from backtesting.etf_backtester.data.icici_breeze import IciciBreezeProvider, _breeze_interval


def test_breeze_interval_uses_daily_when_no_price_time():
    assert _breeze_interval(None, "5m") == "1day"


def test_breeze_interval_maps_supported_intraday_values():
    assert _breeze_interval(time(15, 15), "5m") == "5minute"
    assert _breeze_interval(time(15, 15), "30m") == "30minute"


def test_breeze_interval_rejects_unsupported_intraday_values():
    try:
        _breeze_interval(time(15, 15), "15m")
    except ValueError:
        return
    raise AssertionError("Expected unsupported ICICI Breeze interval to raise ValueError")


def test_icici_provider_supports_configured_index_alias():
    provider = IciciBreezeProvider(client=None, aliases={"NSE:NIFTY_AUTO": "CNXAUTO"})

    assert provider.supports_symbol("NSE:NIFTY_AUTO")
    assert provider.stock_code("NSE:NIFTY_AUTO") == "CNXAUTO"


def test_icici_provider_reads_structured_alias_details():
    provider = IciciBreezeProvider(
        client=None,
        aliases={
            "NSE:NIFTY_INFRA": {
                "stock_code": "CNXINF",
                "exchange_code": "NSE",
                "product_type": "cash",
            }
        },
    )

    instrument = provider.instrument("NSE:NIFTY_INFRA")

    assert instrument is not None
    assert instrument.stock_code == "CNXINF"
    assert instrument.exchange_code == "NSE"
