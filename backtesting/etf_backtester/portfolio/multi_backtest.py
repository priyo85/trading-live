"""Multi-ETF long-only portfolio simulator."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from backtesting.etf_backtester.config.settings import BacktestConfig
from backtesting.etf_backtester.execution.broker import buy_price, commission, sell_price
from backtesting.etf_backtester.indicators.moving_average import exponential_moving_average


@dataclass(frozen=True)
class MultiBacktestResult:
    """Backtest output for a multi-ETF strategy run."""

    equity_curve: list[dict]
    trades: list[dict]
    skipped_symbols: list[str]
    realized_profit: float
    unrealized_profit: float
    open_positions: list[dict]
    per_symbol_report: list[dict]
    capital_flows: list[dict]
    total_capital_added: float
    total_capital_withdrawn: float
    total_extra_capital: float
    max_extra_capital_used: float
    extra_capital_balance: float
    total_extra_capital_interest: float


def run_multi_etf_backtest(
    histories: dict[str, list[dict]],
    signals_by_symbol: dict[str, list[int]],
    config: BacktestConfig,
    max_positions: int,
    rank_buy_candidates_by_ath: bool = False,
    candidate_ranking: str | None = None,
    rotate_to_stronger_candidates: bool = False,
    compound_positions: bool = True,
    sell_price_rule: str = "close",
    sell_rule_ema_window: int = 9,
    ranking_histories: dict[str, list[dict]] | None = None,
    ranking_sources: dict[str, str] | None = None,
    buy_all_overflow_signals: bool = False,
    mtf_mode: str | None = None,
    extra_capital_limit_multiplier: float = 3.0,
    max_overflow_positions: int | None = None,
    extra_capital_interest_rate_daily: float = 0.0,
    monthly_capital_addition: float = 0.0,
    withdrawal_target: float | None = None,
    monthly_withdrawal_amount: float = 0.0,
    entry_parts: int = 1,
    entry_part_weights: list[float] | None = None,
) -> MultiBacktestResult:
    """Run an equal-slot long-only backtest across multiple ETFs."""

    if max_positions <= 0:
        raise ValueError("max_positions must be greater than zero")
    if extra_capital_limit_multiplier < 0:
        raise ValueError("extra_capital_limit_multiplier cannot be negative")
    if max_overflow_positions is not None and max_overflow_positions < 0:
        raise ValueError("max_overflow_positions cannot be negative")
    if extra_capital_interest_rate_daily < 0:
        raise ValueError("extra_capital_interest_rate_daily cannot be negative")
    if monthly_capital_addition < 0:
        raise ValueError("monthly_capital_addition cannot be negative")
    if withdrawal_target is not None and withdrawal_target <= 0:
        raise ValueError("withdrawal_target must be greater than zero")
    if monthly_withdrawal_amount < 0:
        raise ValueError("monthly_withdrawal_amount cannot be negative")
    if entry_parts <= 0:
        raise ValueError("entry_parts must be greater than zero")
    entry_part_weights = _normalize_entry_part_weights(entry_parts, entry_part_weights)
    mtf_mode = mtf_mode or ("overflow" if buy_all_overflow_signals else "off")
    if mtf_mode not in {"off", "overflow", "normal"}:
        raise ValueError("mtf_mode must be one of off, overflow, normal")
    buy_all_overflow_signals = mtf_mode == "overflow" and buy_all_overflow_signals

    usable_symbols = [
        symbol
        for symbol, rows in histories.items()
        if rows and symbol in signals_by_symbol and len(rows) == len(signals_by_symbol[symbol])
    ]
    skipped_symbols = sorted(set(histories) - set(usable_symbols))
    if not usable_symbols:
        raise ValueError("No selected ETFs had enough historical data to backtest")

    rows_by_date = {
        symbol: {row["date"]: row for row in histories[symbol]}
        for symbol in usable_symbols
    }
    ranking_histories = ranking_histories or histories
    ranking_sources = ranking_sources or {symbol: symbol for symbol in usable_symbols}
    ranking_rows_by_date = {
        symbol: {row["date"]: row for row in rows}
        for symbol, rows in ranking_histories.items()
        if rows
    }
    row_index_by_date = {
        symbol: {
            row["date"]: index
            for index, row in enumerate(histories[symbol])
        }
        for symbol in usable_symbols
    }
    signal_events_by_date = {
        symbol: {
            row["date"]: event
            for row, event in zip(histories[symbol], _signal_events(signals_by_symbol[symbol]))
        }
        for symbol in usable_symbols
    }
    ema_by_date = _ema_by_date(histories, usable_symbols, sell_rule_ema_window)
    dates = sorted(set.union(*(set(rows_by_date[symbol]) for symbol in usable_symbols)))

    cash = config.initial_capital
    positions: dict[str, dict] = {}
    last_closes: dict[str, float] = {}
    all_time_highs: dict[str, float] = {}
    ranking_last_closes: dict[str, float] = {}
    ranking_all_time_highs: dict[str, float] = {}
    per_symbol_stats: dict[str, dict] = {
        symbol: _empty_symbol_stats(symbol)
        for symbol in usable_symbols
    }
    equity_curve: list[dict] = []
    trades: list[dict] = []
    capital_flows: list[dict] = [{"date": dates[0], "amount": -float(config.initial_capital), "reason": "initial_capital"}]
    total_capital_added = 0.0
    total_capital_withdrawn = 0.0
    total_extra_capital = 0.0
    max_extra_capital_used = 0.0
    extra_capital_balance = 0.0
    total_extra_capital_interest = 0.0
    extra_capital_limit = float(config.initial_capital) * extra_capital_limit_multiplier
    previous_date = None
    last_capital_addition_month = (dates[0].year, dates[0].month)
    last_withdrawal_month = None
    withdrawal_trigger_reached = False

    for current_date in dates:
        if previous_date is not None and extra_capital_balance > 0 and extra_capital_interest_rate_daily > 0:
            days_held = max((current_date - previous_date).days, 0)
            interest = extra_capital_balance * extra_capital_interest_rate_daily * days_held
            if interest > 0:
                cash -= interest
                total_extra_capital_interest += interest

        current_month = (current_date.year, current_date.month)
        if monthly_capital_addition > 0 and current_month != last_capital_addition_month:
            cash += monthly_capital_addition
            total_capital_added += monthly_capital_addition
            capital_flows.append({"date": current_date, "amount": -monthly_capital_addition, "reason": "monthly_capital_addition"})
            last_capital_addition_month = current_month

        active_symbols = [
            symbol
            for symbol in usable_symbols
            if current_date in rows_by_date[symbol] and current_date in signal_events_by_date[symbol]
        ]
        for symbol in active_symbols:
            close = float(rows_by_date[symbol][current_date]["close"])
            last_closes[symbol] = close
            all_time_highs[symbol] = max(all_time_highs.get(symbol, close), close)
        for source, source_rows_by_date in ranking_rows_by_date.items():
            if current_date in source_rows_by_date:
                close = float(source_rows_by_date[current_date]["close"])
                ranking_last_closes[source] = close
                ranking_all_time_highs[source] = max(ranking_all_time_highs.get(source, close), close)

        for symbol in list(positions):
            if symbol in active_symbols and signal_events_by_date[symbol][current_date] == -1:
                position = positions.pop(symbol)
                fill_source_price = _sell_source_price(
                    close=last_closes[symbol],
                    position=position,
                    sell_price_rule=sell_price_rule,
                )
                fill_price = sell_price(fill_source_price, config.slippage_rate)
                shares = position["shares"]
                trade_value = shares * fill_price
                fee = commission(trade_value, config.commission_rate)
                realized_profit = trade_value - fee - position["cost_basis"]
                holding_days = (current_date - position["entry_date"]).days
                _record_closed_trade(per_symbol_stats[symbol], realized_profit, holding_days)
                cash += trade_value - fee
                trades.append(
                    {
                        "date": current_date,
                        "symbol": symbol,
                        "side": "SELL",
                        "time": rows_by_date[symbol][current_date].get("time", ""),
                        "price": fill_price,
                        "source_price": fill_source_price,
                        "entry_low": position.get("entry_low"),
                        "entry_ema": position.get("entry_ema"),
                        "shares": shares,
                        "value": trade_value - fee,
                        "profit": realized_profit,
                        "holding_days": holding_days,
                        "reason": "signal",
                    }
                )

        if cash > 0 and extra_capital_balance > 0:
            cash, extra_capital_balance = _repay_extra_capital(
                cash=cash,
                extra_capital_balance=extra_capital_balance,
            )

        if withdrawal_target is not None and monthly_withdrawal_amount > 0 and cash >= monthly_withdrawal_amount:
            equity_before_withdrawal = _portfolio_equity(cash, positions, last_closes, extra_capital_balance)
            if equity_before_withdrawal >= withdrawal_target:
                withdrawal_trigger_reached = True
            if withdrawal_trigger_reached and current_month != last_withdrawal_month:
                cash -= monthly_withdrawal_amount
                total_capital_withdrawn += monthly_withdrawal_amount
                last_withdrawal_month = current_month
                capital_flows.append({"date": current_date, "amount": monthly_withdrawal_amount, "reason": "monthly_target_withdrawal"})

        ranking_mode = candidate_ranking or ("ath" if rank_buy_candidates_by_ath else "none")
        add_candidates = [
            symbol
            for symbol in active_symbols
            if (
                signal_events_by_date[symbol][current_date] > 0
                and symbol in positions
                and int(positions[symbol].get("entry_parts_filled", 1)) < entry_parts
            )
        ]
        new_candidates = [
            symbol
            for symbol in active_symbols
            if signal_events_by_date[symbol][current_date] > 0 and symbol not in positions
        ]
        add_candidates = _rank_symbols(
            add_candidates,
            ranking_mode,
            current_date,
            histories,
            row_index_by_date,
            last_closes,
            all_time_highs,
            ranking_sources,
            ranking_last_closes,
            ranking_all_time_highs,
        )
        new_candidates = _rank_symbols(
            new_candidates,
            ranking_mode,
            current_date,
            histories,
            row_index_by_date,
            last_closes,
            all_time_highs,
            ranking_sources,
            ranking_last_closes,
            ranking_all_time_highs,
        )
        if (
            rotate_to_stronger_candidates
            and ranking_mode != "none"
            and new_candidates
            and len(positions) >= max_positions
        ):
            cash = _rotate_to_stronger_candidates(
                candidates=new_candidates,
                positions=positions,
                active_symbols=active_symbols,
                signal_events_by_date=signal_events_by_date,
                current_date=current_date,
                histories=histories,
                row_index_by_date=row_index_by_date,
                last_closes=last_closes,
                all_time_highs=all_time_highs,
                ranking_sources=ranking_sources,
                ranking_last_closes=ranking_last_closes,
                ranking_all_time_highs=ranking_all_time_highs,
                rows_by_date=rows_by_date,
                config=config,
                ranking_mode=ranking_mode,
                cash=cash,
                trades=trades,
                per_symbol_stats=per_symbol_stats,
            )
        slots_available = max_positions - len(positions)
        selected: list[str] = []
        overflow_burst = False
        if slots_available > 0 and new_candidates:
            overflow_burst = buy_all_overflow_signals and len(new_candidates) > slots_available
            if overflow_burst and max_overflow_positions is not None:
                selected = new_candidates[:slots_available + max_overflow_positions]
            else:
                selected = new_candidates if overflow_burst else new_candidates[:slots_available]
        selected = [*add_candidates, *selected]
        if selected:
            fixed_position_capital = config.initial_capital / max_positions
            current_equity = _portfolio_equity(cash, positions, last_closes, extra_capital_balance)
            sizing_equity = (
                current_equity + extra_capital_limit
                if mtf_mode == "normal"
                else current_equity
            )
            target_position_capital = (
                sizing_equity / max_positions
                if compound_positions
                else fixed_position_capital
            )
            for symbol in selected:
                event_parts = max(int(signal_events_by_date[symbol][current_date]), 1)
                existing_position = positions.get(symbol)
                filled_parts = int(existing_position.get("entry_parts_filled", 0)) if existing_position else 0
                remaining_parts = max(entry_parts - filled_parts, 0)
                parts_to_buy = min(event_parts, remaining_parts)
                if parts_to_buy <= 0:
                    continue
                target_entry_capital = target_position_capital * _entry_weight(
                    entry_part_weights,
                    filled_parts,
                    parts_to_buy,
                )
                use_extra_capital = mtf_mode == "normal" or overflow_burst
                if use_extra_capital and cash < target_entry_capital:
                    allowed_extra_capital = max(extra_capital_limit - extra_capital_balance, 0.0)
                    extra_capital = min(target_entry_capital - cash, allowed_extra_capital)
                    if extra_capital <= 0:
                        position_budget = max(cash, 0.0)
                    else:
                        cash += extra_capital
                        total_extra_capital += extra_capital
                        extra_capital_balance += extra_capital
                        max_extra_capital_used = max(max_extra_capital_used, extra_capital_balance)
                        position_budget = min(target_entry_capital, cash)
                else:
                    position_budget = target_entry_capital if use_extra_capital else min(target_entry_capital, cash)
                if position_budget <= 0:
                    continue
                if not use_extra_capital:
                    position_budget = min(position_budget, cash)
                fill_price = buy_price(last_closes[symbol], config.slippage_rate)
                gross_shares = floor(position_budget / fill_price)
                trade_value = gross_shares * fill_price
                fee = commission(trade_value, config.commission_rate)
                shares = floor(max((position_budget - fee) / fill_price, 0))
                if shares <= 0:
                    continue
                entry_value = shares * fill_price + fee
                if existing_position:
                    existing_position["shares"] += shares
                    existing_position["cost_basis"] += entry_value
                    existing_position["entry_price"] = existing_position["cost_basis"] / existing_position["shares"]
                    existing_position["entry_parts_filled"] = filled_parts + parts_to_buy
                    existing_position.setdefault("entry_dates", []).append(current_date)
                    position = existing_position
                else:
                    positions[symbol] = {
                        "shares": shares,
                        "entry_date": current_date,
                        "entry_price": fill_price,
                        "entry_low": float(rows_by_date[symbol][current_date].get("low", last_closes[symbol])),
                        "entry_ema": ema_by_date[symbol].get(current_date),
                        "cost_basis": entry_value,
                        "entry_parts_filled": parts_to_buy,
                        "entry_dates": [current_date],
                    }
                    position = positions[symbol]
                cash -= entry_value
                per_symbol_stats[symbol]["buy_count"] += 1
                trades.append(
                    {
                        "date": current_date,
                        "symbol": symbol,
                        "side": "BUY",
                        "time": rows_by_date[symbol][current_date].get("time", ""),
                        "price": fill_price,
                        "entry_low": position.get("entry_low"),
                        "entry_ema": position.get("entry_ema"),
                        "shares": shares,
                        "value": entry_value,
                        "profit": 0.0,
                        "holding_days": 0,
                        "extra_capital_mode": use_extra_capital,
                        "mtf_mode": mtf_mode,
                        "entry_part": position.get("entry_parts_filled", parts_to_buy),
                        "entry_parts": entry_parts,
                    }
                )

        equity = _portfolio_equity(cash, positions, last_closes, extra_capital_balance)
        equity_curve.append({"date": current_date, "equity": equity, "positions": len(positions)})
        previous_date = current_date

    last_date = dates[-1]
    open_positions = _build_open_positions(positions, last_closes, last_date, per_symbol_stats)
    realized_profit = sum(stats["realized_profit"] for stats in per_symbol_stats.values())
    unrealized_profit = sum(position["unrealized_profit"] for position in open_positions)

    return MultiBacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        skipped_symbols=skipped_symbols,
        realized_profit=realized_profit,
        unrealized_profit=unrealized_profit,
        open_positions=open_positions,
        per_symbol_report=_build_per_symbol_report(per_symbol_stats),
        capital_flows=[*capital_flows, {"date": last_date, "amount": equity_curve[-1]["equity"], "reason": "ending_equity"}],
        total_capital_added=total_capital_added,
        total_capital_withdrawn=total_capital_withdrawn,
        total_extra_capital=total_extra_capital,
        max_extra_capital_used=max_extra_capital_used,
        extra_capital_balance=extra_capital_balance,
        total_extra_capital_interest=total_extra_capital_interest,
    )


def _repay_extra_capital(
    cash: float,
    extra_capital_balance: float,
) -> tuple[float, float]:
    repayment = min(cash, extra_capital_balance)
    if repayment <= 0:
        return cash, extra_capital_balance
    return cash - repayment, extra_capital_balance - repayment


def _normalize_entry_part_weights(entry_parts: int, weights: list[float] | None) -> list[float]:
    if weights is None:
        return [1.0 / entry_parts] * entry_parts
    if len(weights) != entry_parts:
        raise ValueError("entry_part_weights length must match entry_parts")
    if any(weight < 0 for weight in weights):
        raise ValueError("entry_part_weights cannot contain negative values")
    total = sum(weights)
    if total <= 0:
        raise ValueError("entry_part_weights must have a positive total")
    return [weight / total for weight in weights]


def _entry_weight(weights: list[float], filled_parts: int, parts_to_buy: int) -> float:
    start = max(filled_parts, 0)
    end = min(start + parts_to_buy, len(weights))
    return sum(weights[start:end])


def _portfolio_equity(
    cash: float,
    positions: dict[str, dict],
    last_closes: dict[str, float],
    extra_capital_balance: float,
) -> float:
    position_value = sum(
        position["shares"] * last_closes[symbol]
        for symbol, position in positions.items()
        if symbol in last_closes
    )
    return cash + position_value - extra_capital_balance


def _rotate_to_stronger_candidates(
    candidates: list[str],
    positions: dict[str, dict],
    active_symbols: list[str],
    signal_events_by_date: dict[str, dict],
    current_date,
    histories: dict[str, list[dict]],
    row_index_by_date: dict[str, dict],
    last_closes: dict[str, float],
    all_time_highs: dict[str, float],
    ranking_sources: dict[str, str],
    ranking_last_closes: dict[str, float],
    ranking_all_time_highs: dict[str, float],
    rows_by_date: dict[str, dict],
    config: BacktestConfig,
    ranking_mode: str,
    cash: float,
    trades: list[dict],
    per_symbol_stats: dict[str, dict],
) -> float:
    """Sell weaker held ETFs to create slots for stronger ranked candidates."""

    active_set = set(active_symbols)
    for candidate in candidates:
        held_symbols = [
            symbol
            for symbol in positions
            if symbol in active_set and signal_events_by_date[symbol][current_date] != -1
        ]
        if not held_symbols:
            break

        weakest_held = min(
            held_symbols,
            key=lambda symbol: _ranking_score(
                symbol,
                ranking_mode,
                current_date,
                histories,
                row_index_by_date,
                last_closes,
                all_time_highs,
                ranking_sources,
                ranking_last_closes,
                ranking_all_time_highs,
            ),
        )
        candidate_score = _ranking_score(
            candidate,
            ranking_mode,
            current_date,
            histories,
            row_index_by_date,
            last_closes,
            all_time_highs,
            ranking_sources,
            ranking_last_closes,
            ranking_all_time_highs,
        )
        weakest_score = _ranking_score(
            weakest_held,
            ranking_mode,
            current_date,
            histories,
            row_index_by_date,
            last_closes,
            all_time_highs,
            ranking_sources,
            ranking_last_closes,
            ranking_all_time_highs,
        )
        if candidate_score <= weakest_score:
            break

        cash = _sell_position(
            symbol=weakest_held,
            current_date=current_date,
            rows_by_date=rows_by_date,
            last_closes=last_closes,
            positions=positions,
            config=config,
            sell_price_rule="close",
            cash=cash,
            trades=trades,
            per_symbol_stats=per_symbol_stats,
            reason="rotation",
        )

    return cash


def _ath_proximity(
    symbol: str,
    last_closes: dict[str, float],
    all_time_highs: dict[str, float],
) -> float:
    high = all_time_highs.get(symbol)
    if not high:
        return 0.0
    return last_closes[symbol] / high


def _rank_symbols(
    symbols: list[str],
    ranking_mode: str,
    current_date,
    histories: dict[str, list[dict]],
    row_index_by_date: dict[str, dict],
    last_closes: dict[str, float],
    all_time_highs: dict[str, float],
    ranking_sources: dict[str, str],
    ranking_last_closes: dict[str, float],
    ranking_all_time_highs: dict[str, float],
) -> list[str]:
    if ranking_mode == "none":
        return symbols

    return sorted(
        symbols,
        key=lambda symbol: _ranking_score(
            symbol,
            ranking_mode,
            current_date,
            histories,
            row_index_by_date,
            last_closes,
            all_time_highs,
            ranking_sources,
            ranking_last_closes,
            ranking_all_time_highs,
        ),
        reverse=True,
    )


def _ranking_score(
    symbol: str,
    ranking_mode: str,
    current_date,
    histories: dict[str, list[dict]],
    row_index_by_date: dict[str, dict],
    last_closes: dict[str, float],
    all_time_highs: dict[str, float],
    ranking_sources: dict[str, str],
    ranking_last_closes: dict[str, float],
    ranking_all_time_highs: dict[str, float],
) -> tuple[float, float]:
    if ranking_mode == "ath":
        source = ranking_sources.get(symbol, symbol)
        return (0.0, _ath_proximity(source, ranking_last_closes, ranking_all_time_highs))
    if ranking_mode == "momentum_20_60":
        both_positive, momentum = _momentum_score(symbol, current_date, histories, row_index_by_date)
        return (float(both_positive), momentum)

    return (0.0, 0.0)


def _momentum_score(
    symbol: str,
    current_date,
    histories: dict[str, list[dict]],
    row_index_by_date: dict[str, dict],
) -> tuple[int, float]:
    current_index = row_index_by_date[symbol].get(current_date)
    if current_index is None:
        return (0, -999.0)

    return_20 = _lookback_return(histories[symbol], current_index, 20)
    return_60 = _lookback_return(histories[symbol], current_index, 60)
    both_positive = int(return_20 > 0 and return_60 > 0)
    return (both_positive, return_20 + return_60)


def _lookback_return(rows: list[dict], current_index: int, lookback: int) -> float:
    if current_index < lookback:
        return -999.0

    current_close = float(rows[current_index]["close"])
    previous_close = float(rows[current_index - lookback]["close"])
    if previous_close <= 0:
        return -999.0

    return (current_close / previous_close) - 1.0


def _signal_events(signals: list[int]) -> list[int]:
    """Convert exposure state signals into buy/add/sell events."""

    events: list[int] = []
    previous = 0
    for signal in signals:
        current = int(signal)
        if current > previous:
            events.append(current - previous)
        elif previous > 0 and current <= 0:
            events.append(-1)
        else:
            events.append(0)
        previous = current
    return events


def _ema_by_date(histories: dict[str, list[dict]], symbols: list[str], window: int) -> dict[str, dict]:
    values: dict[str, dict] = {}
    for symbol in symbols:
        rows = histories[symbol]
        closes = [float(row["close"]) for row in rows]
        ema_values = exponential_moving_average(closes, window)
        values[symbol] = {
            row["date"]: ema
            for row, ema in zip(rows, ema_values)
            if ema is not None
        }
    return values


def _sell_source_price(close: float, position: dict, sell_price_rule: str) -> float:
    if sell_price_rule != "entry_low_or_entry_ema":
        return close

    entry_low = position.get("entry_low")
    if entry_low is None or close >= float(entry_low):
        return close

    entry_ema = position.get("entry_ema")
    if entry_ema is not None and float(entry_low) > float(entry_ema):
        return float(entry_ema)

    return float(entry_low)


def _sell_position(
    symbol: str,
    current_date,
    rows_by_date: dict[str, dict],
    last_closes: dict[str, float],
    positions: dict[str, dict],
    config: BacktestConfig,
    sell_price_rule: str,
    cash: float,
    trades: list[dict],
    per_symbol_stats: dict[str, dict],
    reason: str,
) -> float:
    position = positions.pop(symbol)
    fill_source_price = _sell_source_price(
        close=last_closes[symbol],
        position=position,
        sell_price_rule=sell_price_rule,
    )
    fill_price = sell_price(fill_source_price, config.slippage_rate)
    shares = position["shares"]
    trade_value = shares * fill_price
    fee = commission(trade_value, config.commission_rate)
    realized_profit = trade_value - fee - position["cost_basis"]
    holding_days = (current_date - position["entry_date"]).days
    _record_closed_trade(per_symbol_stats[symbol], realized_profit, holding_days)
    trades.append(
        {
            "date": current_date,
            "symbol": symbol,
            "side": "SELL",
            "time": rows_by_date[symbol][current_date].get("time", ""),
            "price": fill_price,
            "source_price": fill_source_price,
            "entry_low": position.get("entry_low"),
            "entry_ema": position.get("entry_ema"),
            "shares": shares,
            "value": trade_value - fee,
            "profit": realized_profit,
            "holding_days": holding_days,
            "reason": reason,
        }
    )

    return cash + trade_value - fee


def _empty_symbol_stats(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "realized_profit": 0.0,
        "unrealized_profit": 0.0,
        "total_profit": 0.0,
        "closed_trades": 0,
        "buy_count": 0,
        "open_quantity": 0.0,
        "open_market_value": 0.0,
        "min_holding_days": None,
        "max_holding_days": None,
    }


def _record_closed_trade(stats: dict, realized_profit: float, holding_days: int) -> None:
    stats["realized_profit"] += realized_profit
    stats["closed_trades"] += 1
    stats["min_holding_days"] = (
        holding_days
        if stats["min_holding_days"] is None
        else min(stats["min_holding_days"], holding_days)
    )
    stats["max_holding_days"] = (
        holding_days
        if stats["max_holding_days"] is None
        else max(stats["max_holding_days"], holding_days)
    )


def _build_open_positions(
    positions: dict[str, dict],
    last_closes: dict[str, float],
    last_date,
    per_symbol_stats: dict[str, dict],
) -> list[dict]:
    open_positions: list[dict] = []

    for symbol, position in sorted(positions.items()):
        last_price = last_closes[symbol]
        market_value = position["shares"] * last_price
        unrealized_profit = market_value - position["cost_basis"]
        holding_days = (last_date - position["entry_date"]).days
        stats = per_symbol_stats[symbol]
        stats["unrealized_profit"] += unrealized_profit
        stats["open_quantity"] += position["shares"]
        stats["open_market_value"] += market_value
        stats["min_holding_days"] = (
            holding_days
            if stats["min_holding_days"] is None
            else min(stats["min_holding_days"], holding_days)
        )
        stats["max_holding_days"] = (
            holding_days
            if stats["max_holding_days"] is None
            else max(stats["max_holding_days"], holding_days)
        )
        open_positions.append(
            {
                "symbol": symbol,
                "shares": position["shares"],
                "entry_date": position["entry_date"],
                "entry_price": position["entry_price"],
                "last_date": last_date,
                "last_price": last_price,
                "market_value": market_value,
                "cost_basis": position["cost_basis"],
                "unrealized_profit": unrealized_profit,
                "holding_days": holding_days,
            }
        )

    return open_positions


def _build_per_symbol_report(per_symbol_stats: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for symbol, stats in sorted(per_symbol_stats.items()):
        total_profit = stats["realized_profit"] + stats["unrealized_profit"]
        rows.append(
            {
                **stats,
                "total_profit": total_profit,
                "min_holding_days": stats["min_holding_days"] if stats["min_holding_days"] is not None else 0,
                "max_holding_days": stats["max_holding_days"] if stats["max_holding_days"] is not None else 0,
            }
        )

    return rows
