"""Rich rendering of markets, reserves, RPC nodes, and positions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rich import box
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .liquidation import CrashStatus, crash_scenario, single_asset_levels
from .models import Market, Position, Reserve, RpcNode

console = Console()


@contextmanager
def scan_progress(total: int) -> Iterator[Callable[[], None]]:
    """Transient progress bar over `total` markets; yields a per-market tick.

    The yielded callback is thread-safe, so the parallel market scan can advance
    it from worker threads. On a non-terminal (piped) console it renders nothing.
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[dim]Scanning markets…[/dim]"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("scan", total=total)
        yield lambda: progress.advance(task)


_HEALTHY = 1.5
_CAUTION = 1.15


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _health_color(health_factor: float) -> str:
    if health_factor >= _HEALTHY:
        return "green"
    if health_factor >= _CAUTION:
        return "yellow"
    return "red"


def _table(title: str = "") -> Table:
    return Table(title=title or None, box=box.SIMPLE_HEAD, title_justify="left")


def render_markets(markets: list[Market]) -> None:
    """Print a table of Kamino markets."""
    table = _table("Kamino markets")
    table.add_column("Name")
    table.add_column("Primary", justify="center")
    table.add_column("Market pubkey")
    table.add_column("Description")
    for market in markets:
        table.add_row(
            market.name,
            "✓" if market.is_primary else "",
            market.address,
            market.description,
        )
    console.print(table)


def render_reserves(market_name: str, reserves: list[Reserve]) -> None:
    """Print a market's reserves with LTV, liquidation threshold, and decimals."""
    table = _table(f"{market_name} — reserves")
    table.add_column("Asset")
    table.add_column("Max LTV", justify="right")
    table.add_column("Liq. threshold", justify="right")
    table.add_column("Decimals", justify="right")
    table.add_column("Mint")
    for reserve in sorted(reserves, key=lambda r: r.symbol.lower()):
        table.add_row(
            reserve.symbol,
            f"{reserve.max_ltv:.0%}",
            f"{reserve.liquidation_threshold:.0%}",
            str(reserve.decimals),
            reserve.mint,
        )
    console.print(table)


def render_rpcs(nodes: list[RpcNode], source: str, limit: int) -> None:
    """Print discovered cluster RPC endpoints (up to ``limit``)."""
    table = _table(f"Cluster RPC endpoints (via {source})")
    table.add_column("RPC endpoint")
    table.add_column("Version")
    table.add_column("Validator")
    for node in nodes[:limit]:
        table.add_row(f"http://{node.rpc}", node.version, node.pubkey)
    console.print(table)
    console.print(
        f"[dim]Showing {min(limit, len(nodes))} of {len(nodes)} nodes advertising RPC. "
        "These are gossip-discovered and may be rate-limited or reject public traffic; "
        "prefer a dedicated provider for --rpc.[/dim]"
    )


def render_position(position: Position, show_crash: bool = True) -> None:
    """Print a position's holdings, health, and liquidation scenarios."""
    console.rule(f"[bold]{position.market_name}[/bold]  ·  obligation {position.address[:8]}…")
    _render_body(position, show_crash)


def render_simulation(original: Position, simulated: Position, show_crash: bool = True) -> None:
    """Print a what-if: the price overrides applied, the resulting health, and the
    full liquidation breakdown recomputed at the simulated prices."""
    console.rule(
        f"[bold]Simulation[/bold]  ·  {simulated.market_name}"
        f"  ·  obligation {simulated.address[:8]}…"
    )
    _render_overrides(original, simulated)
    _render_body(simulated, show_crash)


def _render_body(position: Position, show_crash: bool) -> None:
    _render_holdings(position)
    if not position.has_debt:
        console.print("[green]No debt — this position cannot be liquidated.[/green]\n")
        return
    _render_health(position)
    console.print()
    _render_single_asset(position)
    if show_crash and len(position.collateral) > 1:
        console.print()
        _render_crash(position)
    console.print()


