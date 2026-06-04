"""Read-only client for the public Kamino REST API."""

from __future__ import annotations

import requests

from . import config
from .models import Market, Reserve


class KaminoClient:
    """Read-only client for the public Kamino REST API."""

    def __init__(
        self, base_url: str = config.API_BASE, session: requests.Session | None = None
    ) -> None:
        """Create a client, optionally reusing an existing HTTP session."""
        self.base_url = base_url.rstrip("/")
        self.session = session or _new_session()

    def _get(self, path: str, **params: str) -> list | dict:
        response = self.session.get(
            f"{self.base_url}/{path}", params=params, timeout=config.HTTP_TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def markets(self) -> list[Market]:
        """Return all Kamino lending markets."""
        return [Market.from_api(m) for m in self._get("v2/kamino-market")]

    def obligations(self, market: str, wallet: str) -> list[dict]:
        """Return the raw obligation records for ``wallet`` in ``market``."""
        return self._get(f"kamino-market/{market}/users/{wallet}/obligations")

    def reserves(self, market: str) -> dict[str, Reserve]:
        """reserve address -> Reserve (without on-chain fields, see chain.py)."""
        return {
            m["reserve"]: Reserve(
                address=m["reserve"],
                symbol=m["liquidityToken"],
                mint=m["liquidityTokenMint"],
                max_ltv=float(m["maxLtv"]),
            )
            for m in self._get(f"kamino-market/{market}/reserves/metrics")
        }

    def prices(self) -> dict[str, float]:
        """token mint -> USD price (Kamino's Scope oracle)."""
        data = self._get("prices", env=config.PRICE_ENV, source=config.PRICE_SOURCE)
        return {p["mint"]: float(p["usdPrice"]) for p in data}


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    return session
