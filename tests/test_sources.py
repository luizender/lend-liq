"""Tests for protocol resolution and address/chain validation."""

import pytest

from lend_liq import config, sources

WALLET = "11111111111111111111111111111111"  # valid base58 (system program)
EVM = "0x" + "ab" * 20


def test_detect_protocol():
    assert sources.detect_protocol(EVM) == "aave"
    assert sources.detect_protocol(WALLET) == "kamino"


def test_resolve_kamino_returns_loader(monkeypatch):
    captured = {}

    def fake_load(client, address):
        captured["args"] = (client, address)
        return ["pos"]

    monkeypatch.setattr(sources, "KaminoClient", lambda: "client")
    monkeypatch.setattr(sources.service, "load_positions", fake_load)

    protocol, loader, reserves = sources.resolve(WALLET, "auto", None)
    assert protocol == "kamino"
    assert loader() == ["pos"]
    assert captured["args"] == ("client", WALLET)


def test_resolve_kamino_rejects_chain():
    with pytest.raises(ValueError, match="only applies to aave"):
        sources.resolve(WALLET, "kamino", "ethereum")


def test_resolve_kamino_rejects_bad_key():
    with pytest.raises(ValueError, match="Solana"):
        sources.resolve("not-a-key!", "kamino", None)


def test_resolve_aave_returns_loader(monkeypatch):
    captured = {}

    def fake_load(client, address, chain_ids):
        captured["args"] = (client, address, chain_ids)
        return ["pos"]

    monkeypatch.setattr(sources, "AaveClient", lambda: "client")
    monkeypatch.setattr(sources.aave_service, "load_positions", fake_load)

    protocol, loader, reserves = sources.resolve(EVM, "auto", "ethereum")
    assert protocol == "aave"
    assert loader() == ["pos"]
    assert captured["args"] == ("client", EVM, [1])


def test_resolve_aave_without_chain_scans_all(monkeypatch):
    captured = {}

    def fake_load(client, address, chain_ids):
        captured["chain_ids"] = chain_ids
        return ["pos"]

    monkeypatch.setattr(sources, "AaveClient", lambda: "client")
    monkeypatch.setattr(sources.aave_service, "load_positions", fake_load)

    _, loader, reserves = sources.resolve(EVM, "aave", None)
    assert loader() == ["pos"]
    assert captured["chain_ids"] == list(config.AAVE_CHAINS.values())


def test_resolve_aave_unknown_chain():
    with pytest.raises(ValueError, match="unknown chain"):
        sources.resolve(EVM, "aave", "solana")


def test_resolve_aave_rejects_bad_address():
    with pytest.raises(ValueError, match="EVM"):
        sources.resolve("0xnothex", "aave", "ethereum")


def test_resolve_unknown_protocol():
    with pytest.raises(ValueError, match="unknown protocol"):
        sources.resolve(WALLET, "compound", None)


def test_resolve_kamino_memoizes_reserves(monkeypatch):
    captured = []

    def fake_resolve_reserve(client, market_id, symbol):
        captured.append((market_id, symbol))
        return "info"

    monkeypatch.setattr(sources.service, "resolve_reserve", fake_resolve_reserve)

    _, _, reserves = sources.resolve(WALLET, "kamino", None)

    assert reserves("M1", "sol") == "info"
    assert reserves("M1", "SOL") == "info"
    assert captured == [("M1", "sol")]


def test_resolve_aave_memoizes_reserves(monkeypatch):
    captured = []

    def fake_resolve_reserve(client, user, market_id, symbol):
        captured.append((user, market_id, symbol))
        return "info"

    monkeypatch.setattr(sources.aave_service, "resolve_reserve", fake_resolve_reserve)

    _, _, reserves = sources.resolve(EVM, "aave", "ethereum")

    assert reserves("M1", "eth") == "info"
    assert reserves("M1", "ETH") == "info"
    assert captured == [(EVM, "M1", "eth")]
