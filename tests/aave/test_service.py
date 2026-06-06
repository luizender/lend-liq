"""Tests for the Aave orchestration layer (GraphQL -> Position objects)."""

from lend_liq.aave import service as aave_service

WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
MKT = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"


def _reserve(symbol, address, lt, emode_lt=None, usd_exchange_rate=0.0):
    emode = {"liquidationThreshold": {"value": str(emode_lt)}} if emode_lt is not None else None
    return {
        "underlyingToken": {"symbol": symbol, "address": address},
        "supplyInfo": {"liquidationThreshold": {"value": str(lt)}},
        "userState": {"emode": emode},
        "usdExchangeRate": str(usd_exchange_rate),
    }


def _market(address=MKT, name="AaveV3Ethereum", reserves=(), health_factor=None, chain_id=1):
    return {
        "address": address,
        "name": name,
        "chain": {"chainId": chain_id},
        "userState": {"healthFactor": health_factor, "eModeEnabled": False},
        "reserves": list(reserves),
    }


def _supply(symbol, address, amount, price, is_collateral=True, market=MKT, chain_id=1):
    return {
        "market": {"address": market, "chain": {"chainId": chain_id}},
        "currency": {"symbol": symbol, "address": address},
        "balance": {
            "amount": {"value": str(amount)},
            "usdPerToken": str(price),
            "usd": str(amount * price),
        },
        "isCollateral": is_collateral,
    }


def _borrow(symbol, address, amount, price, market=MKT, chain_id=1):
    return {
        "market": {"address": market, "chain": {"chainId": chain_id}},
        "currency": {"symbol": symbol, "address": address},
        "debt": {
            "amount": {"value": str(amount)},
            "usdPerToken": str(price),
            "usd": str(amount * price),
        },
    }


def test_builds_position_with_threshold_and_plain_debt(fake_aave):
    client = fake_aave(
        markets=[_market(reserves=[_reserve("WETH", WETH, 0.83)])],
        supplies=[_supply("WETH", WETH, 1.5, 1600.0)],
        borrows=[_borrow("USDC", USDC, 1000, 1.0)],
    )

    (position,) = list(aave_service.load_positions(client, "0xU", [1]))
    assert position.market_name == "AaveV3Ethereum"
    assert position.market_id == f"1:{MKT}"
    weth = position.collateral[0]
    assert (weth.symbol, weth.amount, weth.price, weth.liquidation_threshold) == (
        "WETH",
        1.5,
        1600.0,
        0.83,
    )
    assert position.debt_value == 1000.0  # no borrow factor
    # health factor reconstructs from the model: 1.5*1600*0.83 / 1000
    assert position.health_factor == 1.992


def test_emode_threshold_overrides_reserve_threshold(fake_aave):
    client = fake_aave(
        markets=[_market(reserves=[_reserve("WETH", WETH, 0.83, emode_lt=0.93)])],
        supplies=[_supply("WETH", WETH, 1.0, 1600.0)],
        borrows=[_borrow("USDC", USDC, 100, 1.0)],
    )

    (position,) = list(aave_service.load_positions(client, "0xU", [1]))
    assert position.collateral[0].liquidation_threshold == 0.93


def test_non_collateral_supply_excluded(fake_aave):
    client = fake_aave(
        markets=[_market(reserves=[_reserve("WETH", WETH, 0.83)])],
        supplies=[_supply("WETH", WETH, 1.0, 1600.0, is_collateral=False)],
        borrows=[_borrow("USDC", USDC, 100, 1.0)],
    )

    (position,) = list(aave_service.load_positions(client, "0xU", [1]))
    assert position.collateral == ()


def test_debt_value_is_plain_usd_sum(fake_aave):
    client = fake_aave(
        markets=[_market(reserves=[_reserve("WETH", WETH, 0.83)])],
        supplies=[_supply("WETH", WETH, 5.0, 1600.0)],
        borrows=[_borrow("USDC", USDC, 1000, 1.0), _borrow("WETH", WETH, 1, 1600.0)],
    )

    (position,) = list(aave_service.load_positions(client, "0xU", [1]))
    assert position.debt_value == 2600.0


