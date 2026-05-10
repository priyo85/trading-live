"""Moving average indicators."""


def simple_moving_average(values: list[float], window: int) -> list[float | None]:
    """Return a simple moving average series with leading None values."""

    if window <= 0:
        raise ValueError("window must be greater than zero")

    averages: list[float | None] = []
    rolling_sum = 0.0

    for index, value in enumerate(values):
        rolling_sum += value
        if index >= window:
            rolling_sum -= values[index - window]

        if index + 1 < window:
            averages.append(None)
        else:
            averages.append(rolling_sum / window)

    return averages


def exponential_moving_average(values: list[float], window: int) -> list[float | None]:
    """Return an exponential moving average series with leading None values."""

    if window <= 0:
        raise ValueError("window must be greater than zero")

    if not values:
        return []

    multiplier = 2 / (window + 1)
    averages: list[float | None] = []
    ema: float | None = None

    for index, value in enumerate(values):
        if index + 1 < window:
            averages.append(None)
            continue

        if index + 1 == window:
            ema = sum(values[:window]) / window
        elif ema is not None:
            ema = (value - ema) * multiplier + ema

        averages.append(ema)

    return averages
