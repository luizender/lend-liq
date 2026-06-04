"""Tests for the domain models and their derived properties."""

from kamino_liq.models import Borrow, Collateral, Market, Position, RpcNode


def test_market_from_api_with_defaults() -> None:
    market = Market.from_api({"name": "X", "lendingMarket": "ADDR"})
    assert market.address == "ADDR"
    assert market.is_primary is False
    assert market.description == ""


def test_collateral_value_and_stability() -> None:
    sol = Collateral("SOL", amount=2, price=50, liquidation_threshold=0.8)
    assert sol.value == 100
    assert sol.weighted_value == 80
    assert sol.is_stable is False
    assert Collateral("usdc", 1, 1, 0.9).is_stable is True


def test_borrow_value() -> None:
    assert Borrow("USDC", 10, 1.0).value == 10


def test_position_net_value_and_has_debt() -> None:
    pos = Position(
        "M", "OB", (Collateral("SOL", 10, 100, 0.8),), (Borrow("USDC", 400, 1.0),), 400.0
    )
    assert pos.has_debt is True
    assert pos.net_value == 600  # 1000 deposit - 400 debt


def test_rpc_node_fields() -> None:
    node = RpcNode("PUB", "1.2.3.4:8899", "2.0")
    assert node.rpc == "1.2.3.4:8899"
