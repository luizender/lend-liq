---
name: project-conventions
description: Architecture, layering, and quality bar for the kamino-liq codebase. Load before adding or modifying code in this repository.
user-invocable: false
---

# kamino-liq conventions

A small, **read-only** CLI that reads a wallet's Kamino Lend position and computes
its liquidation prices. It never needs or touches a private key and never sends a
transaction — preserve that invariant in every change.

## Layering (do not cross)

`api.py` (Kamino REST) and `chain.py` (Solana RPC + on-chain decoding) do the I/O →
`service.py` orchestrates a wallet into `Position` objects → `liquidation.py` is
**pure math over the models: no I/O, no rendering** → `render.py` (Rich) → `cli.py`
(Typer). Keeping `liquidation.py` free of I/O is what makes the math trivially
unit-testable; don't import network/render code into it.

## Models

`models.py` holds frozen dataclasses; health metrics are **derived properties**, not
stored fields. A `Position` is fully described by its collateral, borrows, and
Kamino's borrow-factor-**adjusted** `debt_value` — which is *not* `Σ borrow value`
(see `service.py::_build_position`). Anything that reprices debt must respect that
factor (`liquidation.py::apply_price_overrides`).

## Quality bar (enforced — keep it green)

- `ruff format` and `ruff check` clean (config in `ruff.toml`, line length 100).
- `pytest` passes at **100% coverage** (`fail_under = 100`).
- `pylint kamino_liq` stays **10.00/10**.

Run all three:
`.venv/bin/ruff check kamino_liq tests && .venv/bin/ruff format --check kamino_liq tests && .venv/bin/pytest -q --cov --cov-report=term-missing && .venv/bin/pylint kamino_liq`

A `Stop` hook runs this gate automatically; a `PostToolUse` hook applies `ruff` on
each edit. Every new function needs a test in the matching `tests/test_*.py`.

## Style

- Match surrounding code. Reuse the `render.py` helpers (`_table`, `_usd`,
  `_health_color`) instead of building ad-hoc Rich tables.
- New CLI commands follow the existing pattern: `_validate_wallet` → `_select_markets`
  → `service.load_positions` → a `render.py` function.
- On-chain byte offsets live in `config.py` and are cross-checked at runtime; see the
  `verify-onchain-layout` skill before touching them.
