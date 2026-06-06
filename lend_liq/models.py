"""Typed domain models. Health metrics are derived properties, so a Position is
fully described by its collateral, borrows, and Kamino's fresh debt figure."""

from __future__ import annotations

from dataclasses import dataclass

from .config import STABLE_SYMBOLS


@dataclass(frozen=True)
class Collateral:
    """A deposited asset backing the loan."""

    symbol: str
    amount: float
    price: float
    liquidation_threshold: float

    @property
    def value(self) -> float:
        """USD value of the deposit (amount × price)."""
        return self.amount * self.price

    @property
    def weighted_value(self) -> float:
        """The slice of this collateral that counts toward the liquidation limit."""
        return self.value * self.liquidation_threshold

    @property
    def is_stable(self) -> bool:
        """Whether the asset is treated as a peg-holding stablecoin."""
        return self.symbol.upper() in STABLE_SYMBOLS


@dataclass(frozen=True)
class Borrow:
    """A borrowed asset — the position's debt."""

    symbol: str
    amount: float
    price: float
    borrow_factor: float = 1.0

    @property
    def value(self) -> float:
        """USD value of the borrow (amount × price)."""
        return self.amount * self.price

    @property
    def is_stable(self) -> bool:
        """Whether the borrowed asset is a peg-holding stablecoin."""
        return self.symbol.upper() in STABLE_SYMBOLS


@dataclass(frozen=True)
class Position:
    """A wallet's obligation in one market: its collateral, debt, and health."""

    market_name: str
    address: str
    collateral: tuple[Collateral, ...]
    borrows: tuple[Borrow, ...]
    debt_value: float  # Kamino's fresh, borrow-factor-adjusted debt (USD)
    market_id: str = ""

    @property
    def has_debt(self) -> bool:
        """Whether the position carries debt (and so can be liquidated)."""
        return self.debt_value > 0

    @property
    def deposit_value(self) -> float:
        """Total USD value of all collateral."""
        return sum(c.value for c in self.collateral)

    @property
    def liquidation_limit(self) -> float:
        """Debt value at which the position becomes liquidatable."""
        return sum(c.weighted_value for c in self.collateral)

    @property
    def net_value(self) -> float:
        """The position's equity: collateral value minus debt."""
        return self.deposit_value - self.debt_value

    @property
    def current_ltv(self) -> float:
        """Current loan-to-value ratio (debt ÷ deposits)."""
        return self.debt_value / self.deposit_value if self.deposit_value else 0.0

    @property
    def liquidation_ltv(self) -> float:
        """Weighted-average liquidation threshold (limit ÷ deposits)."""
        return self.liquidation_limit / self.deposit_value if self.deposit_value else 0.0

    @property
    def health_factor(self) -> float:
        """Liquidation limit ÷ debt; the position is liquidated below 1.0."""
        return self.liquidation_limit / self.debt_value if self.debt_value else float("inf")

    @property
    def drop_to_liquidation(self) -> float:
        """Fraction every collateral can fall together before liquidation."""
        if not self.liquidation_limit:
            return 0.0
        return max(0.0, 1 - self.debt_value / self.liquidation_limit)


@dataclass(frozen=True)
class ReserveInfo:
    """Info fetched from a protocol's reserve catalog for simulating new assets."""

    symbol: str
    price: float
    liquidation_threshold: float
    borrow_factor: float
