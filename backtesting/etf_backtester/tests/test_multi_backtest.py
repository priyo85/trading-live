from datetime import date, timedelta

from backtesting.etf_backtester.config.settings import BacktestConfig
from backtesting.etf_backtester.portfolio.multi_backtest import run_multi_etf_backtest


def test_multi_etf_backtest_respects_max_positions():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(5)]
    histories = {
        "NSE:AAA": [_row(day, 100 + index) for index, day in enumerate(dates)],
        "NSE:BBB": [_row(day, 200 + index) for index, day in enumerate(dates)],
    }
    signals = {
        "NSE:AAA": [1, 1, 1, 1, 1],
        "NSE:BBB": [1, 1, 1, 1, 1],
    }

    result = run_multi_etf_backtest(histories, signals, BacktestConfig(), max_positions=1)

    assert result.equity_curve
    assert max(row["positions"] for row in result.equity_curve) == 1
    assert len([trade for trade in result.trades if trade["side"] == "BUY"]) == 1


def test_multi_etf_backtest_uses_union_of_available_dates():
    first_dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(3)]
    later_dates = [date(2026, 1, 3) + timedelta(days=offset) for offset in range(3)]
    histories = {
        "NSE:OLDER": [_row(day, 100 + index) for index, day in enumerate(first_dates)],
        "NSE:NEWER": [_row(day, 200 + index) for index, day in enumerate(later_dates)],
    }
    signals = {
        "NSE:OLDER": [0, 1, 1],
        "NSE:NEWER": [0, 1, 1],
    }

    result = run_multi_etf_backtest(histories, signals, BacktestConfig(), max_positions=2)

    assert result.equity_curve[0]["date"] == date(2026, 1, 1)
    assert result.equity_curve[-1]["date"] == date(2026, 1, 5)


def test_multi_etf_backtest_skips_completely_unavailable_symbols():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(3)]
    histories = {
        "NSE:AVAILABLE": [_row(day, 100 + index) for index, day in enumerate(dates)],
        "NSE:UNAVAILABLE": [],
    }
    signals = {
        "NSE:AVAILABLE": [0, 1, 1],
    }

    result = run_multi_etf_backtest(histories, signals, BacktestConfig(), max_positions=2)

    assert result.equity_curve[0]["date"] == date(2026, 1, 1)
    assert result.skipped_symbols == ["NSE:UNAVAILABLE"]


def test_multi_etf_backtest_adds_later_symbols_when_their_data_starts():
    older_dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(5)]
    newer_dates = [date(2026, 1, 4) + timedelta(days=offset) for offset in range(4)]
    histories = {
        "NSE:OLDER": [_row(day, 100 + index) for index, day in enumerate(older_dates)],
        "NSE:NEWER": [_row(day, 200 + index) for index, day in enumerate(newer_dates)],
    }
    signals = {
        "NSE:OLDER": [0, 0, 0, 0, 0],
        "NSE:NEWER": [0, 1, 1, 1],
    }

    result = run_multi_etf_backtest(histories, signals, BacktestConfig(), max_positions=2)

    assert result.equity_curve[0]["date"] == date(2026, 1, 1)
    assert any(trade["symbol"] == "NSE:NEWER" and trade["side"] == "BUY" for trade in result.trades)


def test_multi_etf_backtest_can_rank_buy_candidates_by_ath_proximity():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(3)]
    histories = {
        "NSE:FAR": [
            _row(dates[0], 100),
            _row(dates[1], 80),
            _row(dates[2], 90),
        ],
        "NSE:CLOSE": [
            _row(dates[0], 100),
            _row(dates[1], 98),
            _row(dates[2], 99),
        ],
    }
    signals = {
        "NSE:FAR": [0, 0, 1],
        "NSE:CLOSE": [0, 0, 1],
    }

    result = run_multi_etf_backtest(
        histories,
        signals,
        BacktestConfig(),
        max_positions=1,
        rank_buy_candidates_by_ath=True,
    )

    buy_trades = [trade for trade in result.trades if trade["side"] == "BUY"]
    assert buy_trades[0]["symbol"] == "NSE:CLOSE"


