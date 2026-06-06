"""Tests for KaminoClient with a mocked HTTP session."""

from unittest.mock import MagicMock

from lend_liq.kamino.api import KaminoClient


def make_client(payload, base_url="https://api.example.com"):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session = MagicMock()
    session.get.return_value = response
    return KaminoClient(base_url=base_url, session=session), session


def test_market_url() -> None:
    client, session = make_client({"name": "Main", "lendingMarket": "MKT"})
    result = client.market("MKT")
    assert result["name"] == "Main"
    assert session.get.call_args.args[0].endswith("/v2/kamino-market/MKT")


def test_portfolio_returns_lending_loans() -> None:
    client, session = make_client({"lending": [{"address": "OB", "marketAddress": "MKT"}]})
    assert client.portfolio("WALLET") == [{"address": "OB", "marketAddress": "MKT"}]
    assert session.get.call_args.args[0].endswith("/portfolio/WALLET")


def test_portfolio_empty_without_lending_section() -> None:
    client, _ = make_client({})
    assert client.portfolio("WALLET") == []


def test_loan_url() -> None:
    client, session = make_client({"loanInfo": {}})
    assert client.loan("OB") == {"loanInfo": {}}
    assert session.get.call_args.args[0].endswith("/klend/loans/OB")


def test_base_url_is_trimmed_and_default_session_built() -> None:
    client, _ = make_client([], base_url="https://api.example.com/")
    assert client.base_url == "https://api.example.com"
    # No session passed -> a default one with a User-Agent is created.
    default = KaminoClient()
    assert "User-Agent" in default.session.headers


def test_reserves_url() -> None:
    client, session = make_client([])
    client.reserves("MKT")
    assert session.get.call_args.args[0].endswith("/kamino-market/MKT/reserves/metrics")


def test_reserve_config_url() -> None:
    client, session = make_client([])
    client.reserve_config("MKT", "RSV")
    url = session.get.call_args.args[0]
    assert url.endswith("/kamino-market/MKT/reserves/RSV/metrics/history")
    params = session.get.call_args.kwargs["params"]
    assert params["env"] == "mainnet-beta"
    assert params["frequency"] == "day"
    assert "start" in params
    assert "end" in params
