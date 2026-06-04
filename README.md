# kamino-liq

[![CI](https://github.com/luizender/kamino-liq/actions/workflows/ci.yml/badge.svg)](https://github.com/luizender/kamino-liq/actions/workflows/ci.yml)

A small, **read-only** command-line tool that reads a Solana wallet's live
[Kamino Lend](https://app.kamino.finance) position and tells you **at what prices
it gets liquidated** — pulling the position, prices, and liquidation thresholds
straight from the Kamino API and the Solana chain.

> 🔒 It only ever needs a wallet **public key**. It never asks for, needs, or
> touches a private key or seed phrase, and it never sends a transaction.

```
$ kamino-liq report <YOUR_WALLET_PUBKEY>

───────────────── Main Market  ·  obligation 3ssjMRz3… ─────────────────
  Asset            Amount        Price            Value   Liq. LTV
  JupSOL      57,543.3696       $80.71    $4,644,272.32        60%
  PYUSD (debt) 2,042,156.91      $1.00   -$2,041,983.60

  Net account value                                    $2,571,246.73
  Current LTV                                                 44.58%
  Liquidation LTV                                             60.00%
  Health factor                       1.35  (liquidated below 1.00)
  Collateral drop to liquidation   25.80%  (if all collateral falls together)

  Liquidation price — single asset drops (others held constant)
  Asset     Current   Liq. price       Buffer
  JupSOL     $80.71       $59.92   25.8% drop
```

## Features

- **Live position** — fetches your actual deposits/borrows; no manual data entry.
- **Accurate liquidation math** — uses Kamino's own borrow-factor-adjusted debt
  and the on-chain liquidation thresholds, so the health figures match the
  Kamino UI.
- **Two liquidation views** — the price of each collateral if *only that asset
  drops*, plus a *global market-crash* scenario where volatile assets fall
  together while stablecoins hold.
- **What-if simulation** — override any asset's price (`simulate -p SOL=120`) and
  recompute the health, liquidation prices, and crash scenario at those prices —
  for the crashes that aren't uniform.
- **Multi-market** — automatically scans every Kamino market (Main, JLP, Jito, …).
- **Watch mode** — refresh continuously; after the first scan it polls only the
  markets that actually hold your positions.
- **No API key** — every data source is public.

## Install

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate

# Option A — install as a command (`kamino-liq`)
pip install -e .

# Option B — just the runtime deps, run via `python -m kamino_liq`
pip install -r requirements.txt
```

## Usage

After `pip install -e .` the entry point is `kamino-liq`; otherwise use
`python -m kamino_liq`. The two are interchangeable.

```bash
# Liquidation report for a wallet (scans all markets)
kamino-liq report <WALLET>

# Limit to one market, and skip the crash scenario
kamino-liq report <WALLET> --market 7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF --no-crash

# What-if: recompute health at hypothetical prices (-p is repeatable)
kamino-liq simulate <WALLET> -p SOL=120 -p JupSOL=110

# Watch mode: refresh every 15s until Ctrl+C
kamino-liq report <WALLET> --watch --interval 15

# Use your own (faster, non-rate-limited) RPC endpoint
kamino-liq report <WALLET> --rpc https://your-provider-url

# List all Kamino markets and their pubkeys
kamino-liq markets

# List a market's reserves with their LTV / liquidation thresholds
kamino-liq reserves                 # primary market
kamino-liq reserves -m <MARKET_PUBKEY>

# List public RPC endpoints advertised on the Solana cluster
kamino-liq rpcs --limit 30
```

Run `kamino-liq --help` or `kamino-liq <command> --help` for all options.

### A note on the public RPC

The default RPC (`api.mainnet-beta.solana.com`) is heavily rate-limited. It's
fine for one-off reports, but for `--watch` at short intervals you'll get much
better results passing your own endpoint via `--rpc` (e.g. Helius, QuickNode,
Triton). `kamino-liq rpcs` lists endpoints discovered on the cluster, though
most are not intended for public traffic.

## How it works

Everything needed is public and keyless:

| Data | Source |
|------|--------|
| Markets, your obligations, reserve symbols, fresh debt figure | Kamino REST API (`api.kamino.finance`) |
| Live prices | Kamino **Scope** oracle — the same prices the protocol liquidates on |
| Per-reserve **liquidation threshold** + token **decimals** | Solana RPC `getMultipleAccounts` |

The liquidation threshold and decimals are the only values the REST API doesn't
expose, so they're read directly from the on-chain KLend reserve and SPL mint
accounts at fixed byte offsets. The reserve offset is **cross-checked against the
API's `maxLtv`** on every read, so if Kamino ever changes the account layout the
tool fails loudly instead of silently returning a wrong number.

### The liquidation views

A position with several collateral assets has no single liquidation price — it has
a *surface* in price space, and any tool has to pick a path through it:

- **Single asset drops** — for each collateral, the price at which the position
  becomes liquidatable assuming that asset alone falls and the rest hold value.
- **Global crash** — every *volatile* collateral falls together while stablecoins
  keep their peg; reports the common drop % (and per-asset price) that triggers
  liquidation. This model holds the debt fixed, so it is suppressed when the debt
  itself is volatile (a real crash would move it too) — use `simulate` there.
- **Simulation** (`simulate`) — set explicit prices for any assets and recompute
  everything at once, for crashes that aren't uniform. Repricing a borrowed asset
  rescales Kamino's borrow-factor-adjusted debt by its current aggregate factor.

## Project structure

```
kamino_liq/
  config.py       endpoints, timeouts, on-chain layout constants
  models.py       typed dataclasses; health metrics are derived properties
  api.py          KaminoClient — the REST API
  chain.py        SolanaRPC + on-chain reserve/decimals decoding
  service.py      orchestration: wallet -> Position objects
  liquidation.py  pure liquidation-price math (no I/O)
  render.py       Rich rendering
  cli.py          Typer app: report / simulate / markets / reserves / rpcs
tests/            unit tests for the liquidation math
```

## Development

```bash
pip install -e ".[dev]"          # or: pip install -r requirements-dev.txt

ruff format kamino_liq tests     # format (line length 100)
ruff check kamino_liq tests      # lint (E/F/I/B/ANN/C4/UP/SIM)
pytest                           # run the unit tests
pytest --cov=kamino_liq          # with coverage (enforced at 100%)
pylint kamino_liq                # static analysis (expects a clean 10.00/10)
```

The suite mocks all HTTP/RPC calls, so it runs offline and deterministically.
Ruff settings live in `ruff.toml`; coverage and pylint settings in `pyproject.toml`.
If you use Claude Code, `.claude/` ships hooks that run ruff on each edit and the
full gate (ruff + pytest + pylint) when a turn ends.

## Disclaimer

This is an informational tool, not financial advice. Prices and on-chain state
change continuously and liquidation depends on the protocol's live oracle at the
moment of liquidation. Always verify against the official Kamino app.
