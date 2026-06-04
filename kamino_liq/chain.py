"""Solana RPC access for the two numbers the Kamino REST API doesn't expose:
each reserve's liquidation threshold and each token's decimals. Both are read
from on-chain accounts at fixed byte offsets and the reserve layout is
cross-checked against the API's maxLtv (see config.py)."""

from __future__ import annotations

import base64
from dataclasses import replace

import requests

from . import config
from .models import Reserve, RpcNode


class SolanaRPC:
    """Minimal JSON-RPC client for a Solana node."""

    def __init__(
        self, url: str = config.DEFAULT_RPC, session: requests.Session | None = None
    ) -> None:
        """Create a client, optionally reusing an existing HTTP session."""
        self.url = url
        self.session = session or requests.Session()

    def _call(self, method: str, params: list) -> dict | list:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        response = self.session.post(self.url, json=payload, timeout=config.RPC_TIMEOUT)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body["result"]

    def get_accounts(self, pubkeys: list[str]) -> list[dict | None]:
        """getMultipleAccounts, transparently chunked under the 100-key limit."""
        accounts: list[dict | None] = []
        for start in range(0, len(pubkeys), config.RPC_MAX_ACCOUNTS):
            chunk = pubkeys[start : start + config.RPC_MAX_ACCOUNTS]
            result = self._call("getMultipleAccounts", [chunk, {"encoding": "base64"}])
            accounts.extend(result["value"])
        return accounts

    def cluster_nodes(self) -> list[RpcNode]:
        """Validators on the cluster that advertise a public RPC port."""
        return [
            RpcNode(pubkey=n["pubkey"], rpc=n["rpc"], version=n.get("version") or "?")
            for n in self._call("getClusterNodes", [])
            if n.get("rpc")
        ]


def enrich_reserves(rpc: SolanaRPC, reserves: list[Reserve]) -> dict[str, Reserve]:
    """Augment reserves with on-chain liquidation_threshold and decimals.

    Reserve accounts and their token mints are read in a single batched call.
    """
    mints = [r.mint for r in reserves]
    accounts = rpc.get_accounts([r.address for r in reserves] + mints)
    reserve_accounts = accounts[: len(reserves)]
    mint_accounts = accounts[len(reserves) :]

    enriched: dict[str, Reserve] = {}
    for reserve, reserve_account, mint_account in zip(
        reserves, reserve_accounts, mint_accounts, strict=True
    ):
        raw = _account_data(reserve_account, reserve.address)
        _check_layout(reserve, raw)
        decimals = _account_data(mint_account, reserve.mint)[config.MINT_DECIMALS_OFFSET]
        enriched[reserve.address] = replace(
            reserve,
            liquidation_threshold=raw[config.RESERVE_LIQ_THRESHOLD_OFFSET] / 100,
            decimals=decimals,
        )
    return enriched


def _account_data(account: dict | None, pubkey: str) -> bytes:
    if account is None:
        raise RuntimeError(f"account not found on-chain: {pubkey}")
    return base64.b64decode(account["data"][0])


def _check_layout(reserve: Reserve, raw: bytes) -> None:
    # A disabled reserve has maxLtv 0 and nothing to validate against; skip it.
    if reserve.max_ltv <= 0:
        return
    on_chain_ltv = raw[config.RESERVE_LTV_OFFSET]
    if on_chain_ltv != round(reserve.max_ltv * 100):
        raise RuntimeError(
            f"KLend reserve layout changed for {reserve.symbol} ({reserve.address}): "
            f"byte[{config.RESERVE_LTV_OFFSET}]={on_chain_ltv} but API maxLtv={reserve.max_ltv}. "
            f"Update the offsets in config.py."
        )
