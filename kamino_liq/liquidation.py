"""Pure liquidation-price math. No I/O, no rendering — just functions over the
domain models, which keeps it trivial to unit-test."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .models import Collateral, Position


@dataclass(frozen=True)
class LiquidationLevel:
    """Liquidation price of one collateral if only it moves, others held."""

    collateral: Collateral
    price: float | None  # None => the position survives even at $0

    @property
    def is_safe(self) -> bool:
        """Whether the position survives even if this asset falls to $0."""
        return self.price is None

    @property
    def buffer(self) -> float | None:
        """Fractional drop from the current price down to the liquidation price."""
        if self.price is None or not self.collateral.price:
            return None
        return (self.collateral.price - self.price) / self.collateral.price


def single_asset_levels(position: Position) -> list[LiquidationLevel]:
    """For each collateral: the price at which the position is liquidated if that
    asset alone falls and the others hold their current value."""
    levels: list[LiquidationLevel] = []
    for collateral in position.collateral:
        held = position.liquidation_limit - collateral.weighted_value
        denominator = collateral.amount * collateral.liquidation_threshold
        price = (position.debt_value - held) / denominator if denominator else 0.0
        levels.append(LiquidationLevel(collateral, price if price > 0 else None))
    return levels


class CrashStatus(enum.Enum):
    """Possible outcomes of the market-crash scenario."""

    SAFE = "safe"  # stable collateral alone covers the debt
    EXCEEDED = "exceeded"  # debt exceeds stables and there is no volatile buffer
    AT_RISK = "at_risk"  # already at or past the liquidation threshold
    TRIGGERABLE = "triggerable"  # a finite volatile drop triggers liquidation


@dataclass(frozen=True)
class CrashScenario:
    """The outcome of a market crash for a position, with per-asset prices."""

    status: CrashStatus
    drop: float | None = None  # volatile drop fraction that triggers liquidation
    prices: tuple[tuple[Collateral, float], ...] = ()  # per-asset price at that drop


def crash_scenario(position: Position) -> CrashScenario:
    """Model a market crash where volatile collateral falls together while stable
    collateral holds its peg."""
    stable_capacity = sum(c.weighted_value for c in position.collateral if c.is_stable)
    volatile_capacity = sum(c.weighted_value for c in position.collateral if not c.is_stable)
    debt = position.debt_value

    if debt <= stable_capacity:
        return CrashScenario(CrashStatus.SAFE)
    if volatile_capacity <= 0:
        return CrashScenario(CrashStatus.EXCEEDED)

    remaining = (debt - stable_capacity) / volatile_capacity
    if remaining >= 1.0:
        return CrashScenario(CrashStatus.AT_RISK)

    prices = tuple(
        (c, c.price if c.is_stable else c.price * remaining) for c in position.collateral
    )
    return CrashScenario(CrashStatus.TRIGGERABLE, drop=1 - remaining, prices=prices)
