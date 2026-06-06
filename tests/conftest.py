"""Shared test fixtures: in-memory fakes so no test touches the network."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from lend_liq.models import Borrow, Collateral, Position


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
        def __init__(self, portfolio=(), loans=None, market_names=None) -> None:
            self._portfolio: list[dict] = list(portfolio)
            self._loans: dict[str, dict] = loans or {}
            self._market_names: dict[str, str] = market_names or {}

        def market(self, pubkey: str) -> dict:
            return {"name": self._market_names.get(pubkey, "Main Market")}

        def portfolio(self, wallet: str) -> list[dict]:
            return self._portfolio

        def loan(self, obligation: str) -> dict:
            return self._loans[obligation]

    return _FakeKamino


@pytest.fixture
def loan_detail():
    """Factory for a Kamino /klend/loans/{pubkey} response."""

    def _make(*, deposits=(), borrows=()):
        return {
            "loanInfo": {
                "collateral": {"deposits": list(deposits)},
                "debt": {"borrows": list(borrows)},
            }
        }

    return _make


@pytest.fixture
def fake_aave():
    """Factory for a duck-typed AaveClient with canned GraphQL responses."""

    class _FakeAave:
        def __init__(self, markets=(), supplies=(), borrows=()) -> None:
            self._markets: list[dict] = list(markets)
            self._supplies: list[dict] = list(supplies)
            self._borrows: list[dict] = list(borrows)

        def markets(self, chain_ids: list[int], user: str) -> list[dict]:
            return self._markets

        def user_positions(self, markets: list[dict], user: str) -> dict:
            return {"supplies": self._supplies, "borrows": self._borrows}

    return _FakeAave
