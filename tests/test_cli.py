"""Tests for the Typer CLI, with all I/O monkeypatched."""

from typer.testing import CliRunner

from lend_liq import cli

runner = CliRunner()
WALLET = "11111111111111111111111111111111"  # valid base58 (system program)
EVM = "0x" + "ab" * 20


def patch_resolve(monkeypatch, protocol, loader, reserves=None):
    """Replace the protocol seam so the CLI runs without any I/O."""
    res = reserves or (lambda m, s: None)
    monkeypatch.setattr(cli.sources, "resolve", lambda wallet, p, c: (protocol, loader, res))


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "lend-liq" in result.output


def test_report_found(monkeypatch, sample_position) -> None:
    # Two positions exercise the rendering loop.
    patch_resolve(monkeypatch, "kamino", lambda: [sample_position, sample_position])
    result = runner.invoke(cli.app, ["report", WALLET])
    assert result.exit_code == 0
    assert "Health factor" in result.output


def test_report_not_found(monkeypatch) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [])
    result = runner.invoke(cli.app, ["report", WALLET])
    assert "No Kamino Lend positions" in result.output


def test_report_aave_not_found(monkeypatch) -> None:
    patch_resolve(monkeypatch, "aave", lambda: [])
    result = runner.invoke(cli.app, ["report", EVM, "--chain", "ethereum"])
    assert "No Aave positions" in result.output


def test_report_aave_chain_all(monkeypatch, sample_position) -> None:
    # "all" is a valid --chain choice (the every-chain sweep).
    patch_resolve(monkeypatch, "aave", lambda: [sample_position])
    result = runner.invoke(cli.app, ["report", EVM, "--chain", "all"])
    assert result.exit_code == 0
    assert "Health factor" in result.output


def test_report_invalid_wallet() -> None:
    result = runner.invoke(cli.app, ["report", "not-a-key!"])
    assert result.exit_code != 0


def test_report_rejects_unknown_protocol() -> None:
    # Typer rejects the enum choice before our code runs.
    result = runner.invoke(cli.app, ["report", WALLET, "-P", "compound"])
    assert result.exit_code != 0


def test_report_rejects_unknown_chain() -> None:
    result = runner.invoke(cli.app, ["report", EVM, "-c", "solana"])
    assert result.exit_code != 0


def test_report_no_crash(monkeypatch, sample_position) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [sample_position])
    result = runner.invoke(cli.app, ["report", WALLET, "--no-crash"])
    assert result.exit_code == 0


def test_report_watch_invokes_watch(monkeypatch) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [])
    called = {}
    monkeypatch.setattr(cli, "_watch", lambda *a: called.setdefault("watched", True))
    result = runner.invoke(cli.app, ["report", WALLET, "--watch"])
    assert result.exit_code == 0
    assert called.get("watched") is True


def test_simulate_command(monkeypatch, sample_position) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [sample_position])
    result = runner.invoke(cli.app, ["simulate", WALLET, "-p", "SOL=50"])
    assert result.exit_code == 0
    assert "Simulation" in result.output
    assert "Simulated price changes" in result.output


def test_simulate_warns_on_unheld_symbol(monkeypatch, sample_position) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [sample_position])
    result = runner.invoke(cli.app, ["simulate", WALLET, "-p", "SOL=50", "-p", "BONK=1"])
    assert result.exit_code == 0
    assert "No position holds: BONK" in result.output


def test_simulate_amount_option(monkeypatch, sample_position) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [sample_position])
    result = runner.invoke(cli.app, ["simulate", WALLET, "-a", "SOL=+10"])
    assert result.exit_code == 0
    assert "Simulated amount changes" in result.output


def test_simulate_warns_on_unheld_amount_symbol(monkeypatch, sample_position) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [sample_position])
    result = runner.invoke(cli.app, ["simulate", WALLET, "-a", "BONK=+1"])
    assert result.exit_code == 0
    assert "No position holds: BONK" in result.output


def test_simulate_rejects_bad_amount_format() -> None:
    result = runner.invoke(cli.app, ["simulate", WALLET, "-a", "SOL"])
    assert result.exit_code != 0


def test_simulate_rejects_non_numeric_amount() -> None:
    result = runner.invoke(cli.app, ["simulate", WALLET, "-a", "SOL=lots"])
    assert result.exit_code != 0


def test_simulate_not_found(monkeypatch) -> None:
    patch_resolve(monkeypatch, "kamino", lambda: [])
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


def test_watch_survives_errors(monkeypatch) -> None:
    calls = {"n": 0}

    def report_once(wallet, label, loader, crash):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")  # exercises the except branch

    def sleep(_seconds):
        if calls["n"] >= 2:
            raise KeyboardInterrupt  # exercises the second (clean) pass, then stops

    monkeypatch.setattr(cli, "_report_once", report_once)
    monkeypatch.setattr(cli.time, "sleep", sleep)
    cli._watch("W", "Kamino Lend", lambda: [], crash=True, interval=1)
    assert calls["n"] == 2


def test_simulate_add_collateral_success(monkeypatch, sample_position) -> None:
    from lend_liq.models import ReserveInfo

    def fake_reserves(market_id, symbol):
        if symbol.upper() == "PYUSD":
            return ReserveInfo("PYUSD", 1.0, 0.9, 1.0)
        return None

    patch_resolve(monkeypatch, "kamino", lambda: [sample_position], reserves=fake_reserves)
    result = runner.invoke(cli.app, ["simulate", WALLET, "-a", "PYUSD=300"])
    assert result.exit_code == 0
    assert "PYUSD" in result.output
    assert "new" in result.output
    assert "No position holds: PYUSD" not in result.output


def test_simulate_add_borrow_success(monkeypatch, sample_position) -> None:
    from lend_liq.models import ReserveInfo

    def fake_reserves(market_id, symbol):
        if symbol.upper() == "SOL":
            return ReserveInfo("SOL", 100.0, 0.8, 1.2)
        return None

    patch_resolve(monkeypatch, "kamino", lambda: [sample_position], reserves=fake_reserves)
    result = runner.invoke(cli.app, ["simulate", WALLET, "-b", "SOL=3"])
    assert result.exit_code == 0
    assert "SOL" in result.output
    assert "new" in result.output
    assert "No position holds: SOL" not in result.output


def test_simulate_borrow_rejects_bad_format() -> None:
    result = runner.invoke(cli.app, ["simulate", WALLET, "-b", "SOL"])
    assert result.exit_code != 0


def test_simulate_borrow_rejects_non_numeric() -> None:
    result = runner.invoke(cli.app, ["simulate", WALLET, "-b", "SOL=bad"])
    assert result.exit_code != 0