def _render_overrides(original: Position, simulated: Position) -> None:
    assets = list(zip(original.collateral, simulated.collateral, strict=True)) + list(
        zip(original.borrows, simulated.borrows, strict=True)
    )
    rows = [(before, after) for before, after in assets if before.price != after.price]
    if not rows:
        console.print("[dim]No simulated price changes apply to this position.[/dim]\n")
        return
    table = _table("Simulated price changes")
    table.add_column("Asset")
    for name in ("Original", "Simulated", "Change"):
        table.add_column(name, justify="right")
    for before, after in rows:
        change = (after.price - before.price) / before.price if before.price else 0.0
        table.add_row(after.symbol, _usd(before.price), _usd(after.price), f"{change:+.1%}")
    console.print(table)
    if simulated.has_debt:
        color = _health_color(simulated.health_factor)
        verdict = "  [red]would be liquidated[/red]" if simulated.health_factor < 1.0 else ""
        console.print(
            f"Health factor: {original.health_factor:.2f} → "
            f"[{color}]{simulated.health_factor:.2f}[/{color}]{verdict}\n"
        )


def _render_holdings(position: Position) -> None:
    table = _table("Position")
    table.add_column("Asset")
    for name in ("Amount", "Price", "Value", "Liq. LTV"):
        table.add_column(name, justify="right")
    for c in position.collateral:
        table.add_row(
            c.symbol,
            f"{c.amount:,.4f}",
            _usd(c.price),
            _usd(c.value),
            f"{c.liquidation_threshold:.0%}",
        )
    table.add_section()
    for b in position.borrows:
        table.add_row(
            f"[red]{b.symbol} (debt)[/red]",
            f"{b.amount:,.4f}",
            _usd(b.price),
            f"[red]-{_usd(b.value)}[/red]",
            "",
        )
    console.print(table)


def _render_health(position: Position) -> None:
    color = _health_color(position.health_factor)
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column(style="bold")
    table.add_column(justify="right")
    table.add_row("Net account value", _usd(position.net_value))
    table.add_row("Total deposited", _usd(position.deposit_value))
    table.add_row("Total borrowed", _usd(position.debt_value))
    table.add_row("Current LTV", f"{position.current_ltv:.2%}")
    table.add_row("Liquidation LTV", f"{position.liquidation_ltv:.2%}")
    table.add_row(
        "Health factor", f"[{color}]{position.health_factor:.2f}[/{color}]  (liquidated below 1.00)"
    )
    drop = f"[{color}]{position.drop_to_liquidation:.2%}[/{color}]"
    table.add_row("Collateral drop to liquidation", f"{drop}  (if all collateral falls together)")
    console.print(table)


def _render_single_asset(position: Position) -> None:
    table = _table("Liquidation price — single asset drops (others held constant)")
    table.add_column("Asset")
    for name in ("Current", "Liq. price", "Buffer"):
        table.add_column(name, justify="right")
    for level in single_asset_levels(position):
        if level.is_safe:
            table.add_row(
                level.collateral.symbol,
                _usd(level.collateral.price),
                "[green]safe at $0[/green]",
                "—",
            )
        else:
            table.add_row(
                level.collateral.symbol,
                _usd(level.collateral.price),
                _usd(level.price),
                f"{level.buffer:.1%} drop",
            )
    console.print(table)


def _render_crash(position: Position) -> None:
    scenario = crash_scenario(position)
    messages = {
        CrashStatus.SAFE: "[green]Global crash: stable collateral alone covers the debt — "
        "volatile assets can fall to $0.[/green]",
        CrashStatus.EXCEEDED: "[red]Global crash: debt exceeds stable collateral and there are "
        "no volatile assets to absorb it.[/red]",
        CrashStatus.AT_RISK: "[red]Global crash: already at or past the liquidation "
        "threshold.[/red]",
        CrashStatus.VOLATILE_DEBT: "[yellow]Global crash: debt includes volatile assets that "
        "would also move in a crash, so a uniform collateral crash is not a meaningful single "
        "scenario. Use `simulate` to model specific prices.[/yellow]",
    }
    if scenario.status is not CrashStatus.TRIGGERABLE:
        console.print(messages[scenario.status])
        return

    table = _table(f"Global crash — liquidated if volatile collateral drops {scenario.drop:.1%}")
    table.add_column("Asset")
    table.add_column("Type")
    for name in ("Current", "Liq. price"):
        table.add_column(name, justify="right")
    for collateral, price in scenario.prices:
        kind, suffix = ("stable", " (held)") if collateral.is_stable else ("volatile", "")
        table.add_row(collateral.symbol, kind, _usd(collateral.price), f"{_usd(price)}{suffix}")
    console.print(table)
