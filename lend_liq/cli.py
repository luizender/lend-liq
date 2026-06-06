"""Typer command-line interface."""

from __future__ import annotations

import enum
import time
from collections.abc import Callable
from datetime import datetime

import typer

from . import __version__, config, sources
from .liquidation import AmountChange, Changes, apply_overrides
from .models import Borrow, Collateral, ReserveInfo
from .render import console, render_position, render_simulation


class Protocol(str, enum.Enum):
    """Lending protocol selector for ``--protocol``."""

    AUTO = "auto"
    KAMINO = "kamino"
    AAVE = "aave"


# --chain choices: "all" (sweep every deployment) plus each supported Aave chain,
# whose names stay defined in one place (config.AAVE_CHAINS).
Chain = enum.Enum("Chain", {"all": "all", **{name: name for name in config.AAVE_CHAINS}}, type=str)


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Inspect Kamino Lend and Aave positions and their liquidation prices (read-only).",
)

_PROTOCOL_OPTION = typer.Option(
    Protocol.AUTO,
    "--protocol",
    "-P",
    help="Protocol: kamino, aave, or auto (detect from the address).",
)
_CHAIN_OPTION = typer.Option(
    Chain["all"],
    "--chain",
    "-c",
    help="Aave chain (e.g. ethereum, arbitrum); 'all' (the default) scans every chain.",
)


def _version_callback(show: bool) -> None:
    if show:
        console.print(f"lend-liq {__version__}")
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
    """Kamino and Aave liquidation-price toolkit."""


@app.command()
def report(
    wallet: str = typer.Argument(
        ..., help="Wallet address: a Solana key (Kamino) or EVM 0x address (Aave). Read-only."
    ),
    protocol: Protocol = _PROTOCOL_OPTION,
    chain: Chain = _CHAIN_OPTION,
    crash: bool = typer.Option(
        True, "--crash/--no-crash", help="Include the global market-crash scenario."
    ),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh continuously until stopped."),
    interval: int = typer.Option(
        30, "--interval", min=1, help="Seconds between refreshes in watch mode."
    ),
) -> None:
    """Show the liquidation prices of WALLET's lending positions."""
    label, loader, _ = _resolve(wallet, protocol, chain)
    if watch:
        _watch(wallet, label, loader, crash, interval)
    else:
        _report_once(wallet, label, loader, crash)


