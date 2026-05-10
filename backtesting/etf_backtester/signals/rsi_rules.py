"""RSI-based signal rules."""

from __future__ import annotations

from backtesting.etf_backtester.indicators.rsi import relative_strength_index


def rsi_cross_signal(closes: list[float], window: int = 14, threshold: float = 50.0) -> list[int]:
    """Return long/cash state when RSI crosses above or below a threshold."""

    rsi_values = relative_strength_index(closes, window)
    signals: list[int] = []
    state = 0
    previous_rsi: float | None = None

    for rsi in rsi_values:
        if rsi is None:
            signals.append(0)
            continue

        if previous_rsi is not None:
            if previous_rsi <= threshold < rsi:
                state = 1
            elif previous_rsi >= threshold > rsi:
                state = 0
        elif rsi > threshold:
            state = 1

        signals.append(state)
        previous_rsi = rsi

    return signals


def rsi_divergence_staged_signal(
    rows: list[dict],
    window: int = 14,
    oversold_threshold: float = 30.0,
    overbought_threshold: float = 70.0,
    divergence_max_rsi: float = 40.0,
    pivot_span: int = 2,
    regular_min_rsi_improvement: float = 3.0,
    double_bottom_low_tolerance: float = 0.001,
    double_bottom_min_rsi_improvement: float = 5.0,
) -> list[int]:
    """Return staged exposure for bullish RSI divergence entries.

    Exposure moves from 0 to 3 in thirds:
    - first third on a confirmed bullish divergence
    - second third on RSI touching/crossing up from 30 after the first third
    - final third on a later confirmed bullish divergence
    - back to 0 when RSI crosses down from 70
    """

    closes = [float(row["close"]) for row in rows]
    highs = [float(row.get("high", row["close"])) for row in rows]
    lows = [float(row.get("low", row["close"])) for row in rows]
    rsi_values = relative_strength_index(closes, window)
    signals: list[int] = []
    state = 0
    rsi_30_entry_done = False
    previous_pivot_low_index: int | None = None
    pending_divergence_pivot_index: int | None = None

    for index, rsi in enumerate(rsi_values):
        if rsi is None:
            signals.append(0)
            continue

        previous_rsi = _previous_rsi(rsi_values, index)
        if (
            previous_rsi is not None
            and previous_rsi >= overbought_threshold
            and rsi < overbought_threshold
        ):
            state = 0
            rsi_30_entry_done = False
            pending_divergence_pivot_index = None
            previous_pivot_low_index = None

        if state == 1 and not rsi_30_entry_done and _is_rsi_30_entry(previous_rsi, rsi, oversold_threshold):
            state += 1
            rsi_30_entry_done = True

        if (
            pending_divergence_pivot_index is not None
            and state in {0, 2}
            and index > pending_divergence_pivot_index
            and closes[index] > highs[pending_divergence_pivot_index]
        ):
            state += 1
            pending_divergence_pivot_index = None

        if index >= pivot_span and _is_pivot_low(lows, index, pivot_span):
            if (
                previous_pivot_low_index is not None
                and state in {0, 2}
                and _is_bullish_divergence(
                    lows,
                    rsi_values,
                    previous_pivot_low_index,
                    index,
                    divergence_max_rsi,
                    regular_min_rsi_improvement,
                    double_bottom_low_tolerance,
                    double_bottom_min_rsi_improvement,
                )
            ):
                pending_divergence_pivot_index = index
            previous_pivot_low_index = index

        signals.append(state)

    return signals


def _previous_rsi(values: list[float | None], index: int) -> float | None:
    for previous_index in range(index - 1, -1, -1):
        value = values[previous_index]
        if value is not None:
            return value
    return None


def _is_rsi_30_entry(previous_rsi: float | None, rsi: float, threshold: float) -> bool:
    if previous_rsi is None:
        return rsi <= threshold
    return (previous_rsi > threshold >= rsi) or (previous_rsi < threshold <= rsi)


def _is_pivot_low(lows: list[float], index: int, span: int) -> bool:
    if index < span:
        return False
    pivot_low = lows[index]
    return all(
        pivot_low <= lows[other_index]
        for other_index in range(index - span, index)
    )


def _is_bullish_divergence(
    lows: list[float],
    rsi_values: list[float | None],
    previous_index: int,
    current_index: int,
    divergence_max_rsi: float,
    regular_min_rsi_improvement: float,
    double_bottom_low_tolerance: float,
    double_bottom_min_rsi_improvement: float,
) -> bool:
    previous_rsi = rsi_values[previous_index]
    current_rsi = rsi_values[current_index]
    if previous_rsi is None or current_rsi is None or current_rsi <= previous_rsi:
        return False
    if current_rsi > divergence_max_rsi:
        return False

    previous_low = lows[previous_index]
    current_low = lows[current_index]
    if previous_low <= 0:
        return False

    rsi_improvement = current_rsi - previous_rsi
    if current_low < previous_low:
        return rsi_improvement >= regular_min_rsi_improvement

    same_low = abs(current_low - previous_low) / previous_low <= double_bottom_low_tolerance
    return same_low and rsi_improvement >= double_bottom_min_rsi_improvement
