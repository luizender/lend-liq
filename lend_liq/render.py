"""Rich rendering of a wallet's positions and liquidation scenarios."""

from __future__ import annotations

from collections.abc import Callable

from rich import box
from rich.console import Console
from rich.table import Table

from .liquidation import CrashStatus, crash_scenario, single_asset_levels
from .models import Borrow, Collateral, Position

console = Console()


_HEALTHY = 1.5
_CAUTION = 1.15


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _amount_str(value: float) -> str:
    return f"{value:,.4f}"


def _health_color(health_factor: float) -> str:
    if health_factor >= _HEALTHY:
        return "green"
    if health_factor >= _CAUTION:
        return "yellow"
    return "red"


def _table(title: str = "") -> Table:
    return Table(title=title or None, box=box.SIMPLE_HEAD, title_justify="left")


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
    pairs = list(zip(original.collateral, simulated.collateral, strict=True)) + list(
        zip(original.borrows, simulated.borrows, strict=True)
    )
    price_rows = [(before, after) for before, after in pairs if before.price != after.price]
    amount_rows = [(before, after) for before, after in pairs if before.amount != after.amount]
    if not price_rows and not amount_rows:
        console.print("[dim]No simulated changes apply to this position.[/dim]\n")
        return
    if price_rows:
        _render_change_table("Simulated price changes", price_rows, lambda a: a.price, _usd)
    if amount_rows:
        _render_change_table(
            "Simulated amount changes", amount_rows, lambda a: a.amount, _amount_str
        )
    if simulated.has_debt:
        color = _health_color(simulated.health_factor)
        verdict = "  [red]would be liquidated[/red]" if simulated.health_factor < 1.0 else ""
        console.print(
            f"Health factor: {original.health_factor:.2f} → "
            f"[{color}]{simulated.health_factor:.2f}[/{color}]{verdict}\n"
        )


def _render_change_table(
    title: str,
    rows: list[tuple[Collateral | Borrow, Collateral | Borrow]],
    value: Callable[[Collateral | Borrow], float],
    fmt: Callable[[float], str],
) -> None:
    table = _table(title)
    table.add_column("Asset")
    for name in ("Original", "Simulated", "Change"):
        table.add_column(name, justify="right")
    for before, after in rows:
        before_v, after_v = value(before), value(after)
        change = (after_v - before_v) / before_v if before_v else 0.0
        table.add_row(after.symbol, fmt(before_v), fmt(after_v), f"{change:+.1%}")
    console.print(table)


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
    for name in ("Current", "Liq. price", "Drop"):
        table.add_column(name, justify="right")
    for collateral, price in scenario.prices:
        kind, suffix = ("stable", " (held)") if collateral.is_stable else ("volatile", "")
        change = (price - collateral.price) / collateral.price if collateral.price else 0.0
        table.add_row(
            collateral.symbol,
            kind,
            _usd(collateral.price),
            f"{_usd(price)}{suffix}",
            f"{change:.1%}",
        )
    console.print(table)
