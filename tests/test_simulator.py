import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Hand-checkable tests for code/buyorwait/simulator.py, the independent
reference cash-flow simulator. Every expected number below is derived by
hand from the inputs; none are copied from any production module (there is
no production forecast/planner yet to copy from).

Required coverage (Stage 2 instruction) and where each lives:
  1. opening balance                    -> OpeningBalanceTests
  2. reserved pending debits             -> ReservedPendingDebitTests
  3. intermediate floor violations       -> IntermediateFloorViolationTests
  4. historical-settlement exclusion     -> HistoricalSettlementExclusionTests
  5. same-day ordering                   -> SameDayOrderingTests
  6. date boundaries                     -> DateBoundaryTests
  7. full-schedule completion            -> FullScheduleCompletionTests
"""

import unittest
from datetime import date, timedelta
from decimal import Decimal

from buyorwait.simulator import (
    CashFlow,
    FlowKind,
    ScheduledPayment,
    SimulatorInputError,
    balance_on,
    simulate,
)

ANCHOR = date(2024, 1, 1)


class OpeningBalanceTests(unittest.TestCase):
    """No flows, no schedule: the balance is exactly the opening balance for
    the entire window, and the plan is trivially safe."""

    def test_no_activity_is_safe_and_balance_unchanged(self):
        result = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
        )
        self.assertTrue(result.is_safe)
        self.assertEqual(result.daily_balances, ())
        self.assertEqual(balance_on(result, ANCHOR), Decimal("1000.00"))
        self.assertEqual(balance_on(result, ANCHOR + timedelta(days=45)), Decimal("1000.00"))

    def test_balance_on_rejects_a_date_before_anchor(self):
        result = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
        )
        with self.assertRaises(SimulatorInputError):
            balance_on(result, ANCHOR - timedelta(days=1))


class ReservedPendingDebitTests(unittest.TestCase):
    """A pending debit must be subtracted from the balance even though it has
    not settled yet (S-16: "Reserve pending debits")."""

    def _flow(self, amount: Decimal) -> tuple[CashFlow, ...]:
        return (
            CashFlow(
                flow_date=date(2024, 1, 10),
                amount=-amount,
                kind=FlowKind.RESERVED_PENDING_DEBIT,
                label="pending telecom bill",
            ),
        )

    def test_reserved_debit_within_headroom_stays_safe(self):
        # By hand: 1000 - 750 = 250, which is >= the 200 minimum.
        result = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=self._flow(Decimal("750.00")),
        )
        self.assertTrue(result.is_safe)
        self.assertEqual(result.daily_balances[0].floor_check_balance, Decimal("250.00"))
        self.assertEqual(balance_on(result, date(2024, 1, 31)), Decimal("250.00"))

    def test_reserved_debit_that_breaches_the_floor_is_caught(self):
        # By hand: 1000 - 850 = 150, which is BELOW the 200 minimum by 50.
        # A simulator that forgot to reserve this pending debit would report
        # 1000 the whole way through and call the request safe -- this is
        # exactly the mistake S-16 exists to prevent.
        result = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=self._flow(Decimal("850.00")),
        )
        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.breaches), 1)
        self.assertEqual(result.breaches[0].shortfall, Decimal("50.00"))


class IntermediateFloorViolationTests(unittest.TestCase):
    """A dip in the middle of the window must be caught even when the
    balance recovers comfortably by the end -- checking only the final
    balance would call this scenario safe, which is exactly wrong."""

    def test_mid_window_dip_is_caught_even_with_a_healthy_final_balance(self):
        # By hand:
        #   opening 1000, minimum 200.
        #   day 30: debit 850  -> floor_check = 1000 - 850 = 150  (BREACH, short 50); end_of_day 150.
        #   day 60: credit 1000 (a later salary) -> floor_check = 150 - 0 = 150 (STILL a breach,
        #           because the balance has not recovered yet at the point debits are checked);
        #           end_of_day = 150 + 1000 = 1150.
        # Final balance 1150 is well above the 200 minimum -- exactly the
        # "temporary dip hidden by a good final balance" case.
        day30 = date(2024, 1, 30)
        day60 = date(2024, 2, 29)
        flows = (
            CashFlow(day30, Decimal("-850.00"), FlowKind.OTHER, "rent+utilities pile-up"),
            CashFlow(day60, Decimal("1000.00"), FlowKind.CONFIRMED_INCOME, "later salary"),
        )
        result = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=flows,
            same_day_order="debits_first",
        )
        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.breaches), 2)
        self.assertEqual(result.breaches[0].day, day30)
        self.assertEqual(result.breaches[0].shortfall, Decimal("50.00"))
        self.assertEqual(result.breaches[1].day, day60)
        self.assertEqual(result.breaches[1].shortfall, Decimal("50.00"))
        # And yet the final balance looks perfectly healthy:
        self.assertEqual(balance_on(result, date(2024, 3, 15)), Decimal("1150.00"))
        self.assertGreater(balance_on(result, date(2024, 3, 15)), Decimal("200.00"))


class HistoricalSettlementExclusionTests(unittest.TestCase):
    """A flow dated before the anchor is already reflected in the opening
    balance; passing one in is a caller bug, not silently-ignorable input."""

    def test_flow_before_anchor_raises(self):
        flows = (
            CashFlow(ANCHOR - timedelta(days=1), Decimal("-100.00"), FlowKind.OTHER, "yesterday's groceries"),
        )
        with self.assertRaises(SimulatorInputError):
            simulate(
                opening_balance=Decimal("1000.00"),
                minimum_balance_to_keep=Decimal("200.00"),
                anchor_date=ANCHOR,
                flows=flows,
            )

    def test_flow_on_the_anchor_date_itself_is_allowed(self):
        # The anchor day is the FIRST day of the forecast, not history -- a
        # same-day candidate payment or pending item belongs here.
        flows = (CashFlow(ANCHOR, Decimal("-100.00"), FlowKind.OTHER, "same-day debit"),)
        result = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        self.assertTrue(result.is_safe)

    def test_scheduled_payment_before_anchor_raises(self):
        schedule = (ScheduledPayment(ANCHOR - timedelta(days=1), Decimal("100.00")),)
        with self.assertRaises(SimulatorInputError):
            simulate(
                opening_balance=Decimal("1000.00"),
                minimum_balance_to_keep=Decimal("200.00"),
                anchor_date=ANCHOR,
                schedule=schedule,
            )


class SameDayOrderingTests(unittest.TestCase):
    """U-SIMORDER-1: tests both debits_first and credits_first same-day ordering modes."""

    def test_same_day_debit_before_credit_reveals_an_intraday_breach(self):
        # Under debits-first:
        #   opening 500, minimum 400.
        #   day 5: debit 150 AND credit 200 land the same day.
        #   debits-first: floor_check = 500 - 150 = 350  -> BELOW 400 (breach, short 50)
        #   end_of_day = 350 + 200 = 550  -> comfortably ABOVE 400.
        day = date(2024, 1, 5)
        flows = (
            CashFlow(day, Decimal("-150.00"), FlowKind.OTHER, "same-day debit"),
            CashFlow(day, Decimal("200.00"), FlowKind.CONFIRMED_INCOME, "same-day credit"),
        )
        result = simulate(
            opening_balance=Decimal("500.00"),
            minimum_balance_to_keep=Decimal("400.00"),
            anchor_date=ANCHOR,
            flows=flows,
            same_day_order="debits_first",
        )
        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.breaches), 1)
        self.assertEqual(result.breaches[0].day, day)
        self.assertEqual(result.breaches[0].shortfall, Decimal("50.00"))
        self.assertEqual(result.daily_balances[0].balance_end_of_day, Decimal("550.00"))
        self.assertGreaterEqual(result.daily_balances[0].balance_end_of_day, Decimal("400.00"))

    def test_same_day_credits_first_clears_income_before_debit(self):
        # Under credits-first (production default):
        #   opening 500, minimum 400.
        #   day 5: debit 150 AND credit 200 land the same day.
        #   credits-first: floor_check = 500 + 200 - 150 = 550  -> safe (above 400)
        day = date(2024, 1, 5)
        flows = (
            CashFlow(day, Decimal("-150.00"), FlowKind.OTHER, "same-day debit"),
            CashFlow(day, Decimal("200.00"), FlowKind.CONFIRMED_INCOME, "same-day credit"),
        )
        result = simulate(
            opening_balance=Decimal("500.00"),
            minimum_balance_to_keep=Decimal("400.00"),
            anchor_date=ANCHOR,
            flows=flows,
            same_day_order="credits_first",
        )
        self.assertTrue(result.is_safe)
        self.assertEqual(len(result.breaches), 0)
        self.assertEqual(result.daily_balances[0].floor_check_balance, Decimal("550.00"))
        self.assertEqual(result.daily_balances[0].balance_end_of_day, Decimal("550.00"))


class DateBoundaryTests(unittest.TestCase):
    """U-WINDOW-1: the forecast window is [anchor, anchor + 90 days]
    INCLUSIVE of both ends."""

    def test_flow_exactly_on_the_horizon_end_is_allowed(self):
        horizon_end = ANCHOR + timedelta(days=90)
        flows = (CashFlow(horizon_end, Decimal("-1.00"), FlowKind.OTHER, "last allowed day"),)
        result = simulate(
            opening_balance=Decimal("100.00"),
            minimum_balance_to_keep=Decimal("0.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        self.assertEqual(result.horizon_end, horizon_end)
        self.assertTrue(result.is_safe)

    def test_flow_one_day_beyond_the_horizon_raises(self):
        one_day_too_late = ANCHOR + timedelta(days=91)
        flows = (CashFlow(one_day_too_late, Decimal("-1.00"), FlowKind.OTHER, "too late"),)
        with self.assertRaises(SimulatorInputError):
            simulate(
                opening_balance=Decimal("100.00"),
                minimum_balance_to_keep=Decimal("0.00"),
                anchor_date=ANCHOR,
                flows=flows,
            )

    def test_custom_horizon_is_respected(self):
        result = simulate(
            opening_balance=Decimal("100.00"),
            minimum_balance_to_keep=Decimal("0.00"),
            anchor_date=ANCHOR,
            horizon_days=30,
        )
        self.assertEqual(result.horizon_end, ANCHOR + timedelta(days=30))


class FullScheduleCompletionTests(unittest.TestCase):
    """A multi-payment schedule (e.g. an n=3 installment plan) that stays
    safe start to finish, and whose total is exactly trackable."""

    def test_three_installments_all_safe_and_total_matches(self):
        # By hand: opening 10,000, minimum 100. Three payments of 3000 each
        # on days 5, 35, 65 -- balance after each: 7000, 4000, 1000. Every
        # one is >= the 100 minimum. Total paid: 9000.
        schedule = (
            ScheduledPayment(date(2024, 1, 6), Decimal("3000.00"), "installment 1"),
            ScheduledPayment(date(2024, 2, 5), Decimal("3000.00"), "installment 2"),
            ScheduledPayment(date(2024, 3, 6), Decimal("3000.00"), "installment 3"),
        )
        result = simulate(
            opening_balance=Decimal("10000.00"),
            minimum_balance_to_keep=Decimal("100.00"),
            anchor_date=ANCHOR,
            schedule=schedule,
        )
        self.assertTrue(result.is_safe)
        self.assertEqual(result.total_scheduled_paid, Decimal("9000.00"))
        self.assertEqual(len(result.daily_balances), 3)
        self.assertEqual(result.daily_balances[0].balance_end_of_day, Decimal("7000.00"))
        self.assertEqual(result.daily_balances[1].balance_end_of_day, Decimal("4000.00"))
        self.assertEqual(result.daily_balances[2].balance_end_of_day, Decimal("1000.00"))

    def test_schedule_that_breaches_partway_through_is_caught(self):
        # By hand: opening 5000, minimum 1000. Payments of 3000 then 3000:
        # after payment 1 -> 2000 (safe); after payment 2 -> -1000 (BREACH, short 2000).
        schedule = (
            ScheduledPayment(date(2024, 1, 10), Decimal("3000.00"), "installment 1"),
            ScheduledPayment(date(2024, 2, 10), Decimal("3000.00"), "installment 2"),
        )
        result = simulate(
            opening_balance=Decimal("5000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
            anchor_date=ANCHOR,
            schedule=schedule,
        )
        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.breaches), 1)
        self.assertEqual(result.breaches[0].day, date(2024, 2, 10))
        self.assertEqual(result.breaches[0].shortfall, Decimal("2000.00"))

    def test_non_positive_scheduled_payment_rejected(self):
        with self.assertRaises(SimulatorInputError):
            simulate(
                opening_balance=Decimal("1000.00"),
                minimum_balance_to_keep=Decimal("0.00"),
                anchor_date=ANCHOR,
                schedule=(ScheduledPayment(date(2024, 1, 10), Decimal("0.00")),),
            )


if __name__ == "__main__":
    unittest.main()
