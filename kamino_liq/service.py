"""Orchestration: combine the REST API, the on-chain reads, and live prices into
typed Position objects for a wallet."""

from __future__ import annotations

from collections.abc import Iterator

from . import config
from .api import KaminoClient
from .chain import SolanaRPC, enrich_reserves
from .models import Borrow, Collateral, Market, Position, Reserve


def load_positions(
    client: KaminoClient,
    rpc: SolanaRPC,
    wallet: str,
    markets: list[Market],
) -> Iterator[tuple[Market, Position]]:
    """Yield (market, position) for every active obligation across `markets`."""
    prices = client.prices()
    for market in markets:
        obligations = [o for o in client.obligations(market.address, wallet) if _is_active(o)]
        if not obligations:
            continue
        reserves = client.reserves(market.address)
        for obligation in obligations:
            yield market, _build_position(obligation, market, reserves, prices, rpc)


def _is_active(obligation: dict) -> bool:
    state = obligation["state"]
    return state["hasDebt"] or bool(_used(state["deposits"], "depositReserve", "depositedAmount"))


def _used(rows: list[dict], reserve_key: str, amount_key: str) -> list[dict]:
    return [r for r in rows if r[reserve_key] != config.EMPTY_PUBKEY and r[amount_key] != "0"]


def _build_position(
    obligation: dict,
    market: Market,
    reserves: dict[str, Reserve],
    prices: dict[str, float],
    rpc: SolanaRPC,
) -> Position:
    state = obligation["state"]
    deposits = _used(state["deposits"], "depositReserve", "depositedAmount")
    borrows = _used(state["borrows"], "borrowReserve", "borrowedAmountSf")

    used_addresses = {d["depositReserve"] for d in deposits} | {b["borrowReserve"] for b in borrows}
    enriched = enrich_reserves(rpc, [reserves[address] for address in used_addresses])

    collateral = tuple(_collateral(d, enriched[d["depositReserve"]], prices) for d in deposits)
    debt = tuple(_borrow(b, enriched[b["borrowReserve"]], prices) for b in borrows)
    debt_value = float(obligation["refreshedStats"]["userTotalBorrowBorrowFactorAdjusted"])
    return Position(market.name, obligation["obligationAddress"], collateral, debt, debt_value)


def _collateral(deposit: dict, reserve: Reserve, prices: dict[str, float]) -> Collateral:
    return Collateral(
        symbol=reserve.symbol,
        amount=int(deposit["depositedAmount"]) / 10**reserve.decimals,
        price=prices.get(reserve.mint, 0.0),
        liquidation_threshold=reserve.liquidation_threshold,
    )


def _borrow(borrow: dict, reserve: Reserve, prices: dict[str, float]) -> Borrow:
    raw = int(borrow["borrowedAmountSf"]) / config.FRACTION_SCALE
    return Borrow(
        symbol=reserve.symbol,
        amount=raw / 10**reserve.decimals,
        price=prices.get(reserve.mint, 0.0),
    )
