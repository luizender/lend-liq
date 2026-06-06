"""Tests for AaveClient with a mocked HTTP session."""

from unittest.mock import MagicMock

import pytest

from lend_liq.aave.api import AaveApiError, AaveClient


def make_client(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session = MagicMock()
    session.post.return_value = response
    return AaveClient(session=session), session


def test_markets_posts_chains_and_user():
    client, session = make_client({"data": {"markets": [{"address": "0xM"}]}})
    assert client.markets([1, 137], "0xU") == [{"address": "0xM"}]
    body = session.post.call_args.kwargs["json"]
    assert body["variables"]["req"] == {"chainIds": [1, 137], "user": "0xU"}
    assert "markets(request" in body["query"]


def test_user_positions_combines_supplies_and_borrows():
    client, session = make_client({"data": {"userSupplies": [{"s": 1}], "userBorrows": [{"b": 2}]}})
    out = client.user_positions([{"address": "0xM", "chainId": 1}], "0xU")
    assert out == {"supplies": [{"s": 1}], "borrows": [{"b": 2}]}
    request = session.post.call_args.kwargs["json"]["variables"]
    assert request["supplies"]["collateralsOnly"] is False
    assert request["supplies"]["orderBy"] == {"balance": "DESC"}
    assert request["borrows"]["orderBy"] == {"debt": "DESC"}


def test_errors_payload_raises():
    client, _ = make_client({"errors": [{"message": "bad request"}]})
    with pytest.raises(AaveApiError):
        client.markets([1], "0xU")


def test_default_session_has_user_agent():
    client = AaveClient()
    assert "User-Agent" in client.session.headers
    assert client.base_url.endswith("/graphql")
