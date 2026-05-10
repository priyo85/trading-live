"""Optional ETF-to-index signal source mappings."""

from __future__ import annotations

from pathlib import Path
import json

from backtesting.etf_backtester.config.json_loader import load_json_config


SIGNAL_SOURCES_PATH = Path(__file__).with_suffix(".json")


def load_signal_sources(path: str | Path = SIGNAL_SOURCES_PATH) -> dict[str, str]:
    """Load optional ETF signal source symbols from JSON."""

    data = load_json_config(path)
    sources = data.get("signal_sources", {})
    if not isinstance(sources, dict):
        raise ValueError(f"Expected signal_sources object in {path}")

    normalized: dict[str, str] = {}
    for etf_symbol, source_symbol in sources.items():
        if not source_symbol:
            continue
        if not isinstance(etf_symbol, str) or not isinstance(source_symbol, str):
            raise ValueError(f"Invalid signal source mapping in {path}")
        normalized[etf_symbol.strip().upper()] = source_symbol.strip().upper()

    return normalized


SIGNAL_SOURCES = load_signal_sources()


def save_signal_sources(sources: dict[str, str], path: str | Path = SIGNAL_SOURCES_PATH) -> dict[str, str]:
    """Save ETF signal source mappings to JSON."""

    normalized: dict[str, str] = {}
    for etf_symbol, source_symbol in sources.items():
        if not isinstance(etf_symbol, str) or not isinstance(source_symbol, str):
            raise ValueError("Signal source mappings must be strings.")
        etf = etf_symbol.strip().upper()
        source = source_symbol.strip().upper()
        if etf and source:
            normalized[etf] = source

    output_path = Path(path)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump({"signal_sources": normalized}, file, indent=2)

    global SIGNAL_SOURCES
    SIGNAL_SOURCES = normalized
    return normalized


def signal_source_for(etf_symbol: str) -> str:
    """Return the configured index/source symbol for an ETF, or the ETF itself."""

    normalized_symbol = etf_symbol.strip().upper()
    return load_signal_sources().get(normalized_symbol, normalized_symbol)


def signal_sources_for(etf_symbols: list[str]) -> dict[str, str]:
    """Return signal source used by each ETF in a selected universe."""

    sources = load_signal_sources()
    return {symbol: sources.get(symbol, symbol) for symbol in etf_symbols}
