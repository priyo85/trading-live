from datetime import date

from backtesting.etf_backtester.metrics.performance import cagr
from backtesting.etf_backtester.reports.period_returns import build_period_returns, report_frequency


def test_cagr_for_one_year_double():
    curve = [
        {"date": date(2026, 1, 1), "equity": 100},
        {"date": date(2027, 1, 1), "equity": 200},
    ]

    assert round(cagr(curve), 2) == 1.0


def test_report_frequency_switches_to_yearly_after_threshold():
    curve = [
        {"date": date(2024, 1, 1), "equity": 100},
        {"date": date(2026, 1, 2), "equity": 120},
    ]

    assert report_frequency(curve, yearly_threshold_years=2) == "yearly"


def test_period_returns_build_monthly_profit_rows():
    curve = [
        {"date": date(2026, 1, 1), "equity": 100},
        {"date": date(2026, 1, 31), "equity": 110},
        {"date": date(2026, 2, 28), "equity": 121},
    ]

    rows = build_period_returns(curve, "monthly")

    assert rows[0].period == "2026-01"
    assert rows[0].profit == 10
    assert rows[1].period == "2026-02"
    assert rows[1].profit == 11
