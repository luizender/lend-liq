"""Tests for the orchestration layer (wallet -> Position objects)."""

from lend_liq.kamino import service


def _deposit(name, amount, price, liq):
    return {
        "tokenName": name,
        "tokenAmount": str(amount),
        "tokenPrice": price,
        "liquidationLtv": liq,
    }


def _borrow(name, amount, price, borrow_factor):
    return {
        "tokenName": name,
        "tokenAmount": str(amount),
        "tokenPrice": price,
        "tokenValue": amount * price,
        "borrowFactor": borrow_factor,
    }


def test_load_positions_builds_from_loan_detail(fake_kamino, loan_detail):
    detail = loan_detail(
        deposits=[_deposit("SOL", 10, 100.0, 0.75)],
        borrows=[_borrow("USDC", 500, 1.0, 1)],
    )
    client = fake_kamino(
        portfolio=[{"address": "OB", "marketAddress": "MKT"}], loans={"OB": detail}
    )

    (position,) = list(service.load_positions(client, "W"))
    assert position.market_name == "Main Market"
    assert position.address == "OB"
    assert position.market_id == "MKT"
    sol = position.collateral[0]
    assert (sol.symbol, sol.amount, sol.price, sol.liquidation_threshold) == (
        "SOL",
        10.0,
        100.0,
        0.75,
    )
    assert position.borrows[0].amount == 500.0
    assert position.debt_value == 500.0  # 500 value * borrowFactor 1


def test_debt_value_applies_borrow_factor(fake_kamino, loan_detail):
    detail = loan_detail(
        deposits=[_deposit("SOL", 10, 100.0, 0.75)],
        borrows=[_borrow("ETH", 1, 2000.0, 1.5)],
    )
    client = fake_kamino(
        portfolio=[{"address": "OB", "marketAddress": "MKT"}], loans={"OB": detail}
    )

    (position,) = list(service.load_positions(client, "W"))
    assert position.debt_value == 3000.0  # value 2000 * borrowFactor 1.5


def test_empty_portfolio(fake_kamino):
    client = fake_kamino(portfolio=[], loans={})
    assert list(service.load_positions(client, "W")) == []


def test_market_name_cached(fake_kamino, loan_detail):
    """Two loans in the same market should only call market() once."""
    detail = loan_detail(deposits=[_deposit("SOL", 1, 10.0, 0.8)])
    client = fake_kamino(
        portfolio=[
            {"address": "OB1", "marketAddress": "MKT"},
            {"address": "OB2", "marketAddress": "MKT"},
        ],
        loans={"OB1": detail, "OB2": detail},
    )

    calls = {"n": 0}
    orig_market = client.market

    def counting_market(pubkey):
        calls["n"] += 1
        return orig_market(pubkey)

    client.market = counting_market
    positions = list(service.load_positions(client, "W"))
    assert len(positions) == 2
    assert calls["n"] == 1  # cached


def test_resolve_reserve_kamino(fake_kamino) -> None:
    client = fake_kamino(portfolio=[], loans={})

    client.reserves = lambda m: [
        {"liquidityToken": "SOL", "reserve": "SOL_RSV"},
        {"liquidityToken": "USDC", "reserve": "USDC_RSV"},
        {"liquidityToken": "USDT", "reserve": "USDT_RSV"},
        {"liquidityToken": "PYTH", "reserve": "PYTH_RSV"},
    ]
    client.reserve_config = lambda m, r: (
        {
            "history": [
                {
                    "metrics": {
                        "assetPriceUSD": "100.0",
                        "borrowFactor": "120.0",
                        "liquidationThreshold": "0.8",
                    }
                }
            ]
        }
        if r == "SOL_RSV"
        else (
            {"history": [{}]} if r == "USDT_RSV" else ({"history": []} if r == "PYTH_RSV" else None)
        )
    )

    # Found case (case-insensitive search):
    res = service.resolve_reserve(client, "MKT", "sol")
    assert res is not None
    assert res.symbol == "SOL"
    assert res.price == 100.0
    assert res.borrow_factor == 1.2
    assert res.liquidation_threshold == 0.8

    # Not found case (token not in market reserves):
    assert service.resolve_reserve(client, "MKT", "BONK") is None

    # History not found/invalid:
    assert service.resolve_reserve(client, "MKT", "USDC") is None

    # History exists but metrics missing:
    assert service.resolve_reserve(client, "MKT", "USDT") is None

    # History key present but empty list:
    assert service.resolve_reserve(client, "MKT", "PYTH") is None
