"""Read-only client for the public Kamino REST API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from .. import config


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

    def market(self, pubkey: str) -> dict:
        """Return one market's metadata (its human-readable ``name``, etc.)."""
        return self._get(f"v2/kamino-market/{pubkey}")

    def portfolio(self, wallet: str) -> list[dict]:
        """Return ``wallet``'s lending loans across every market (one row each).

        Each row carries the loan's ``address`` and ``marketAddress``; per-asset
        figures come from :meth:`loan`.
        """
        return self._get(f"portfolio/{wallet}").get("lending") or []

    def loan(self, obligation: str) -> dict:
        """Return one loan's fully-priced detail (underlying amounts, live prices,
        per-asset liquidation thresholds, and borrow factors)."""
        return self._get(f"klend/loans/{obligation}")

    def reserves(self, market: str) -> list[dict]:
        """Return the list of reserves in the market."""
        return self._get(f"kamino-market/{market}/reserves/metrics")

    def reserve_config(self, market: str, reserve: str) -> dict:
        """Return metrics history for a specific reserve to extract configuration."""
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        return self._get(
            f"kamino-market/{market}/reserves/{reserve}/metrics/history",
            env="mainnet-beta",
            start=start,
            end=end,
            frequency="day",
        )


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    return session
