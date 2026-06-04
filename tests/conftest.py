"""Shared test fixtures: in-memory fakes so no test touches the network."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from kamino_liq.models import Borrow, Collateral, Market, Position, Reserve


@pytest.fixture
def market() -> Market:
    return Market("Main Market", "MKT", is_primary=True, description="Primary")


@pytest.fixture
def sample_position() -> Position:
    return Position(
        market_name="Main Market",
        address="OBLIGATION123",
        collateral=(Collateral("SOL", 100, 100, 0.8),),
        borrows=(Borrow("USDC", 4000, 1.0),),
        debt_value=4000.0,
    )


@pytest.fixture
def make_position():
    def _make(collateral: Iterable[Collateral], debt_value: float, borrows: Iterable[Borrow] = ()):
        return Position("Main Market", "OB", tuple(collateral), tuple(borrows), debt_value)

    return _make


@pytest.fixture
def fake_kamino():
    """Factory for a duck-typed KaminoClient with canned responses."""

    class _FakeKamino:
        def __init__(self, markets=(), reserves=None, obligations_map=None, prices=None) -> None:
            self._markets = list(markets)
            self._reserves: dict[str, Reserve] = reserves or {}
            self._obligations: dict[str, list[dict]] = obligations_map or {}
            self._prices: dict[str, float] = prices or {}

        def markets(self) -> list[Market]:
            return self._markets

        def reserves(self, market: str) -> dict[str, Reserve]:
            return self._reserves

        def obligations(self, market: str, wallet: str) -> list[dict]:
            return self._obligations.get(market, [])

        def prices(self) -> dict[str, float]:
            return self._prices

    return _FakeKamino


@pytest.fixture
def obligation():
    """Factory for a Kamino obligation record."""

    def _make(*, has_debt=True, deposits=(), borrows=(), debt_value="0", address="OB"):
        return {
            "obligationAddress": address,
            "state": {
                "hasDebt": has_debt,
                "deposits": list(deposits),
                "borrows": list(borrows),
            },
            "refreshedStats": {"userTotalBorrowBorrowFactorAdjusted": debt_value},
        }

    return _make
