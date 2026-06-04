"""Tests for the Solana RPC client and on-chain decoding."""

import base64
from unittest.mock import MagicMock

import pytest

from kamino_liq import config
from kamino_liq.chain import SolanaRPC, enrich_reserves
from kamino_liq.models import Reserve


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _reserve_account(max_ltv_pct: int, liq_pct: int) -> dict:
    raw = bytearray(config.RESERVE_LIQ_THRESHOLD_OFFSET + 1)
    raw[config.RESERVE_LTV_OFFSET] = max_ltv_pct
    raw[config.RESERVE_LIQ_THRESHOLD_OFFSET] = liq_pct
    return {"data": [base64.b64encode(bytes(raw)).decode(), "base64"]}


def _mint_account(decimals: int) -> dict:
    raw = bytearray(config.MINT_DECIMALS_OFFSET + 1)
    raw[config.MINT_DECIMALS_OFFSET] = decimals
    return {"data": [base64.b64encode(bytes(raw)).decode(), "base64"]}


class StubRPC:
    """A SolanaRPC stand-in returning fixed account data."""

    def __init__(self, accounts):
        self._accounts = accounts

    def get_accounts(self, pubkeys):
        return self._accounts


# --- SolanaRPC ------------------------------------------------------------- #
def test_call_raises_on_rpc_error() -> None:
    session = MagicMock()
    session.post.return_value = _response({"error": {"code": -1, "message": "boom"}})
    with pytest.raises(RuntimeError, match="RPC error"):
        SolanaRPC(session=session)._call("getX", [])


def test_get_accounts_chunks_requests() -> None:
    def post(url, json, timeout):
        chunk = json["params"][0]
        return _response({"result": {"value": [_mint_account(6)] * len(chunk)}})

    session = MagicMock()
    session.post.side_effect = post
    accounts = SolanaRPC(session=session).get_accounts(["k"] * 150)
    assert len(accounts) == 150
    assert session.post.call_count == 2  # 100 + 50


def test_cluster_nodes_filters_and_defaults_version() -> None:
    session = MagicMock()
    session.post.return_value = _response(
        {
            "result": [
                {"pubkey": "P1", "rpc": "1.2.3.4:8899", "version": "1.0"},
                {"pubkey": "P2", "rpc": None, "version": "1.0"},  # no RPC -> dropped
                {"pubkey": "P3", "rpc": "5.6.7.8:1", "version": None},  # version default
            ]
        }
    )
    nodes = SolanaRPC(session=session).cluster_nodes()
    assert [n.pubkey for n in nodes] == ["P1", "P3"]
    assert nodes[1].version == "?"


# --- enrich_reserves ------------------------------------------------------- #
def test_enrich_reserves_success() -> None:
    reserves = [Reserve("R", "SOL", "M", max_ltv=0.7)]
    rpc = StubRPC([_reserve_account(70, 75), _mint_account(9)])
    enriched = enrich_reserves(rpc, reserves)
    assert enriched["R"].liquidation_threshold == 0.75
    assert enriched["R"].decimals == 9


def test_enrich_reserves_detects_layout_change() -> None:
    reserves = [Reserve("R", "SOL", "M", max_ltv=0.7)]
    rpc = StubRPC([_reserve_account(99, 75), _mint_account(9)])  # 99 != 70
    with pytest.raises(RuntimeError, match="layout changed"):
        enrich_reserves(rpc, reserves)


def test_enrich_reserves_skips_check_for_disabled_reserve() -> None:
    reserves = [Reserve("R", "X", "M", max_ltv=0.0)]  # maxLtv 0 -> no cross-check
    rpc = StubRPC([_reserve_account(5, 10), _mint_account(6)])
    enriched = enrich_reserves(rpc, reserves)
    assert enriched["R"].liquidation_threshold == 0.10


def test_enrich_reserves_raises_on_missing_account() -> None:
    reserves = [Reserve("R", "SOL", "M", max_ltv=0.7)]
    rpc = StubRPC([None, _mint_account(9)])
    with pytest.raises(RuntimeError, match="not found on-chain"):
        enrich_reserves(rpc, reserves)
