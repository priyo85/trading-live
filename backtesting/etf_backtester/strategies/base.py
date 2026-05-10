"""Base strategy interfaces."""

from __future__ import annotations

from typing import Protocol


class Strategy(Protocol):
    """A strategy converts market rows into long/cash signals."""

    name: str

    def generate_signals(self, rows: list[dict]) -> list[int]:
        """Return one signal per market row."""
