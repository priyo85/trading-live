"""Core performance calculations."""

from __future__ import annotations


def xirr(cash_flows: list[dict]) -> float:
    """Return annualized money-weighted return for dated cash flows."""

    flows = _normalized_cash_flows(cash_flows)
    if len(flows) < 2:
        return 0.0
    if not any(amount < 0 for _, amount in flows) or not any(amount > 0 for _, amount in flows):
        return 0.0

    low = -0.999999999
    high = 1.0
    low_value = _xnpv(low, flows)
    high_value = _xnpv(high, flows)
    expansion_count = 0
    while low_value * high_value > 0 and expansion_count < 80:
        high *= 2
        high_value = _xnpv(high, flows)
        expansion_count += 1

    if low_value * high_value > 0:
        return 0.0

    for _ in range(120):
        mid = (low + high) / 2
        mid_value = _xnpv(mid, flows)
        if abs(mid_value) < 1e-7:
            return mid
        if low_value * mid_value <= 0:
            high = mid
            high_value = mid_value
        else:
            low = mid
            low_value = mid_value
    return (low + high) / 2


def cagr(equity_curve: list[dict]) -> float:
    """Return compound annual growth rate as a decimal."""

    if len(equity_curve) < 2:
        return 0.0

    start = float(equity_curve[0]["equity"])
    end = float(equity_curve[-1]["equity"])
    start_date = equity_curve[0]["date"]
    end_date = equity_curve[-1]["date"]
    days = (end_date - start_date).days

    if start <= 0 or days <= 0:
        return 0.0
    if end <= 0:
        return -1.0

    return (end / start) ** (365.25 / days) - 1


def total_return(equity_curve: list[dict]) -> float:
    """Return total strategy return as a decimal."""

    if len(equity_curve) < 2:
        return 0.0

    start = float(equity_curve[0]["equity"])
    end = float(equity_curve[-1]["equity"])
    if start == 0:
        return 0.0
    return (end / start) - 1


def max_drawdown(equity_curve: list[dict]) -> float:
    """Return maximum drawdown as a negative decimal."""

    peak = None
    worst = 0.0

    for row in equity_curve:
        equity = float(row["equity"])
        peak = equity if peak is None else max(peak, equity)
        if peak:
            worst = min(worst, (equity / peak) - 1)

    return worst


def _normalized_cash_flows(cash_flows: list[dict]) -> list[tuple[object, float]]:
    flows = []
    for flow in cash_flows:
        try:
            amount = float(flow.get("amount", 0))
        except (TypeError, ValueError):
            continue
        flow_date = flow.get("date")
        if flow_date is None or amount == 0:
            continue
        flows.append((flow_date, amount))
    return sorted(flows, key=lambda item: item[0])


def _xnpv(rate: float, flows: list[tuple[object, float]]) -> float:
    first_date = flows[0][0]
    total = 0.0
    for flow_date, amount in flows:
        days = (flow_date - first_date).days
        total += amount / ((1 + rate) ** (days / 365.25))
    return total
