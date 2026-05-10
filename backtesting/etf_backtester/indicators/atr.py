"""Average true range indicator."""

from __future__ import annotations


def average_true_range(rows: list[dict], window: int = 14) -> list[float | None]:
    """Return Wilder ATR values with leading None values."""

    if window <= 0:
        raise ValueError("window must be greater than zero")
    if not rows:
        return []

    true_ranges: list[float] = []
    previous_close: float | None = None
    for row in rows:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(true_range)
        previous_close = close

    atr_values: list[float | None] = [None] * len(rows)
    if len(true_ranges) < window:
        return atr_values

    average_range = sum(true_ranges[:window]) / window
    atr_values[window - 1] = average_range
    for index in range(window, len(true_ranges)):
        average_range = ((average_range * (window - 1)) + true_ranges[index]) / window
        atr_values[index] = average_range

    return atr_values