def test_multi_etf_backtest_can_rotate_to_stronger_ath_candidate():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(4)]
    histories = {
        "NSE:WEAK": [
            _row(dates[0], 100),
            _row(dates[1], 100),
            _row(dates[2], 80),
            _row(dates[3], 80),
        ],
        "NSE:STRONG": [
            _row(dates[0], 100),
            _row(dates[1], 100),
            _row(dates[2], 99),
            _row(dates[3], 100),
        ],
    }
    signals = {
        "NSE:WEAK": [1, 1, 1, 1],
        "NSE:STRONG": [0, 0, 1, 1],
    }

    result = run_multi_etf_backtest(
        histories,
        signals,
        BacktestConfig(),
        max_positions=1,
        candidate_ranking="ath",
        rotate_to_stronger_candidates=True,
    )

    trades = [(trade["side"], trade["symbol"], trade.get("reason", "")) for trade in result.trades]
    assert ("SELL", "NSE:WEAK", "rotation") in trades
    assert trades[-1][0:2] == ("BUY", "NSE:STRONG")


def test_multi_etf_backtest_can_disable_compounding_for_fixed_slot_sizing():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(2)]
    histories = {
        "NSE:AAA": [_row(day, 100) for day in dates],
    }
    signals = {
        "NSE:AAA": [1, 1],
    }

    result = run_multi_etf_backtest(
        histories,
        signals,
        BacktestConfig(initial_capital=100000),
        max_positions=2,
        compound_positions=False,
    )

    assert result.open_positions[0]["cost_basis"] == 50000


def test_multi_etf_backtest_can_add_position_in_entry_parts():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(4)]
    histories = {
        "NSE:AAA": [_row(day, 100) for day in dates],
    }
    signals = {
        "NSE:AAA": [0, 1, 2, 3],
    }

    result = run_multi_etf_backtest(
        histories,
        signals,
        BacktestConfig(initial_capital=90000, commission_rate=0, slippage_rate=0),
        max_positions=1,
        compound_positions=False,
        entry_parts=3,
    )

    buy_trades = [trade for trade in result.trades if trade["side"] == "BUY"]
    assert len(buy_trades) == 3
    assert [trade["value"] for trade in buy_trades] == [30000, 30000, 30000]
    assert result.open_positions[0]["cost_basis"] == 90000


def test_multi_etf_backtest_sells_all_entry_parts_together():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(5)]
    histories = {
        "NSE:AAA": [_row(day, 100) for day in dates],
    }
    signals = {
        "NSE:AAA": [0, 1, 2, 3, 0],
    }

    result = run_multi_etf_backtest(
        histories,
        signals,
        BacktestConfig(initial_capital=90000, commission_rate=0, slippage_rate=0),
        max_positions=1,
        compound_positions=False,
        entry_parts=3,
    )

    sell_trades = [trade for trade in result.trades if trade["side"] == "SELL"]
    assert len(sell_trades) == 1
    assert sell_trades[0]["shares"] == 900
    assert not result.open_positions


def test_multi_etf_backtest_supports_weighted_entry_parts():
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(4)]
    histories = {
        "NSE:AAA": [_row(day, 100) for day in dates],
    }
    signals = {
        "NSE:AAA": [0, 1, 2, 3],
    }

    result = run_multi_etf_backtest(
        histories,
        signals,
        BacktestConfig(initial_capital=100000, commission_rate=0, slippage_rate=0),
        max_positions=1,
        compound_positions=False,
        entry_parts=3,
        entry_part_weights=[0.5, 0.25, 0.25],
    )

    buy_trades = [trade for trade in result.trades if trade["side"] == "BUY"]
    assert [trade["value"] for trade in buy_trades] == [50000, 25000, 25000]


def _row(day: date, close: float) -> dict:
    return {
        "date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 0,
    }
