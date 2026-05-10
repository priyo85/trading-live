from backtesting.etf_backtester.indicators.moving_average import exponential_moving_average
from datetime import date, timedelta

from backtesting.etf_backtester.signals.ema_atr_rules import ema_atr_confirmed_signal, ema_atr_sell_band_signal
from backtesting.etf_backtester.signals.rsi_rules import rsi_cross_signal
from backtesting.etf_backtester.strategies.ema_trend import EmaTrendStrategy
from backtesting.etf_backtester.strategies.weekly_ema_cross import WeeklyEmaCrossStrategy


def test_exponential_moving_average_has_leading_none_values():
    values = [10, 11, 12, 13, 14]

    ema = exponential_moving_average(values, 3)

    assert ema[0] is None
    assert ema[1] is None
    assert ema[2] == 11
    assert len(ema) == len(values)


def test_ema_strategy_returns_one_signal_per_row():
    rows = [{"close": close} for close in [10, 11, 12, 13, 12, 11]]

    signals = EmaTrendStrategy(window=3).generate_signals(rows)

    assert len(signals) == len(rows)
    assert set(signals) <= {0, 1}


def test_weekly_ema_cross_strategy_returns_one_signal_per_daily_row():
    start = date(2026, 1, 5)
    closes = [
        10, 10, 10, 10, 10,
        11, 11, 11, 11, 11,
        12, 12, 12, 12, 12,
        13, 13, 13, 13, 13,
        12, 12, 12, 12, 12,
    ]
    rows = [
        {"date": start + timedelta(days=index), "close": close}
        for index, close in enumerate(closes)
    ]

    signals = WeeklyEmaCrossStrategy(window=3).generate_signals(rows)

    assert len(signals) == len(rows)
    assert set(signals) <= {0, 1}
    assert signals[0] == 0


def test_weekly_ema_cross_confirmation_waits_for_requested_weekly_candles():
    start = date(2026, 1, 5)
    rows = [
        {"date": start + timedelta(days=7 * index), "close": close}
        for index, close in enumerate([10, 11, 12, 13, 14, 15])
    ]

    two_candle_signals = WeeklyEmaCrossStrategy(window=3, confirmation_days=2).generate_signals(rows)
    three_candle_signals = WeeklyEmaCrossStrategy(window=3, confirmation_days=3).generate_signals(rows)

    assert two_candle_signals[3] == 1
    assert three_candle_signals[3] == 0
    assert three_candle_signals[4] == 1


def test_rsi_cross_signal_returns_one_signal_per_close():
    closes = [10, 9, 8, 9, 10, 11, 10, 9, 8, 9, 10]

    signals = rsi_cross_signal(closes, window=3, threshold=50)

    assert len(signals) == len(closes)
    assert set(signals) <= {0, 1}


def test_ema_atr_confirmed_signal_returns_one_signal_per_row():
    rows = [
        {"high": close + 1, "low": close - 1, "close": close}
        for close in [10, 11, 12, 13, 14, 15, 16, 15, 14, 13]
    ]

    signals = ema_atr_confirmed_signal(rows, ema_window=3, atr_window=3, confirmation_days=2)

    assert len(signals) == len(rows)
    assert set(signals) <= {0, 1}


def test_ema_atr_sell_band_signal_returns_one_signal_per_row():
    rows = [
        {"high": close + 1, "low": close - 1, "close": close}
        for close in [10, 11, 12, 13, 14, 15, 16, 15, 14, 13]
    ]

    signals = ema_atr_sell_band_signal(rows, ema_window=3, atr_window=3)

    assert len(signals) == len(rows)
    assert set(signals) <= {0, 1}
