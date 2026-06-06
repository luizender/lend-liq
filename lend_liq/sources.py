"""Resolve an address to a protocol-specific position loader, so the CLI stays
free of per-protocol I/O wiring. Kamino positions come from a Solana wallet; Aave
positions from an EVM address on a chosen chain."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from solders.pubkey import Pubkey

from . import config
from .aave import service as aave_service
from .aave.api import AaveClient
from .kamino import service
from .kamino.api import KaminoClient
from .models import Position, ReserveInfo

Loader = Callable[[], Iterator[Position]]
LABELS = {"kamino": "Kamino Lend", "aave": "Aave"}
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def detect_protocol(address: str) -> str:
    """Guess the protocol from the address shape: EVM (0x…) is Aave, else Kamino."""
    return "aave" if _EVM_ADDRESS.match(address) else "kamino"


def resolve(
    address: str, protocol: str, chain: str | None
) -> tuple[str, Loader, Callable[[str, str], ReserveInfo | None]]:
    """Return ``(protocol, loader, reserves)`` for ``address``. ``protocol`` may be ``auto``.

    Raises ``ValueError`` on a bad address, an unknown chain, or a chain passed to
    Kamino — the CLI turns these into usage errors. A missing Aave chain is not an
    error: it defaults to scanning every supported chain."""
    if protocol == "auto":
        protocol = detect_protocol(address)
    if protocol == "kamino":
        loader, reserves = _kamino_loader(address, chain)
        return protocol, loader, reserves
    if protocol == "aave":
        loader, reserves = _aave_loader(address, chain)
        return protocol, loader, reserves
    raise ValueError(f"unknown protocol {protocol!r}; choose kamino, aave, or auto")


def _kamino_loader(
    address: str, chain: str | None
) -> tuple[Loader, Callable[[str, str], ReserveInfo | None]]:
    if chain:
        raise ValueError("--chain only applies to aave")
    _validate_solana(address)
    client = KaminoClient()

    def loader() -> Iterator[Position]:
        return service.load_positions(client, address)

    cache: dict[tuple[str, str], ReserveInfo | None] = {}

    def reserves(market_id: str, symbol: str) -> ReserveInfo | None:
        key = (market_id, symbol.upper())
        if key not in cache:
            cache[key] = service.resolve_reserve(client, market_id, symbol)
        return cache[key]

    return loader, reserves


def _aave_loader(
    address: str, chain: str | None
) -> tuple[Loader, Callable[[str, str], ReserveInfo | None]]:
    _validate_evm(address)
    chain_ids = _chain_ids(chain)
    client = AaveClient()

    def loader() -> Iterator[Position]:
        return aave_service.load_positions(client, address, chain_ids)

    cache: dict[tuple[str, str], ReserveInfo | None] = {}

    def reserves(market_id: str, symbol: str) -> ReserveInfo | None:
        key = (market_id, symbol.upper())
        if key not in cache:
            cache[key] = aave_service.resolve_reserve(client, address, market_id, symbol)
        return cache[key]

    return loader, reserves


def _validate_solana(address: str) -> None:
    try:
        Pubkey.from_string(address)
    except Exception as exc:  # solders raises a bare ValueError-like error
        raise ValueError("not a valid Solana public key") from exc


def _validate_evm(address: str) -> None:
    if not _EVM_ADDRESS.match(address):
        raise ValueError("not a valid EVM address (expected 0x + 40 hex chars)")


def _chain_ids(chain: str | None) -> list[int]:
    """The chain ids to scan: just the named one, or — by default — every supported
    chain, mirroring Kamino's all-markets sweep."""
    if not chain:
        return list(config.AAVE_CHAINS.values())
    try:
        return [config.AAVE_CHAINS[chain.lower()]]
    except KeyError as exc:
        supported = ", ".join(sorted(config.AAVE_CHAINS))
        raise ValueError(f"unknown chain {chain!r}; supported: {supported}") from exc
