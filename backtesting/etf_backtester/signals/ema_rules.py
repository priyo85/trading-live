"""EMA-based signal rules."""

from datetime import datetime

from backtesting.etf_backtester.indicators.moving_average import exponential_moving_average


def price_above_ema_signal(closes: list[float], window: int = 9) -> list[int]:
    """Return long/cash state from close crossing above or below EMA."""

    ema_values = exponential_moving_average(closes, window)
    signals: list[int] = []
    state = 0

    for close, ema in zip(closes, ema_values):
        if ema is None:
            signals.append(0)
            continue

        if close > ema:
            state = 1
        elif close < ema:
            state = 0
        signals.append(state)

    return signals


def weekly_price_above_ema_signal(
    rows: list[dict],
    window: int = 9,
    confirmation_days: int = 1,
) -> list[int]:
    """Return daily long/cash state from confirmed weekly EMA crosses."""

    weekly_closes: list[float] = []
    weekly_end_indices: list[int] = []
    current_week = None
    previous_index = None

    for index, row in enumerate(rows):
        week = _week_key(row["date"])
        if current_week is None:
            current_week = week
        elif week != current_week and previous_index is not None:
            weekly_closes.append(float(rows[previous_index]["close"]))
            weekly_end_indices.append(previous_index)
            current_week = week
        previous_index = index

    if previous_index is not None:
        weekly_closes.append(float(rows[previous_index]["close"]))
        weekly_end_indices.append(previous_index)

    weekly_states = _confirmed_price_above_ema_signal(weekly_closes, window, confirmation_days)
    signals = [0] * len(rows)
    state = 0
    previous_end = -1

    for end_index, weekly_state in zip(weekly_end_indices, weekly_states):
        for index in range(previous_end + 1, end_index):
            signals[index] = state
        state = weekly_state
        signals[end_index] = state
        previous_end = end_index

    for index in range(previous_end + 1, len(signals)):
        signals[index] = state

    return signals


def _confirmed_price_above_ema_signal(
    closes: list[float],
    window: int,
    confirmation_days: int,
) -> list[int]:
    ema_values = exponential_moving_average(closes, window)
    signals: list[int] = []
    state = 0
    above_count = 0
    below_count = 0
    required_count = max(int(confirmation_days), 1)

    for close, ema in zip(closes, ema_values):
        if ema is None:
            signals.append(0)
            continue

        if close > ema:
            above_count += 1
            below_count = 0
        elif close < ema:
            below_count += 1
            above_count = 0
        else:
            above_count = 0
            below_count = 0

        if state == 0 and above_count >= required_count:
            state = 1
        elif state == 1 and below_count >= required_count:
            state = 0

        signals.append(state)

    return signals


def _week_key(value) -> tuple[int, int]:
    if isinstance(value, str):
        value = datetime.strptime(value, "%Y-%m-%d").date()
    calendar = value.isocalendar()
    return calendar.year, calendar.week