@app.command("simulate")
def simulate_command(  # pylint: disable=too-many-locals
    wallet: str = typer.Argument(
        ..., help="Wallet address: a Solana key (Kamino) or EVM 0x address (Aave). Read-only."
    ),
    protocol: Protocol = _PROTOCOL_OPTION,
    chain: Chain = _CHAIN_OPTION,
    price: list[str] = typer.Option(
        None, "--price", "-p", help="Override an asset price, e.g. -p SOL=120 (repeatable)."
    ),
    amount: list[str] = typer.Option(
        None,
        "--amount",
        "-a",
        help=(
            "Change a collateral asset amount: -a SOL=+10 (add), "
            "-a SOL=-5 (remove), -a SOL=200 (set). Repeatable."
        ),
    ),
    borrow: list[str] = typer.Option(
        None,
        "--borrow",
        "-b",
        help=(
            "Change a borrow asset amount: -b SOL=+10 (add), -b SOL=-5 (remove), -b SOL=200 (set). "
            "Repeatable."
        ),
    ),
    crash: bool = typer.Option(
        True, "--crash/--no-crash", help="Include the global market-crash scenario."
    ),
) -> None:
    """Recompute WALLET's liquidation health under hypothetical prices and amounts."""
    prices = _parse_prices(price or [])
    amounts = _parse_amounts(amount or [], "--amount")
    borrows = _parse_amounts(borrow or [], "--borrow")
    if not prices and not amounts and not borrows:
        raise typer.BadParameter(
            "provide at least one --price, --amount, or --borrow change",
            param_hint="--price/--amount/--borrow",
        )
    label, loader, reserves = _resolve(wallet, protocol, chain)

    requested = set(prices) | set(amounts) | set(borrows)
    resolved_globally: set[str] = set()
    processed_any = False

    for position in loader():
        processed_any = True
        held_collateral = {c.symbol.upper() for c in position.collateral}
        held_borrows = {b.symbol.upper() for b in position.borrows}

        collateral_amounts = {
            sym: change for sym, change in amounts.items() if sym in held_collateral
        }
        borrow_amounts = {sym: change for sym, change in borrows.items() if sym in held_borrows}

        add_collateral = []
        added_collateral_symbols = set()
        for sym, change in amounts.items():
            if sym not in held_collateral:
                res_info = reserves(position.market_id, sym)
                if res_info:
                    add_collateral.append(
                        Collateral(
                            symbol=res_info.symbol,
                            amount=change.applied_to(0.0),
                            price=res_info.price,
                            liquidation_threshold=res_info.liquidation_threshold,
                        )
                    )
                    added_collateral_symbols.add(sym)

        add_borrows = []
        added_borrow_symbols = set()
        for sym, change in borrows.items():
            if sym not in held_borrows:
                res_info = reserves(position.market_id, sym)
                if res_info:
                    add_borrows.append(
                        Borrow(
                            symbol=res_info.symbol,
                            amount=change.applied_to(0.0),
                            price=res_info.price,
                            borrow_factor=res_info.borrow_factor,
                        )
                    )
                    added_borrow_symbols.add(sym)

        changes = Changes(
            prices=prices,
            collateral_amounts=collateral_amounts,
            borrow_amounts=borrow_amounts,
            add_collateral=tuple(add_collateral),
            add_borrows=tuple(add_borrows),
        )

        simulated = apply_overrides(position, changes)
        render_simulation(position, simulated, show_crash=crash)

        resolved_this_position = (
            held_collateral | held_borrows | added_collateral_symbols | added_borrow_symbols
        )
        resolved_globally.update(resolved_this_position)

    if not processed_any:
        console.print(f"[yellow]No {label} positions found for {wallet}.[/yellow]")
        return

    unresolved = requested - resolved_globally
    if unresolved:
        console.print(f"[yellow]No position holds: {', '.join(sorted(unresolved))}.[/yellow]")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _resolve(
    wallet: str, protocol: Protocol, chain: Chain
) -> tuple[str, sources.Loader, Callable[[str, str], ReserveInfo | None]]:
    # "all" carries no specific chain; sources reads a missing chain as scan-every-chain.
    chain_arg = None if chain.value == "all" else chain.value
    try:
        name, loader, reserves = sources.resolve(wallet, protocol.value, chain_arg)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return sources.LABELS[name], loader, reserves


def _parse_prices(items: list[str]) -> dict[str, float]:
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


def _parse_amounts(items: list[str], param: str = "--amount") -> dict[str, AmountChange]:
    # A leading +/- means adjust by that much; a bare number sets the amount outright.
    amounts: dict[str, AmountChange] = {}
    for item in items:
        symbol, sep, value = item.partition("=")
        if not sep or not symbol.strip():
            raise typer.BadParameter(f"expected SYMBOL=AMOUNT, got {item!r}", param_hint=param)
        is_delta = value.strip().startswith(("+", "-"))
        try:
            amounts[symbol.strip().upper()] = AmountChange(float(value), is_delta)
        except ValueError as exc:
            raise typer.BadParameter(f"{value!r} is not a number", param_hint=param) from exc
    return amounts


def _report_once(wallet: str, label: str, loader: sources.Loader, crash: bool) -> None:
    """Render every position, or a note if the wallet has none."""
    found = list(loader())
    for position in found:
        render_position(position, show_crash=crash)
    if not found:
        console.print(f"[yellow]No {label} positions found for {wallet}.[/yellow]")


def _watch(
    wallet: str,
    label: str,
    loader: sources.Loader,
    crash: bool,
    interval: int,
) -> None:
    try:
        while True:
            console.clear()
            console.print(
                f"[dim]{label} liquidation watch · {wallet} · {datetime.now():%Y-%m-%d %H:%M:%S}"
                f" · every {interval}s · Ctrl+C to stop[/dim]\n"
            )
            try:
                _report_once(wallet, label, loader, crash)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # keep watching through transient API errors
                console.print(f"[red]Refresh failed: {exc}[/red]")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped.[/dim]")
