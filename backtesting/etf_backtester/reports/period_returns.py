"""Calendar period profit reports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeriodReturn:
    """Profit for one calendar reporting period."""

    period: str
    start_equity: float
    end_equity: float
    profit: float
    return_pct: float


def report_frequency(equity_curve: list[dict], yearly_threshold_years: int) -> str:
    """Return monthly for shorter backtests and yearly for longer backtests."""

    if len(equity_curve) < 2:
        return "monthly"

    days = (equity_curve[-1]["date"] - equity_curve[0]["date"]).days
    return "yearly" if days >= yearly_threshold_years * 365 else "monthly"


def build_period_returns(equity_curve: list[dict], frequency: str) -> list[PeriodReturn]:
    """Build monthly or yearly profit rows from an equity curve."""

    if not equity_curve:
        return []

    period_end_rows: dict[str, dict] = {}
    for row in equity_curve:
        key = _period_key(row["date"], frequency)
        period_end_rows[key] = row

    results: list[PeriodReturn] = []
    previous_equity = float(equity_curve[0]["equity"])

    for period in sorted(period_end_rows):
        end_equity = float(period_end_rows[period]["equity"])
        profit = end_equity - previous_equity
        return_pct = 0.0 if previous_equity == 0 else profit / previous_equity
        results.append(
            PeriodReturn(
                period=period,
                start_equity=previous_equity,
                end_equity=end_equity,
                profit=profit,
                return_pct=return_pct,
            )
        )
        previous_equity = end_equity

    return results


def _period_key(value, frequency: str) -> str:
    if frequency == "yearly":
        return f"{value.year}"
    return f"{value.year}-{value.month:02d}"
