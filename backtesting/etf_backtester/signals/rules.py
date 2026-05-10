"""Reusable signal rules."""

from backtesting.etf_backtester.indicators.moving_average import simple_moving_average


def moving_average_regime(
    closes: list[float],
    fast_window: int = 20,
    slow_window: int = 50,
) -> list[int]:
    """Return 1 when the fast average is above the slow average, otherwise 0."""

    if fast_window >= slow_window:
        raise ValueError("fast_window must be smaller than slow_window")

    fast = simple_moving_average(closes, fast_window)
    slow = simple_moving_average(closes, slow_window)

    signals: list[int] = []
    for fast_value, slow_value in zip(fast, slow):
        if fast_value is None or slow_value is None:
            signals.append(0)
        else:
            signals.append(1 if fast_value > slow_value else 0)

    return signals
