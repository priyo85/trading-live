"""EMA and ATR confirmation signal rules."""

from __future__ import annotations

from backtesting.etf_backtester.indicators.atr import average_true_range
from backtesting.etf_backtester.indicators.moving_average import exponential_moving_average


def ema_atr_confirmed_signal(
    rows: list[dict],
    ema_window: int = 9,
    atr_window: int = 14,
    atr_multiplier: float = 0.25,
    confirmation_days: int = 2,
) -> list[int]:
    """Return long/cash signals using rising EMA, confirmation, and ATR bands."""

    closes = [float(row["close"]) for row in rows]
    ema_values = exponential_moving_average(closes, ema_window)
    atr_values = average_true_range(rows, atr_window)
    signals: list[int] = []
    state = 0
    confirmation_count = 0

    for index, close in enumerate(closes):
        ema = ema_values[index]
        atr = atr_values[index]
        previous_ema = ema_values[index - 1] if index > 0 else None
        if ema is None or atr is None or previous_ema is None:
            signals.append(0)
            continue

        ema_rising = ema > previous_ema
        above_buy_band = close > ema + (atr_multiplier * atr)
        below_sell_band = close < ema - (atr_multiplier * atr)

        if ema_rising and above_buy_band:
            confirmation_count += 1
        else:
            confirmation_count = 0

        if state == 0 and confirmation_count >= confirmation_days:
            state = 1
        elif state == 1 and below_sell_band:
            state = 0
            confirmation_count = 0

        signals.append(state)

    return signals


def ema_atr_sell_band_signal(
    rows: list[dict],
    ema_window: int = 9,
    atr_window: int = 14,
    atr_multiplier: float = 0.25,
) -> list[int]:
    """Return EMA trend signals with ATR band applied only to sells."""

    closes = [float(row["close"]) for row in rows]
    ema_values = exponential_moving_average(closes, ema_window)
    atr_values = average_true_range(rows, atr_window)
    signals: list[int] = []
    state = 0

    for index, close in enumerate(closes):
        ema = ema_values[index]
        atr = atr_values[index]
        if ema is None or atr is None:
            signals.append(0)
            continue

        sell_band = ema - (atr_multiplier * atr)

        if state == 0 and close > ema:
            state = 1
        elif state == 1 and close < sell_band:
            state = 0

        signals.append(state)

    return signals
