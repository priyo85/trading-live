"""Default NSE ETF universe for swing trading backtests."""

from __future__ import annotations

from pathlib import Path

from backtesting.etf_backtester.config.json_loader import load_json_config


ETF_UNIVERSE_PATH = Path(__file__).with_suffix(".json")
YAHOO_SYMBOL_ALIASES_PATH = Path(__file__).with_name("yahoo_symbol_aliases.json")
NSE_INDEX_ALIASES_PATH = Path(__file__).with_name("nse_index_aliases.json")


def load_etf_universe(path: str | Path = ETF_UNIVERSE_PATH) -> tuple[str, ...]:
    """Load the ETF universe from JSON."""

    data = load_json_config(path)
    symbols = data.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError(f"Expected a non-empty symbols list in {path}")

    return tuple(_validate_symbol(symbol, path) for symbol in symbols)


def _validate_symbol(symbol: object, path: str | Path) -> str:
    if not isinstance(symbol, str) or ":" not in symbol:
        raise ValueError(f"Invalid ETF symbol in {path}: {symbol!r}")
    return symbol.strip().upper()


def strip_exchange(symbol: str) -> str:
    """Return the ticker without the exchange prefix."""

    return symbol.split(":", maxsplit=1)[-1].strip().upper()


def load_symbol_aliases(path: str | Path = YAHOO_SYMBOL_ALIASES_PATH) -> dict[str, str]:
    """Load non-ETF source symbol aliases for Yahoo Finance."""

    data = load_json_config(path)
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError(f"Expected aliases object in {path}")

    normalized: dict[str, str] = {}
    for source_symbol, yahoo_symbol in aliases.items():
        if not isinstance(source_symbol, str) or not isinstance(yahoo_symbol, str):
            raise ValueError(f"Invalid Yahoo symbol alias in {path}")
        normalized[source_symbol.strip().upper()] = yahoo_symbol.strip()

    return normalized


def load_nse_index_aliases(path: str | Path = NSE_INDEX_ALIASES_PATH) -> dict[str, tuple[str, ...]]:
    """Load NSE index display names for the official NSE API fallback."""

    data = load_json_config(path)
    indices = data.get("indices", {})
    if not isinstance(indices, dict):
        raise ValueError(f"Expected indices object in {path}")

    normalized: dict[str, tuple[str, ...]] = {}
    for source_symbol, index_names in indices.items():
        if not isinstance(source_symbol, str):
            raise ValueError(f"Invalid NSE index alias source in {path}")
        if isinstance(index_names, str):
            names = [index_names]
        elif isinstance(index_names, list):
            names = index_names
        else:
            raise ValueError(f"Invalid NSE index alias names in {path}")

        cleaned_names = tuple(str(name).strip().upper() for name in names if str(name).strip())
        if not cleaned_names:
            raise ValueError(f"Empty NSE index alias names in {path}")
        normalized[source_symbol.strip().upper()] = cleaned_names

    return normalized


ETF_UNIVERSE = load_etf_universe()
YAHOO_SYMBOL_ALIASES = load_symbol_aliases()
NSE_INDEX_ALIASES = load_nse_index_aliases()


def to_yahoo_symbol(symbol: str) -> str:
    """Convert project source symbols into Yahoo Finance symbols."""

    normalized = symbol.strip().upper()
    if normalized in YAHOO_SYMBOL_ALIASES:
        return YAHOO_SYMBOL_ALIASES[normalized]
    if normalized.startswith("YAHOO:"):
        return symbol.split(":", maxsplit=1)[-1].strip()
    if normalized.startswith("^") or "." in normalized:
        return symbol.strip()
    return f"{strip_exchange(symbol)}.NS"


def all_yahoo_symbols() -> tuple[str, ...]:
    """Return the default ETF universe in Yahoo Finance format."""

    return tuple(to_yahoo_symbol(symbol) for symbol in ETF_UNIVERSE)
