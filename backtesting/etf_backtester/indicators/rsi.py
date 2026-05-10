"""Relative strength index indicator."""

from __future__ import annotations


def relative_strength_index(values: list[float], window: int = 14) -> list[float | None]:
    """Return Wilder RSI values with leading None values."""

    if window <= 0:
        raise ValueError("window must be greater than zero")
    if not values:
        return []

    rsi_values: list[float | None] = [None] * len(values)
    if len(values) <= window:
        return rsi_values

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, window + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains) / window
    average_loss = sum(losses) / window
    rsi_values[window] = _rsi_from_averages(average_gain, average_loss)

    for index in range(window + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        average_gain = ((average_gain * (window - 1)) + gain) / window
        average_loss = ((average_loss * (window - 1)) + loss) / window
        rsi_values[index] = _rsi_from_averages(average_gain, average_loss)

    return rsi_values


def _rsi_from_averages(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))
