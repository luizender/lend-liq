"""Pure liquidation-price math. No I/O, no rendering — just functions over the
domain models, which keeps it trivial to unit-test."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace

from .models import Borrow, Collateral, Position


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
    VOLATILE_DEBT = "volatile_debt"  # debt itself is volatile; a uniform crash is not meaningful


@dataclass(frozen=True)
class CrashScenario:
    """The outcome of a market crash for a position, with per-asset prices."""

    status: CrashStatus
    drop: float | None = None  # volatile drop fraction that triggers liquidation
    prices: tuple[tuple[Collateral, float], ...] = ()  # per-asset price at that drop


def crash_scenario(position: Position) -> CrashScenario:
    """Model a market crash where volatile collateral falls together while stable
    collateral holds its peg."""
    if any(not b.is_stable for b in position.borrows):
        # A uniform collateral crash would also move volatile debt, so holding the
        # debt fixed (as this model does) would be misleading. Defer to `simulate`.
        return CrashScenario(CrashStatus.VOLATILE_DEBT)

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


@dataclass(frozen=True)
class Changes:
    """A collection of overrides and additions to apply to a Position."""

    prices: dict[str, float] = field(default_factory=dict)
    collateral_amounts: dict[str, AmountChange] = field(default_factory=dict)
    borrow_amounts: dict[str, AmountChange] = field(default_factory=dict)
    add_collateral: tuple[Collateral, ...] = field(default_factory=tuple)
    add_borrows: tuple[Borrow, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AmountChange:
    """A simulated change to an asset's amount: an absolute target, or — when
    `is_delta` — a signed adjustment added to the current amount (floored at 0)."""

    value: float
    is_delta: bool

    def applied_to(self, amount: float) -> float:
        """The new amount after this change is applied to the current `amount`."""
        return max(0.0, amount + self.value) if self.is_delta else self.value


def apply_overrides(position: Position, changes: Changes) -> Position:
    """Return a copy of `position` with overrides and additions applied."""

    def _override_collateral(c: Collateral) -> Collateral:
        sym = c.symbol.upper()
        price = changes.prices.get(sym, c.price)
        amount = c.amount
        if sym in changes.collateral_amounts:
            amount = changes.collateral_amounts[sym].applied_to(amount)
        return replace(c, price=price, amount=amount)

    def _override_borrow(b: Borrow) -> Borrow:
        sym = b.symbol.upper()
        price = changes.prices.get(sym, b.price)
        amount = b.amount
        if sym in changes.borrow_amounts:
            amount = changes.borrow_amounts[sym].applied_to(amount)
        return replace(b, price=price, amount=amount)

    def _priced_collateral(c: Collateral) -> Collateral:
        sym = c.symbol.upper()
        price = changes.prices.get(sym, c.price)
        return replace(c, price=price)

    def _priced_borrow(b: Borrow) -> Borrow:
        sym = b.symbol.upper()
        price = changes.prices.get(sym, b.price)
        return replace(b, price=price)

    # Apply overrides to existing collateral
    collateral = tuple(_override_collateral(c) for c in position.collateral)
    # Append newly added collateral (with prices overridden if present)
    collateral += tuple(_priced_collateral(c) for c in changes.add_collateral)

    # Apply overrides to existing borrows
    existing_borrows = tuple(_override_borrow(b) for b in position.borrows)
    # Append newly added borrows (with prices overridden if present)
    added_borrows = tuple(_priced_borrow(b) for b in changes.add_borrows)
    borrows = existing_borrows + added_borrows

    # Debt calculation
    old_borrowed = sum(b.value for b in position.borrows)
    factor = position.debt_value / old_borrowed if old_borrowed else 1.0

    existing_debt = factor * sum(b.value for b in existing_borrows)
    added_debt = sum(b.value * b.borrow_factor for b in added_borrows)
    debt_value = existing_debt + added_debt

    return replace(position, collateral=collateral, borrows=borrows, debt_value=debt_value)
