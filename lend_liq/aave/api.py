"""Read-only client for the public Aave (AaveKit) GraphQL API.

Two queries cover a position: ``markets`` carries the per-reserve liquidation
thresholds (and the user's eMode override), and ``userSupplies``/``userBorrows``
carry the actual priced positions. Both are plain HTTP POSTs — no key, no RPC."""

from __future__ import annotations

import requests

from .. import config

_MARKETS_QUERY = """query Markets($req: MarketsRequest!) {
  markets(request: $req) {
    address
    name
    chain { chainId }
    userState { healthFactor eModeEnabled }
    reserves {
      underlyingToken { symbol address }
      supplyInfo { liquidationThreshold { value } }
      userState { emode { liquidationThreshold { value } } }
      usdExchangeRate
    }
  }
}"""

_POSITIONS_QUERY = """query Positions(
  $supplies: UserSuppliesRequest!
  $borrows: UserBorrowsRequest!
) {
  userSupplies(request: $supplies) {
    market { address chain { chainId } }
    currency { symbol address }
    balance { amount { value } usdPerToken usd }
    isCollateral
  }
  userBorrows(request: $borrows) {
    market { address chain { chainId } }
    currency { symbol address }
    debt { amount { value } usdPerToken usd }
  }
}"""


class AaveApiError(RuntimeError):
    """The Aave GraphQL API returned an ``errors`` payload."""


class AaveClient:
    """Read-only client for the public Aave (AaveKit) GraphQL API."""

    def __init__(
        self, base_url: str = config.AAVE_API, session: requests.Session | None = None
    ) -> None:
        """Create a client, optionally reusing an existing HTTP session."""
        self.base_url = base_url
        self.session = session or _new_session()

    def _post(self, query: str, variables: dict) -> dict:
        response = self.session.post(
            self.base_url,
            json={"query": query, "variables": variables},
            timeout=config.HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise AaveApiError(payload["errors"])
        return payload["data"]

    def markets(self, chain_ids: list[int], user: str) -> list[dict]:
        """Return every Aave market across ``chain_ids`` with its chain id, its
        reserves' liquidation thresholds, and ``user``'s per-reserve eMode state."""
        data = self._post(_MARKETS_QUERY, {"req": {"chainIds": chain_ids, "user": user}})
        return data["markets"]

    def user_positions(self, markets: list[dict], user: str) -> dict:
        """Return ``user``'s supplies and borrows across ``markets`` (each a
        ``{"address", "chainId"}`` input), as ``{"supplies": [...], "borrows": [...]}``."""
        variables = {
            "supplies": {
                "markets": markets,
                "user": user,
                "collateralsOnly": False,
                "orderBy": {"balance": "DESC"},
            },
            "borrows": {"markets": markets, "user": user, "orderBy": {"debt": "DESC"}},
        }
        data = self._post(_POSITIONS_QUERY, variables)
        return {"supplies": data["userSupplies"], "borrows": data["userBorrows"]}


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    return session
