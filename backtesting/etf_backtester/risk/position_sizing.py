"""Position sizing rules."""


def capital_to_deploy(cash: float, position_fraction: float) -> float:
    """Return cash amount to deploy after validating the fraction."""

    if not 0 < position_fraction <= 1:
        raise ValueError("position_fraction must be in the range (0, 1]")
    return cash * position_fraction
