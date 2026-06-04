"""Typer command-line interface."""

from __future__ import annotations

import time
from datetime import datetime

import typer
from solders.pubkey import Pubkey

from . import __version__, config
from .api import KaminoClient
from .chain import SolanaRPC, enrich_reserves
from .liquidation import apply_price_overrides
from .models import Market
from .render import (
    console,
    render_markets,
    render_position,
    render_reserves,
    render_rpcs,
    render_simulation,
    scan_progress,
)
from .service import load_positions

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Inspect Kamino Lend positions and their liquidation prices (read-only).",
)


def _version_callback(show: bool) -> None:
    if show:
        console.print(f"kamino-liq {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Kamino liquidation-price toolkit."""


@app.command()
def report(
    wallet: str = typer.Argument(
        ..., help="Solana wallet public key (read-only — never a private key)."
    ),
    market: str | None = typer.Option(
        None, "--market", "-m", help="Limit to one market pubkey (default: scan all)."
    ),
    rpc: str = typer.Option(
        config.DEFAULT_RPC, "--rpc", help="Solana RPC URL (reads reserve config + decimals)."
    ),
    crash: bool = typer.Option(
        True, "--crash/--no-crash", help="Include the global market-crash scenario."
    ),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh continuously until stopped."),
    interval: int = typer.Option(
        30, "--interval", min=1, help="Seconds between refreshes in watch mode."
    ),
) -> None:
    """Show the liquidation prices of WALLET's Kamino Lend positions."""
    _validate_wallet(wallet)
    client = KaminoClient()
    solana = SolanaRPC(rpc)
    markets = _select_markets(client, market)

    if watch:
        _watch(wallet, client, solana, markets, crash, interval)
    else:
        _report_once(wallet, client, solana, markets, crash)


@app.command("simulate")
def simulate_command(
    wallet: str = typer.Argument(
        ..., help="Solana wallet public key (read-only — never a private key)."
    ),
    price: list[str] = typer.Option(
        None, "--price", "-p", help="Override an asset price, e.g. -p SOL=120 (repeatable)."
    ),
    market: str | None = typer.Option(
        None, "--market", "-m", help="Limit to one market pubkey (default: scan all)."
    ),
    rpc: str = typer.Option(
        config.DEFAULT_RPC, "--rpc", help="Solana RPC URL (reads reserve config + decimals)."
    ),
    crash: bool = typer.Option(
        True, "--crash/--no-crash", help="Include the global market-crash scenario."
    ),
) -> None:
    """Recompute WALLET's liquidation health under hypothetical prices."""
    _validate_wallet(wallet)
    overrides = _parse_overrides(price or [])
    client = KaminoClient()
    solana = SolanaRPC(rpc)
    markets = _select_markets(client, market)

    with scan_progress(len(markets)) as tick:
        found = list(load_positions(client, solana, wallet, markets, on_scan=tick))
    held: set[str] = set()
    for _market, position in found:
        render_simulation(position, apply_price_overrides(position, overrides), show_crash=crash)
        held.update(c.symbol.upper() for c in position.collateral)
        held.update(b.symbol.upper() for b in position.borrows)

    if not held:
        console.print(f"[yellow]No Kamino Lend positions found for {wallet}.[/yellow]")
        return
    unknown = sorted(set(overrides) - held)
    if unknown:
        console.print(f"[yellow]No position holds: {', '.join(unknown)}.[/yellow]")


@app.command("markets")
def markets_command() -> None:
    """List all Kamino lending markets and their pubkeys."""
    render_markets(KaminoClient().markets())


@app.command("reserves")
def reserves_command(
    market: str | None = typer.Option(
        None, "--market", "-m", help="Market pubkey (default: the primary market)."
    ),
    rpc: str = typer.Option(config.DEFAULT_RPC, "--rpc", help="Solana RPC URL."),
) -> None:
    """List a market's reserves with their LTV and liquidation thresholds."""
    client = KaminoClient()
    selected = _select_markets(client, market)[0] if market else _primary_market(client)
    reserves = list(client.reserves(selected.address).values())
    enriched = enrich_reserves(SolanaRPC(rpc), reserves)
    render_reserves(selected.name, list(enriched.values()))


@app.command("rpcs")
def rpcs_command(
    rpc: str = typer.Option(config.DEFAULT_RPC, "--rpc", help="RPC node to query for the list."),
    limit: int = typer.Option(25, "--limit", "-n", min=1, help="Max endpoints to show."),
) -> None:
    """List public Solana RPC endpoints advertised on the cluster."""
    render_rpcs(SolanaRPC(rpc).cluster_nodes(), source=rpc, limit=limit)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _validate_wallet(wallet: str) -> None:
    try:
        Pubkey.from_string(wallet)
    except Exception as exc:  # solders raises a bare ValueError-like error
        raise typer.BadParameter("not a valid Solana public key", param_hint="WALLET") from exc


def _parse_overrides(items: list[str]) -> dict[str, float]:
    if not items:
        raise typer.BadParameter("provide at least one SYMBOL=PRICE", param_hint="--price")
    overrides: dict[str, float] = {}
    for item in items:
        symbol, sep, value = item.partition("=")
        if not sep or not symbol.strip():
            raise typer.BadParameter(f"expected SYMBOL=PRICE, got {item!r}", param_hint="--price")
        try:
            overrides[symbol.strip().upper()] = float(value)
        except ValueError as exc:
            raise typer.BadParameter(f"{value!r} is not a number", param_hint="--price") from exc
    return overrides


def _primary_market(client: KaminoClient) -> Market:
    markets = client.markets()
    return next((m for m in markets if m.is_primary), markets[0])


def _select_markets(client: KaminoClient, market: str | None) -> list[Market]:
    markets = client.markets()
    if market is None:
        return markets
    selected = [m for m in markets if m.address == market]
    if not selected:
        raise typer.BadParameter(f"unknown market {market}", param_hint="--market")
    return selected


def _report_once(
    wallet: str, client: KaminoClient, solana: SolanaRPC, markets: list[Market], crash: bool
) -> list[Market]:
    """Render every position; return the markets that actually held one."""
    with scan_progress(len(markets)) as tick:
        found = list(load_positions(client, solana, wallet, markets, on_scan=tick))
    active: list[Market] = []
    for market, position in found:
        if market not in active:
            active.append(market)
        render_position(position, show_crash=crash)
    if not active:
        console.print(f"[yellow]No Kamino Lend positions found for {wallet}.[/yellow]")
    return active


def _watch(
    wallet: str,
    client: KaminoClient,
    solana: SolanaRPC,
    markets: list[Market],
    crash: bool,
    interval: int,
) -> None:
    try:
        while True:
            console.clear()
            console.print(
                f"[dim]Kamino liquidation watch · {wallet} · {datetime.now():%Y-%m-%d %H:%M:%S}"
                f" · every {interval}s · Ctrl+C to stop[/dim]\n"
            )
            try:
                active = _report_once(wallet, client, solana, markets, crash)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # keep watching through transient API/RPC errors
                console.print(f"[red]Refresh failed: {exc}[/red]")
            else:
                # After the first scan, poll only the markets that hold positions.
                if active:
                    markets = active
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped.[/dim]")
