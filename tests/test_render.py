"""Tests for the Rich rendering layer (output captured to a wide buffer)."""

import io

import pytest
from rich.console import Console

from lend_liq import render
from lend_liq.liquidation import AmountChange, apply_overrides
from lend_liq.models import Borrow, Collateral, Position


@pytest.fixture
def out(monkeypatch):
    buffer = io.StringIO()
    monkeypatch.setattr(render, "console", Console(file=buffer, width=200))
    return buffer


def position(collateral, debt_value, borrows=()):
    return Position("Main Market", "OBLIGATION", tuple(collateral), tuple(borrows), debt_value)


def test_render_position_multi_collateral(out) -> None:
    # A is over-covered by B (safe at $0); B has a real liquidation price.
    a = Collateral("A", 1, 100, 0.8)  # weighted 80
    b = Collateral("B", 100, 100, 0.8)  # weighted 8000
    render.render_position(position([a, b], 1000, [Borrow("USDC", 1000, 1.0)]))
    text = out.getvalue()
    assert "Health factor" in text
    assert "Liquidation price" in text
    assert "safe at $0" in text  # asset A
    assert "Global crash" in text  # two collaterals -> crash table


def test_render_position_no_debt(out) -> None:
    render.render_position(position([Collateral("SOL", 1, 100, 0.8)], 0))
    assert "cannot be liquidated" in out.getvalue()


def test_render_position_single_collateral_skips_crash(out) -> None:
    pos = position([Collateral("SOL", 100, 100, 0.8)], 4000, [Borrow("U", 4000, 1.0)])
    render.render_position(pos)
    assert "Global crash" not in out.getvalue()


def test_health_color_thresholds() -> None:
    assert render._health_color(2.0) == "green"
    assert render._health_color(1.2) == "yellow"
    assert render._health_color(1.0) == "red"


def test_render_crash_stable_and_volatile_rows(out) -> None:
    usdc = Collateral("USDC", 100, 1.0, 0.9)  # stable, cap 90
    sol = Collateral("SOL", 10, 100, 0.8)  # volatile, cap 800
    render._render_crash(position([usdc, sol], 200))
    text = out.getvalue()
    assert "Global crash" in text
    assert "(held)" in text  # stable row
    assert "volatile" in text  # volatile row
    assert "Drop" in text  # per-asset drop column
    assert "0.0%" in text  # held stable row drops nothing


def test_render_crash_safe(out) -> None:
    usdc = Collateral("USDC", 1000, 1.0, 0.9)  # cap 900 > debt
    sol = Collateral("SOL", 10, 100, 0.8)
    render._render_crash(position([usdc, sol], 800))
    assert "$0" in out.getvalue()


def test_render_crash_exceeded(out) -> None:
    render._render_crash(position([Collateral("USDC", 100, 1.0, 0.9)], 200))
    assert "absorb" in out.getvalue()


def test_render_crash_at_risk(out) -> None:
    render._render_crash(position([Collateral("SOL", 100, 100, 0.8)], 9000))
    assert "past" in out.getvalue()


def test_render_crash_volatile_debt(out) -> None:
    pos = position([Collateral("SOL", 10, 100, 0.8)], 500, [Borrow("BTC", 0.1, 40000)])
    render._render_crash(pos)
    assert "volatile" in out.getvalue()
    assert "simulate" in out.getvalue()


def test_render_simulation_shows_changes_and_verdict(out) -> None:
    sol = Collateral("SOL", 100, 100, 0.8)
    original = position([sol], 4000, [Borrow("USDC", 4000, 1.0)])
    simulated = apply_overrides(original, {"SOL": 40.0})
    render.render_simulation(original, simulated)
    text = out.getvalue()
    assert "Simulation" in text
    assert "Simulated price changes" in text
    assert "2.00 →" in text  # original HF 8000/4000; simulated 3200/4000 = 0.80
    assert "would be liquidated" in text


def test_render_simulation_shows_amount_changes(out) -> None:
    sol = Collateral("SOL", 100, 100, 0.8)
    original = position([sol], 4000, [Borrow("USDC", 4000, 1.0)])
    simulated = apply_overrides(original, {}, {"SOL": AmountChange(50.0, is_delta=True)})
    render.render_simulation(original, simulated)
    text = out.getvalue()
    assert "Simulated amount changes" in text
    assert "150.0000" in text  # 100 + 50 SOL deposited
    assert "+50.0%" in text  # amount grew by half


def test_render_simulation_no_matching_changes(out) -> None:
    sol = Collateral("SOL", 100, 100, 0.8)
    original = position([sol], 4000, [Borrow("USDC", 4000, 1.0)])
    render.render_simulation(original, original)
    assert "No simulated changes" in out.getvalue()


def test_render_simulation_no_debt_skips_health_line(out) -> None:
    sol = Collateral("SOL", 100, 100, 0.8)
    original = position([sol], 0)  # no debt -> no health-factor line
    simulated = apply_overrides(original, {"SOL": 50.0})
    render.render_simulation(original, simulated)
    text = out.getvalue()
    assert "Simulated price changes" in text
    assert "Health factor:" not in text
    assert "cannot be liquidated" in text
