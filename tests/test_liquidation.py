"""Unit tests for the pure liquidation math."""

import math
from collections.abc import Iterable

from lend_liq.liquidation import (
    AmountChange,
    CrashStatus,
    apply_overrides,
    crash_scenario,
    single_asset_levels,
)
from lend_liq.models import Borrow, Collateral, Position


def make_position(
    collateral: Iterable[Collateral],
    debt_value: float,
    borrows: Iterable[Borrow] = (),
) -> Position:
    return Position("Test", "obligation", tuple(collateral), tuple(borrows), debt_value)


def test_position_health_metrics() -> None:
    # 100 SOL @ $100, liq threshold 0.8 -> deposit 10_000, limit 8_000; debt 4_000.
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_000)
    assert pos.deposit_value == 10_000
    assert pos.liquidation_limit == 8_000
    assert pos.current_ltv == 0.4
    assert pos.liquidation_ltv == 0.8
    assert pos.health_factor == 2.0
    assert pos.drop_to_liquidation == 0.5


def test_single_asset_liquidation_price() -> None:
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_000)
    (level,) = single_asset_levels(pos)
    # Liquidation when price * 100 * 0.8 == 4_000 -> price 50.
    assert level.price == 50
    assert level.buffer == 0.5
    assert not level.is_safe


def test_collateral_safe_when_others_cover_debt() -> None:
    a = Collateral("A", amount=10, price=100, liquidation_threshold=0.8)  # weighted 800
    b = Collateral("B", amount=10, price=100, liquidation_threshold=0.8)  # weighted 800
    pos = make_position([a, b], debt_value=500)
    levels = {lvl.collateral.symbol: lvl for lvl in single_asset_levels(pos)}
    # Dropping A alone: B's weighted 800 already exceeds the 500 debt -> safe at $0.
    assert levels["A"].is_safe
    assert levels["A"].price is None
    assert levels["A"].buffer is None


def test_health_factor_infinite_without_debt() -> None:
    sol = Collateral("SOL", amount=1, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=0)
    assert pos.has_debt is False
    assert math.isinf(pos.health_factor)


def test_crash_safe_when_stables_cover_debt() -> None:
    usdc = Collateral("USDC", amount=1_000, price=1.0, liquidation_threshold=0.9)  # weighted 900
    sol = Collateral("SOL", amount=10, price=100, liquidation_threshold=0.8)
    pos = make_position([usdc, sol], debt_value=800)
    assert crash_scenario(pos).status is CrashStatus.SAFE


def test_crash_triggerable_drop_and_prices() -> None:
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)  # volatile
    pos = make_position([sol], debt_value=4_000)
    scenario = crash_scenario(pos)
    assert scenario.status is CrashStatus.TRIGGERABLE
    assert scenario.drop == 0.5  # remaining = 4000 / 8000
    ((collateral, price),) = scenario.prices
    assert collateral.symbol == "SOL"
    assert price == 50


def test_crash_at_risk_when_already_underwater() -> None:
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)  # limit 8_000
    pos = make_position([sol], debt_value=9_000)
    assert crash_scenario(pos).status is CrashStatus.AT_RISK


def test_crash_exceeded_when_only_stables_and_debt_too_high() -> None:
    usdc = Collateral("USDC", amount=100, price=1.0, liquidation_threshold=0.9)  # cap 90
    pos = make_position([usdc], debt_value=100)  # no volatile buffer, debt > 90
    assert crash_scenario(pos).status is CrashStatus.EXCEEDED


def test_single_asset_zero_threshold_is_safe() -> None:
    # A zero-threshold collateral has no liquidation price (denominator is 0).
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.0)
    pos = make_position([sol], debt_value=1_000)
    (level,) = single_asset_levels(pos)
    assert level.is_safe
    assert level.buffer is None


def test_crash_gated_when_debt_is_volatile() -> None:
    # A SOL crash would also move a SOL-denominated debt, so the uniform-crash
    # model is suppressed rather than holding the debt fixed.
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_000, borrows=[Borrow("BTC", 0.1, 40_000)])
    assert crash_scenario(pos).status is CrashStatus.VOLATILE_DEBT


def test_apply_overrides_reprices_collateral_and_keeps_stable_debt() -> None:
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_000, borrows=[Borrow("USDC", 4_000, 1.0)])
    simulated = apply_overrides(pos, {"SOL": 50.0})
    assert simulated.collateral[0].price == 50.0
    # Stable debt price is unchanged, so the adjusted debt is untouched.
    assert simulated.debt_value == 4_000
    assert simulated.health_factor == 1.0  # 50*100*0.8 / 4000


def test_apply_overrides_rescales_volatile_debt() -> None:
    # debt_value carries a 1.2x borrow factor (4800 adjusted on 4000 borrowed).
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_800, borrows=[Borrow("ETH", 2, 2_000)])
    simulated = apply_overrides(pos, {"ETH": 1_000.0})  # halve the debt price
    assert simulated.borrows[0].price == 1_000.0
    assert simulated.debt_value == 2_400  # factor 1.2 preserved on the new 2000 borrowed


def test_apply_overrides_without_borrows_is_a_noop_on_debt() -> None:
    sol = Collateral("SOL", amount=10, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=0)
    simulated = apply_overrides(pos, {"DOGE": 1.0})  # symbol not held -> no change
    assert simulated.collateral[0].price == 100
    assert simulated.debt_value == 0


def test_amount_change_delta_and_absolute() -> None:
    assert AmountChange(10.0, is_delta=True).applied_to(5) == 15.0  # add to current
    assert AmountChange(-8.0, is_delta=True).applied_to(5) == 0.0  # floored, not -3
    assert AmountChange(20.0, is_delta=False).applied_to(5) == 20.0  # set outright


def test_apply_overrides_increases_collateral_amount() -> None:
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_000, borrows=[Borrow("USDC", 4_000, 1.0)])
    simulated = apply_overrides(pos, {}, {"SOL": AmountChange(50.0, is_delta=True)})
    assert simulated.collateral[0].amount == 150  # 100 + 50 deposited
    assert simulated.debt_value == 4_000  # collateral change leaves the debt alone
    assert simulated.health_factor == 3.0  # 150*100*0.8 / 4000


def test_apply_overrides_changing_borrow_amount_rescales_debt() -> None:
    # 1.2x borrow factor: 4800 adjusted on 4000 borrowed (ETH 2 @ 2000).
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_800, borrows=[Borrow("ETH", 2, 2_000)])
    simulated = apply_overrides(pos, {}, {"ETH": AmountChange(-1.0, is_delta=True)})  # repay 1 ETH
    assert simulated.borrows[0].amount == 1
    assert simulated.debt_value == 2_400  # factor 1.2 preserved on the new 2000 borrowed


def test_apply_overrides_sets_absolute_amount() -> None:
    sol = Collateral("SOL", amount=100, price=100, liquidation_threshold=0.8)
    pos = make_position([sol], debt_value=4_000, borrows=[Borrow("USDC", 4_000, 1.0)])
    simulated = apply_overrides(pos, {}, {"SOL": AmountChange(50.0, is_delta=False)})
    assert simulated.collateral[0].amount == 50  # set outright, not 150


def test_position_without_collateral_has_zero_metrics() -> None:
    pos = make_position([], debt_value=100)
    assert pos.deposit_value == 0
    assert pos.current_ltv == 0.0
    assert pos.liquidation_ltv == 0.0
    assert pos.drop_to_liquidation == 0.0
    assert pos.health_factor == 0.0
