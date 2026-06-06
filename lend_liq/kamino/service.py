"""Orchestration: turn a wallet into typed Position objects from the Kamino REST
API. The portfolio endpoint lists a wallet's loans across every market in one
call; each loan's fully-priced per-asset detail then comes from the loan
endpoint, and the market endpoint supplies its human-readable name."""

from __future__ import annotations

from collections.abc import Iterator

from ..models import Borrow, Collateral, Position, ReserveInfo
from .api import KaminoClient


def load_positions(client: KaminoClient, wallet: str) -> Iterator[Position]:
    """Yield a Position for each of ``wallet``'s Kamino Lend loans."""
    names: dict[str, str] = {}
    for loan in client.portfolio(wallet):
        market = loan["marketAddress"]
        if market not in names:
            names[market] = client.market(market)["name"]
        detail = client.loan(loan["address"])
        yield _build_position(names[market], loan["address"], detail, market)


def _build_position(market_name: str, address: str, detail: dict, market_id: str) -> Position:
    info = detail["loanInfo"]
    borrows = info["debt"]["borrows"]
    collateral = tuple(_collateral(d) for d in info["collateral"]["deposits"])
    debt = tuple(_borrow(b) for b in borrows)
    debt_value = sum(float(b["tokenValue"]) * float(b["borrowFactor"]) for b in borrows)
    return Position(market_name, address, collateral, debt, debt_value, market_id=market_id)


def _collateral(deposit: dict) -> Collateral:
    return Collateral(
        symbol=deposit["tokenName"],
        amount=float(deposit["tokenAmount"]),
        price=float(deposit["tokenPrice"]),
        liquidation_threshold=float(deposit["liquidationLtv"]),
    )


def _borrow(borrow: dict) -> Borrow:
    return Borrow(
        symbol=borrow["tokenName"],
        amount=float(borrow["tokenAmount"]),
        price=float(borrow["tokenPrice"]),
    )


def resolve_reserve(client: KaminoClient, market_id: str, symbol: str) -> ReserveInfo | None:
    """Find a reserve configuration by symbol and construct ReserveInfo."""
    reserves_list = client.reserves(market_id)
    matching_reserve = None
    for item in reserves_list:
        if item.get("liquidityToken", "").upper() == symbol.upper():
            matching_reserve = item
            break
    if not matching_reserve:
        return None

    canonical_symbol = matching_reserve["liquidityToken"]
    reserve_pubkey = matching_reserve["reserve"]

    history_data = client.reserve_config(market_id, reserve_pubkey)
    if not history_data or not isinstance(history_data, dict):
        return None
    history = history_data.get("history")
    if not history or not isinstance(history, list):
        return None

    latest_point = history[-1]
    metrics = latest_point.get("metrics")
    if not metrics:
        return None

    price = float(metrics.get("assetPriceUSD", 0.0))
    borrow_factor = float(metrics.get("borrowFactor", 100.0)) / 100.0
    liquidation_threshold = float(metrics.get("liquidationThreshold", 0.0))

    return ReserveInfo(
        symbol=canonical_symbol,
        price=price,
        liquidation_threshold=liquidation_threshold,
        borrow_factor=borrow_factor,
    )
