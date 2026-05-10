from backtesting.etf_backtester.config.etf_universe import (
    ETF_UNIVERSE,
    all_yahoo_symbols,
    load_etf_universe,
    strip_exchange,
    to_yahoo_symbol,
)


def test_default_universe_contains_nse_symbols():
    assert "NSE:GOLDBEES" in ETF_UNIVERSE
    assert "NSE:OILIETF" in ETF_UNIVERSE
    assert len(ETF_UNIVERSE) == 25
    assert load_etf_universe() == ETF_UNIVERSE


def test_symbol_format_helpers():
    assert strip_exchange("NSE:CPSEETF") == "CPSEETF"
    assert to_yahoo_symbol("NSE:CPSEETF") == "CPSEETF.NS"
    assert "GOLDBEES.NS" in all_yahoo_symbols()
