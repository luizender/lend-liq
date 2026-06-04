"""Tests for the orchestration layer (wallet -> Position objects)."""

from kamino_liq import service
from kamino_liq.config import EMPTY_PUBKEY, FRACTION_SCALE
from kamino_liq.models import Market, Reserve

MARKET = Market("Main Market", "MKT", is_primary=True, description="")
RESERVES = {
    "resSOL": Reserve("resSOL", "SOL", "mintSOL", max_ltv=0.7),
    "resUSDC": Reserve("resUSDC", "USDC", "mintUSDC", max_ltv=0.8),
}
ENRICHED = {
    "resSOL": Reserve("resSOL", "SOL", "mintSOL", 0.7, liquidation_threshold=0.75, decimals=9),
    "resUSDC": Reserve("resUSDC", "USDC", "mintUSDC", 0.8, liquidation_threshold=0.85, decimals=6),
}
PRICES = {"mintSOL": 100.0, "mintUSDC": 1.0}


def _patch_enrich(monkeypatch):
    monkeypatch.setattr(service, "enrich_reserves", lambda rpc, reserves: ENRICHED)


def test_build_position_amounts_and_prices(monkeypatch, fake_kamino, obligation):
    _patch_enrich(monkeypatch)
    ob = obligation(
        has_debt=True,
        debt_value="5.0",
        deposits=[
            {"depositReserve": "resSOL", "depositedAmount": str(10 * 10**9)},
            {"depositReserve": EMPTY_PUBKEY, "depositedAmount": "0"},  # filtered out
        ],
        borrows=[{"borrowReserve": "resUSDC", "borrowedAmountSf": str(5 * 10**6 * FRACTION_SCALE)}],
    )
    client = fake_kamino(
        markets=[MARKET], reserves=RESERVES, obligations_map={"MKT": [ob]}, prices=PRICES
    )

    (result,) = list(service.load_positions(client, rpc=None, wallet="W", markets=[MARKET]))
    market, position = result
    assert market is MARKET
    assert position.collateral[0].symbol == "SOL"
    assert position.collateral[0].amount == 10
    assert position.collateral[0].value == 1000
    assert position.collateral[0].liquidation_threshold == 0.75
    assert position.borrows[0].amount == 5
    assert position.debt_value == 5.0


def test_market_without_active_obligations_is_skipped(monkeypatch, fake_kamino, obligation):
    _patch_enrich(monkeypatch)
    inactive = obligation(has_debt=False, deposits=[], borrows=[])
    client = fake_kamino(markets=[MARKET], reserves=RESERVES, obligations_map={"MKT": [inactive]})
    assert list(service.load_positions(client, None, "W", [MARKET])) == []


def test_is_active_variants(obligation):
    with_debt = obligation(has_debt=True, deposits=[], borrows=[])
    only_deposit = obligation(
        has_debt=False, deposits=[{"depositReserve": "resSOL", "depositedAmount": "1"}]
    )
    empty = obligation(has_debt=False, deposits=[], borrows=[])
    assert service._is_active(with_debt) is True
    assert service._is_active(only_deposit) is True
    assert service._is_active(empty) is False
