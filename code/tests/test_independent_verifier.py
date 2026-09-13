import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/buyorwait/independent_verifier.py."""

import unittest
from datetime import date
from decimal import Decimal

from buyorwait.csv_format import parse_payment_plan
from buyorwait.independent_verifier import replay_plan


class ExactTwoPaymentPartialPlanTests(unittest.TestCase):
    """Mirrors the shape of the real sample request_19 (evaluation/inventory.md):
    pay part today, the rest on a later date, no floor breach either time."""

    def test_valid_partial_plan_is_fully_valid(self):
        # By hand: requested 39660. Pay 28820 today (2024-09-04), remaining
        # 10840 on 2024-09-15. 28820 + 10840 = 39660 exactly.
        plan = parse_payment_plan("2024-09-04:28820|2024-09-15:10840")
        result = replay_plan(
            opening_balance=Decimal("199545.00"),
            minimum_balance_to_keep=Decimal("92800.00"),
            anchor_date=date(2024, 9, 4),
            flows=(),
            plan_entries=plan,
            requested_amount=Decimal("39660.00"),
            deadline=date(2024, 10, 4),
        )
        self.assertTrue(result.is_fully_valid)
        self.assertTrue(result.sums_to_requested_amount)
        self.assertTrue(result.completes_by_deadline)
        self.assertTrue(result.is_chronological)
        self.assertEqual(result.amount_gap, Decimal("0.00"))

    def test_plan_that_undershoots_the_requested_amount_is_flagged(self):
        plan = parse_payment_plan("2024-09-04:28820|2024-09-15:10000")  # short by 840
        result = replay_plan(
            opening_balance=Decimal("199545.00"),
            minimum_balance_to_keep=Decimal("92800.00"),
            anchor_date=date(2024, 9, 4),
            flows=(),
            plan_entries=plan,
            requested_amount=Decimal("39660.00"),
            deadline=date(2024, 10, 4),
        )
        self.assertFalse(result.sums_to_requested_amount)
        self.assertEqual(result.amount_gap, Decimal("840.00"))
        self.assertFalse(result.is_fully_valid)

    def test_second_payment_after_deadline_is_flagged(self):
        plan = parse_payment_plan("2024-09-04:28820|2024-10-10:10840")  # after the deadline
        result = replay_plan(
            opening_balance=Decimal("199545.00"),
            minimum_balance_to_keep=Decimal("92800.00"),
            anchor_date=date(2024, 9, 4),
            flows=(),
            plan_entries=plan,
            requested_amount=Decimal("39660.00"),
            deadline=date(2024, 10, 4),
        )
        self.assertFalse(result.completes_by_deadline)
        self.assertFalse(result.is_fully_valid)

    def test_deadline_is_inclusive(self):
        # Last payment lands EXACTLY on the deadline -- must count as on time
        # (S-05's "on or before").
        plan = parse_payment_plan("2024-09-04:28820|2024-10-04:10840")
        result = replay_plan(
            opening_balance=Decimal("199545.00"),
            minimum_balance_to_keep=Decimal("92800.00"),
            anchor_date=date(2024, 9, 4),
            flows=(),
            plan_entries=plan,
            requested_amount=Decimal("39660.00"),
            deadline=date(2024, 10, 4),
        )
        self.assertTrue(result.completes_by_deadline)


class FloorBreachDuringPlanTests(unittest.TestCase):
    def test_plan_that_breaches_the_floor_is_not_fully_valid(self):
        # By hand: opening 10000, minimum 9000. First payment 500 -> 9500 (safe).
        # Second payment 600 -> 8900, which is BELOW the 9000 minimum.
        plan = parse_payment_plan("2024-01-05:500|2024-02-05:600")
        result = replay_plan(
            opening_balance=Decimal("10000.00"),
            minimum_balance_to_keep=Decimal("9000.00"),
            anchor_date=date(2024, 1, 1),
            flows=(),
            plan_entries=plan,
            requested_amount=Decimal("1100.00"),
            deadline=date(2024, 3, 1),
        )
        self.assertFalse(result.simulation.is_safe)
        self.assertFalse(result.is_fully_valid)
        self.assertEqual(result.simulation.breaches[0].day, date(2024, 2, 5))
        self.assertEqual(result.simulation.breaches[0].shortfall, Decimal("100.00"))


class NoPaymentPlanTests(unittest.TestCase):
    def test_none_plan_has_no_breach_and_completes_trivially(self):
        plan = parse_payment_plan("none")
        result = replay_plan(
            opening_balance=Decimal("100.00"),
            minimum_balance_to_keep=Decimal("50.00"),
            anchor_date=date(2024, 1, 1),
            flows=(),
            plan_entries=plan,
            requested_amount=Decimal("500.00"),
            deadline=date(2024, 3, 1),
        )
        self.assertTrue(result.simulation.is_safe)
        self.assertTrue(result.completes_by_deadline)
        self.assertFalse(result.sums_to_requested_amount)  # 0 paid != 500 requested
        self.assertEqual(result.amount_gap, Decimal("500.00"))


if __name__ == "__main__":
    unittest.main()
