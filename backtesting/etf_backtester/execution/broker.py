"""Simple execution cost helpers."""


def buy_price(close_price: float, slippage_rate: float) -> float:
    """Apply positive slippage for buys."""

    return close_price * (1 + slippage_rate)


def sell_price(close_price: float, slippage_rate: float) -> float:
    """Apply negative slippage for sells."""

    return close_price * (1 - slippage_rate)


def commission(notional: float, commission_rate: float) -> float:
    """Calculate commission cost from traded notional."""

    return abs(notional) * commission_rate
