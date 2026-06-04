"""Tests for KaminoClient with a mocked HTTP session."""

from unittest.mock import MagicMock

from kamino_liq.api import KaminoClient


def make_client(payload, base_url="https://api.example.com"):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session = MagicMock()
    session.get.return_value = response
    return KaminoClient(base_url=base_url, session=session), session


def test_markets_parsed() -> None:
    client, session = make_client(
        [{"name": "Main", "lendingMarket": "MKT", "isPrimary": True, "description": "d"}]
    )
    markets = client.markets()
    assert markets[0].address == "MKT"
    assert session.get.call_args.args[0].endswith("/v2/kamino-market")


def test_obligations_url() -> None:
    client, session = make_client([{"obligationAddress": "OB"}])
    assert client.obligations("MKT", "WALLET") == [{"obligationAddress": "OB"}]
    assert session.get.call_args.args[0].endswith("/kamino-market/MKT/users/WALLET/obligations")


def test_reserves_indexed_by_address() -> None:
    client, _ = make_client(
        [{"reserve": "R", "liquidityToken": "SOL", "liquidityTokenMint": "M", "maxLtv": "0.7"}]
    )
    reserves = client.reserves("MKT")
    assert reserves["R"].symbol == "SOL"
    assert reserves["R"].max_ltv == 0.7


def test_prices_mapped_by_mint() -> None:
    client, session = make_client([{"mint": "M", "usdPrice": "1.5", "token": "X"}])
    assert client.prices() == {"M": 1.5}
    assert session.get.call_args.kwargs["params"] == {"env": "mainnet-beta", "source": "scope"}


def test_base_url_is_trimmed_and_default_session_built() -> None:
    client, _ = make_client([], base_url="https://api.example.com/")
    assert client.base_url == "https://api.example.com"
    # No session passed -> a default one with a User-Agent is created.
    default = KaminoClient()
    assert "User-Agent" in default.session.headers
