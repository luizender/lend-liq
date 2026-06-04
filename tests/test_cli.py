"""Tests for the Typer CLI, with all I/O monkeypatched."""

import types

from typer.testing import CliRunner

from kamino_liq import cli
from kamino_liq.models import Reserve, RpcNode

runner = CliRunner()
WALLET = "11111111111111111111111111111111"  # valid base58 (system program)


def patch_clients(monkeypatch, kamino, solana=None):
    monkeypatch.setattr(cli, "KaminoClient", lambda *a, **k: kamino)
    monkeypatch.setattr(cli, "SolanaRPC", lambda *a, **k: solana or object())


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "kamino-liq" in result.output


def test_report_found(monkeypatch, fake_kamino, market, sample_position) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    # Two positions in the same market exercise the de-dup in _report_once.
    monkeypatch.setattr(
        cli,
        "load_positions",
        lambda c, r, w, m, on_scan=None: [(market, sample_position), (market, sample_position)],
    )
    result = runner.invoke(cli.app, ["report", WALLET])
    assert result.exit_code == 0
    assert "Health factor" in result.output


def test_report_not_found(monkeypatch, fake_kamino, market) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    monkeypatch.setattr(cli, "load_positions", lambda c, r, w, m, on_scan=None: [])
    result = runner.invoke(cli.app, ["report", WALLET])
    assert "No Kamino Lend positions" in result.output


def test_report_invalid_wallet() -> None:
    result = runner.invoke(cli.app, ["report", "not-a-key!"])
    assert result.exit_code != 0


def test_report_unknown_market(monkeypatch, fake_kamino, market) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    result = runner.invoke(cli.app, ["report", WALLET, "--market", "NOPE"])
    assert result.exit_code != 0


def test_report_market_filter(monkeypatch, fake_kamino, market, sample_position) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    monkeypatch.setattr(
        cli, "load_positions", lambda c, r, w, m, on_scan=None: [(market, sample_position)]
    )
    result = runner.invoke(cli.app, ["report", WALLET, "--market", "MKT", "--no-crash"])
    assert result.exit_code == 0


def test_report_watch_invokes_watch(monkeypatch, fake_kamino, market) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    called = {}
    monkeypatch.setattr(cli, "_watch", lambda *a: called.setdefault("watched", True))
    result = runner.invoke(cli.app, ["report", WALLET, "--watch"])
    assert result.exit_code == 0
    assert called.get("watched") is True


def test_simulate_command(monkeypatch, fake_kamino, market, sample_position) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    monkeypatch.setattr(
        cli, "load_positions", lambda c, r, w, m, on_scan=None: [(market, sample_position)]
    )
    result = runner.invoke(cli.app, ["simulate", WALLET, "-p", "SOL=50"])
    assert result.exit_code == 0
    assert "Simulation" in result.output
    assert "Simulated price changes" in result.output


def test_simulate_warns_on_unheld_symbol(monkeypatch, fake_kamino, market, sample_position) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    monkeypatch.setattr(
        cli, "load_positions", lambda c, r, w, m, on_scan=None: [(market, sample_position)]
    )
    result = runner.invoke(cli.app, ["simulate", WALLET, "-p", "SOL=50", "-p", "BONK=1"])
    assert result.exit_code == 0
    assert "No position holds: BONK" in result.output


def test_simulate_not_found(monkeypatch, fake_kamino, market) -> None:
    patch_clients(monkeypatch, fake_kamino(markets=[market]))
    monkeypatch.setattr(cli, "load_positions", lambda c, r, w, m, on_scan=None: [])
    result = runner.invoke(cli.app, ["simulate", WALLET, "-p", "SOL=50"])
    assert "No Kamino Lend positions" in result.output


def test_simulate_requires_a_price() -> None:
    result = runner.invoke(cli.app, ["simulate", WALLET])
    assert result.exit_code != 0


def test_simulate_rejects_bad_price_format() -> None:
    result = runner.invoke(cli.app, ["simulate", WALLET, "-p", "SOL"])
    assert result.exit_code != 0


def test_simulate_rejects_non_numeric_price() -> None:
    result = runner.invoke(cli.app, ["simulate", WALLET, "-p", "SOL=cheap"])
    assert result.exit_code != 0


def test_markets_command(monkeypatch, fake_kamino, market) -> None:
    monkeypatch.setattr(cli, "KaminoClient", lambda *a, **k: fake_kamino(markets=[market]))
    result = runner.invoke(cli.app, ["markets"])
    assert "Main Market" in result.output


def test_reserves_command_primary(monkeypatch, fake_kamino, market) -> None:
    kamino = fake_kamino(markets=[market], reserves={"R": Reserve("R", "SOL", "M", 0.7)})
    patch_clients(monkeypatch, kamino)
    monkeypatch.setattr(
        cli, "enrich_reserves", lambda rpc, rs: {"R": Reserve("R", "SOL", "M", 0.7, 0.75, 9)}
    )
    result = runner.invoke(cli.app, ["reserves"])
    assert result.exit_code == 0
    assert "SOL" in result.output


def test_reserves_command_with_market(monkeypatch, fake_kamino, market) -> None:
    kamino = fake_kamino(markets=[market], reserves={"R": Reserve("R", "USDC", "M", 0.8)})
    patch_clients(monkeypatch, kamino)
    monkeypatch.setattr(
        cli, "enrich_reserves", lambda rpc, rs: {"R": Reserve("R", "USDC", "M", 0.8, 0.85, 6)}
    )
    result = runner.invoke(cli.app, ["reserves", "--market", "MKT"])
    assert result.exit_code == 0
    assert "USDC" in result.output


def test_rpcs_command(monkeypatch) -> None:
    fake_rpc = types.SimpleNamespace(cluster_nodes=lambda: [RpcNode("P", "1.2.3.4:8899", "1.0")])
    monkeypatch.setattr(cli, "SolanaRPC", lambda *a, **k: fake_rpc)
    result = runner.invoke(cli.app, ["rpcs", "--limit", "5"])
    assert "1.2.3.4:8899" in result.output


def test_watch_narrows_markets_and_survives_errors(monkeypatch, market) -> None:
    calls = {"n": 0}

    def report_once(wallet, client, solana, markets, crash):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")  # exercises the except branch
        return [market]  # exercises the narrowing branch

    def sleep(_seconds):
        if calls["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_report_once", report_once)
    monkeypatch.setattr(cli.time, "sleep", sleep)
    cli._watch("W", object(), object(), [market], crash=True, interval=1)
    assert calls["n"] == 2


def test_watch_with_no_active_markets(monkeypatch, market) -> None:
    def report_once(*_args):
        return []

    def sleep(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_report_once", report_once)
    monkeypatch.setattr(cli.time, "sleep", sleep)
    cli._watch("W", object(), object(), [market], crash=True, interval=1)