def test_market_without_positions_is_skipped(fake_aave):
    client = fake_aave(markets=[_market(reserves=[_reserve("WETH", WETH, 0.83)])])
    assert list(aave_service.load_positions(client, "0xU", [1])) == []


def test_groups_positions_by_market(fake_aave):
    other = "0x4e033931ad43597d96D6bcc25c280717730B58B1"
    client = fake_aave(
        markets=[
            _market(reserves=[_reserve("WETH", WETH, 0.83)]),
            _market(
                address=other, name="AaveV3EthereumLido", reserves=[_reserve("WETH", WETH, 0.85)]
            ),
        ],
        supplies=[_supply("WETH", WETH, 1, 1600.0), _supply("WETH", WETH, 2, 1600.0, market=other)],
        borrows=[_borrow("USDC", USDC, 100, 1.0, market=other)],
    )

    positions = {p.market_name: p for p in aave_service.load_positions(client, "0xU", [1])}
    assert set(positions) == {"AaveV3Ethereum", "AaveV3EthereumLido"}
    assert positions["AaveV3Ethereum"].debt_value == 0.0
    assert positions["AaveV3EthereumLido"].collateral[0].liquidation_threshold == 0.85


def test_same_pool_address_on_different_chains_stays_separate(fake_aave):
    # One pool address is reused across chains (Arbitrum, Polygon, ...); scanning
    # both must keep the positions distinct rather than collapsing them by address.
    shared = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
    client = fake_aave(
        markets=[
            _market(
                address=shared,
                name="AaveV3Arbitrum",
                chain_id=42161,
                reserves=[_reserve("WETH", WETH, 0.83)],
            ),
            _market(
                address=shared,
                name="AaveV3Polygon",
                chain_id=137,
                reserves=[_reserve("WETH", WETH, 0.85)],
            ),
        ],
        supplies=[
            _supply("WETH", WETH, 1, 1600.0, market=shared, chain_id=42161),
            _supply("WETH", WETH, 2, 1600.0, market=shared, chain_id=137),
        ],
        borrows=[_borrow("USDC", USDC, 100, 1.0, market=shared, chain_id=137)],
    )

    positions = {p.market_name: p for p in aave_service.load_positions(client, "0xU", [42161, 137])}
    assert set(positions) == {"AaveV3Arbitrum", "AaveV3Polygon"}
    assert positions["AaveV3Arbitrum"].collateral[0].amount == 1
    assert positions["AaveV3Arbitrum"].collateral[0].liquidation_threshold == 0.83
    assert positions["AaveV3Arbitrum"].debt_value == 0.0
    assert positions["AaveV3Polygon"].collateral[0].amount == 2
    assert positions["AaveV3Polygon"].collateral[0].liquidation_threshold == 0.85
    assert positions["AaveV3Polygon"].debt_value == 100.0


def test_resolve_reserve_aave(fake_aave) -> None:
    client = fake_aave(
        markets=[_market(reserves=[_reserve("WETH", WETH, 0.85, usd_exchange_rate=1600.0)])]
    )

    # Found case (case-insensitive search):
    res = aave_service.resolve_reserve(client, "0xU", f"1:{MKT}", "weth")
    assert res is not None
    assert res.symbol == "WETH"
    assert res.price == 1600.0
    assert res.borrow_factor == 1.0
    assert res.liquidation_threshold == 0.85

    # Not found case:
    assert aave_service.resolve_reserve(client, "0xU", f"1:{MKT}", "BONK") is None

    # Bad market_id format:
    assert aave_service.resolve_reserve(client, "0xU", "invalid", "weth") is None

    # Market not found:
    assert aave_service.resolve_reserve(client, "0xU", "1:0xNonExistent", "weth") is None
