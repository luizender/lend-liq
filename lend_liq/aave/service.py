"""Orchestration: turn an Aave user address into typed Position objects from the
AaveKit GraphQL API. The markets query supplies each reserve's liquidation
threshold (and the user's eMode override); userSupplies/userBorrows supply the
actual priced positions. Aave has no borrow factor, so a position's debt_value is
simply the USD sum of its borrows.

Markets are keyed by ``(chainId, address)`` rather than address alone: the same
pool address is reused across chains (e.g. Optimism, Polygon, Arbitrum and
Avalanche share one), so address alone collides when scanning every chain."""

from __future__ import annotations

# pylint: disable=duplicate-code
from collections import defaultdict
from collections.abc import Iterator

from ..models import Borrow, Collateral, Position, ReserveInfo
from .api import AaveClient

MarketKey = tuple[int, str]


def load_positions(client: AaveClient, user: str, chain_ids: list[int]) -> Iterator[Position]:  # pylint: disable=too-many-locals
    """Yield a Position for each Aave market across ``chain_ids`` where ``user``
    holds collateral or debt."""
    markets = client.markets(chain_ids, user)
    thresholds = _threshold_map(markets)
    names = {_market_key(market): market["name"] for market in markets}
    inputs = [
        {"address": market["address"], "chainId": market["chain"]["chainId"]} for market in markets
    ]
    positions = client.user_positions(inputs, user)
    supplies = _by_market(positions["supplies"])
    borrows = _by_market(positions["borrows"])
    for key, name in names.items():
        collateral = _collateral(supplies[key], thresholds)
        debt = tuple(_borrow(b) for b in borrows[key])
        if not collateral and not debt:
            continue
        debt_value = sum(float(b["debt"]["usd"]) for b in borrows[key])
        market_id = f"{key[0]}:{key[1]}"
        yield Position(name, key[1], collateral, debt, debt_value, market_id=market_id)


def _market_key(market: dict) -> MarketKey:
    """Identify a market by ``(chainId, pool address)``; the address alone is reused
    across chains."""
    return market["chain"]["chainId"], market["address"]


def _threshold_map(markets: list[dict]) -> dict[tuple[int, str, str], float]:
    thresholds: dict[tuple[int, str, str], float] = {}
    for market in markets:
        chain_id, address = _market_key(market)
        for reserve in market["reserves"]:
            key = (chain_id, address, reserve["underlyingToken"]["address"].lower())
            thresholds[key] = _effective_lt(reserve)
    return thresholds


def _effective_lt(reserve: dict) -> float:
    """The liquidation threshold that applies to the user: the eMode category's when
    the user has eMode enabled for this reserve, otherwise the reserve's own."""
    emode = (reserve.get("userState") or {}).get("emode")
    info = emode or reserve["supplyInfo"]
    return float(info["liquidationThreshold"]["value"])


def _by_market(rows: list[dict]) -> dict[MarketKey, list[dict]]:
    grouped: dict[MarketKey, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[_market_key(row["market"])].append(row)
    return grouped


def _collateral(
    supplies: list[dict], thresholds: dict[tuple[int, str, str], float]
) -> tuple[Collateral, ...]:
    return tuple(
        Collateral(
            supply["currency"]["symbol"],
            float(supply["balance"]["amount"]["value"]),
            float(supply["balance"]["usdPerToken"]),
            thresholds[(*_market_key(supply["market"]), supply["currency"]["address"].lower())],
        )
        for supply in supplies
        if supply["isCollateral"]
    )


def _borrow(borrow: dict) -> Borrow:
    debt = borrow["debt"]
    return Borrow(
        borrow["currency"]["symbol"], float(debt["amount"]["value"]), float(debt["usdPerToken"])
    )


def resolve_reserve(  # pylint: disable=too-many-locals
    client: AaveClient, user: str, market_id: str, symbol: str
) -> ReserveInfo | None:
    """Find a reserve configuration by symbol and construct ReserveInfo."""
    try:
        chain_id_str, market_address = market_id.split(":", 1)
        chain_id = int(chain_id_str)
    except ValueError:
        return None

    markets = client.markets([chain_id], user)
    matching_market = None
    for m in markets:
        if m["address"].lower() == market_address.lower():
            matching_market = m
            break
    if not matching_market:
        return None

    matching_reserve = None
    for reserve in matching_market["reserves"]:
        if reserve["underlyingToken"]["symbol"].upper() == symbol.upper():
            matching_reserve = reserve
            break
    if not matching_reserve:
        return None

    canonical_symbol = matching_reserve["underlyingToken"]["symbol"]
    price = float(matching_reserve.get("usdExchangeRate", 0.0))
    liquidation_threshold = _effective_lt(matching_reserve)
    borrow_factor = 1.0

    return ReserveInfo(
        symbol=canonical_symbol,
        price=price,
        liquidation_threshold=liquidation_threshold,
        borrow_factor=borrow_factor,
    )
