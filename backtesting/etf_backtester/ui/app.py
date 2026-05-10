"""Tkinter UI for running ETF swing backtests."""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from backtesting.etf_backtester.config.etf_universe import ETF_UNIVERSE
from backtesting.etf_backtester.config.settings import DEFAULT_CONFIG, STRATEGY_SETTINGS, BacktestConfig
from backtesting.etf_backtester.data.market_data import fetch_historical_prices
from backtesting.etf_backtester.portfolio.multi_backtest import run_multi_etf_backtest
from backtesting.etf_backtester.reports.multi_summary import build_multi_summary
from backtesting.etf_backtester.strategies.ema_trend import EmaTrendStrategy


class ETFBacktesterApp(tk.Tk):
    """Desktop UI for configuring and running ETF swing backtests."""

    def __init__(self) -> None:
        super().__init__()
        self.title("ETF Swing Backtester")
        self.geometry("980x680")
        self.minsize(860, 560)

        ema_defaults = STRATEGY_SETTINGS["ema_trend"]
        self.initial_capital = tk.StringVar(value=str(DEFAULT_CONFIG.initial_capital))
        self.max_etfs = tk.StringVar(value=str(DEFAULT_CONFIG.max_positions))
        self.start_date = tk.StringVar(value=DEFAULT_CONFIG.default_start_date)
        self.end_date = tk.StringVar(value=datetime.today().date().isoformat())
        self.strategy_name = tk.StringVar(value=ema_defaults["display_name"])
        self.ema_window = tk.StringVar(value=str(ema_defaults["window"]))
        self.status = tk.StringVar(value="Ready.")

        self._build_layout()

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=16)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=2)
        root.columnconfigure(1, weight=3)
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        universe = ttk.LabelFrame(root, text="ETF Universe", padding=10)
        universe.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 12))
        universe.columnconfigure(0, weight=1)
        universe.rowconfigure(0, weight=1)

        self.etf_listbox = tk.Listbox(universe, selectmode="extended", exportselection=False)
        self.etf_listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(universe, orient="vertical", command=self.etf_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.etf_listbox.configure(yscrollcommand=scrollbar.set)
        for symbol in ETF_UNIVERSE:
            self.etf_listbox.insert("end", symbol)
        for index in range(min(3, len(ETF_UNIVERSE))):
            self.etf_listbox.selection_set(index)

        list_actions = ttk.Frame(universe)
        list_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(list_actions, text="Select All", command=self._select_all_etfs).pack(side="left")
        ttk.Button(list_actions, text="Clear", command=self._clear_etfs).pack(side="left", padx=(8, 0))

        settings = ttk.LabelFrame(root, text="Backtest Configuration", padding=10)
        settings.grid(row=0, column=1, sticky="nsew")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Initial capital").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.initial_capital, width=18).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(settings, text="Max ETFs to buy").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(settings, from_=1, to=len(ETF_UNIVERSE), textvariable=self.max_etfs, width=16).grid(
            row=1, column=1, sticky="w", padx=8, pady=(10, 0)
        )

        ttk.Label(settings, text="Start date").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(settings, textvariable=self.start_date, width=18).grid(
            row=2, column=1, sticky="w", padx=8, pady=(10, 0)
        )

        ttk.Label(settings, text="End date").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(settings, textvariable=self.end_date, width=18).grid(
            row=3, column=1, sticky="w", padx=8, pady=(10, 0)
        )

        ttk.Label(settings, text="Strategy").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(
            settings,
            textvariable=self.strategy_name,
            values=(STRATEGY_SETTINGS["ema_trend"]["display_name"],),
            state="readonly",
            width=22,
        ).grid(row=4, column=1, sticky="w", padx=8, pady=(10, 0))

        ttk.Label(settings, text="EMA window").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(settings, from_=2, to=200, textvariable=self.ema_window, width=16).grid(
            row=5, column=1, sticky="w", padx=8, pady=(10, 0)
        )

        self.run_button = ttk.Button(settings, text="Run Backtest", command=self._run_backtest)
        self.run_button.grid(row=6, column=1, sticky="w", padx=8, pady=(16, 0))

        results = ttk.LabelFrame(root, text="Results", padding=10)
        results.grid(row=1, column=1, sticky="nsew", pady=(12, 0))
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)

        self.result_text = tk.Text(results, wrap="word", height=16)
        self.result_text.grid(row=0, column=0, sticky="nsew")
        result_scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.result_text.yview)
        result_scrollbar.grid(row=0, column=1, sticky="ns")
        self.result_text.configure(yscrollcommand=result_scrollbar.set)
        self._set_output("Ready.")

        ttk.Label(root, textvariable=self.status).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _select_all_etfs(self) -> None:
        self.etf_listbox.selection_set(0, "end")

    def _clear_etfs(self) -> None:
        self.etf_listbox.selection_clear(0, "end")

    def _run_backtest(self) -> None:
        try:
            request = self._build_request()
        except ValueError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            return

        self.run_button.configure(state="disabled")
        self.status.set("Running backtest...")
        self._set_output("Fetching Yahoo Finance history...")

        thread = threading.Thread(target=self._run_backtest_worker, args=(request,), daemon=True)
        thread.start()

    def _run_backtest_worker(self, request: dict) -> None:
        try:
            histories = fetch_historical_prices(
                request["symbols"],
                request["start_date"],
                request["end_date"],
            )
            strategy = EmaTrendStrategy(window=request["ema_window"])
            signals_by_symbol = {
                symbol: strategy.generate_signals(rows)
                for symbol, rows in histories.items()
                if rows
            }
            result = run_multi_etf_backtest(
                histories=histories,
                signals_by_symbol=signals_by_symbol,
                config=request["config"],
                max_positions=request["max_etfs"],
            )
            output = self._format_result(request, result)
            self.after(0, self._finish_backtest, output, None)
        except Exception as exc:
            self.after(0, self._finish_backtest, "", exc)

    def _finish_backtest(self, output: str, error: Exception | None) -> None:
        self.run_button.configure(state="normal")
        if error is not None:
            self.status.set("Backtest failed.")
            messagebox.showerror("Backtest failed", str(error))
            return

        self.status.set("Backtest complete.")
        self._set_output(output)

    def _build_request(self) -> dict:
        selected_indices = self.etf_listbox.curselection()
        symbols = [ETF_UNIVERSE[index] for index in selected_indices]
        if not symbols:
            raise ValueError("Select at least one ETF.")

        capital = float(self.initial_capital.get())
        if capital <= 0:
            raise ValueError("Initial capital must be greater than zero.")

        max_etfs = int(self.max_etfs.get())
        if max_etfs <= 0:
            raise ValueError("Max ETFs to buy must be greater than zero.")

        ema_window = int(self.ema_window.get())
        if ema_window <= 1:
            raise ValueError("EMA window must be greater than one.")

        start_date = _parse_date(self.start_date.get(), "start date")
        end_date = _parse_date(self.end_date.get(), "end date")
        if start_date > end_date:
            raise ValueError("Start date must be before or equal to end date.")

        return {
            "symbols": symbols,
            "config": BacktestConfig(initial_capital=capital),
            "max_etfs": max_etfs,
            "start_date": start_date,
            "end_date": end_date,
            "ema_window": ema_window,
        }

    def _format_result(self, request: dict, result) -> str:
        trade_lines = [
            (
                f"{trade['date']} {trade['side']} {trade['symbol']} "
                f"{trade['shares']:.4f} @ {trade['price']:.2f}"
            )
            for trade in result.trades[-20:]
        ]
        lines = [
            f"Selected ETFs: {', '.join(request['symbols'])}",
            f"Strategy: buy when close is above {request['ema_window']} EMA; sell when close is below {request['ema_window']} EMA",
            f"Max ETFs to buy: {request['max_etfs']}",
            "",
            build_multi_summary(result),
        ]
        if trade_lines:
            lines.extend(["", "Last trades:", *trade_lines])

        return "\n".join(lines)

    def _set_output(self, value: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", value)
        self.result_text.configure(state="disabled")


def _parse_date(value: str, label: str):
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {label}. Use YYYY-MM-DD.") from exc


def run_ui() -> None:
    """Launch the desktop UI."""

    app = ETFBacktesterApp()
    app.mainloop()
