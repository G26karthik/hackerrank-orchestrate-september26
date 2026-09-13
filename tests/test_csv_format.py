import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/buyorwait/csv_format.py -- the parse/serialize contract
shared by writer.py and code/evaluation/metrics.py.
"""

import unittest
from datetime import date
from decimal import Decimal

from buyorwait.csv_format import (
    CsvFormatError,
    PlanEntry,
    ReduceChange,
    StopChange,
    is_chronological,
    parse_payment_plan,
    parse_spending_changes,
    serialize_payment_plan,
    serialize_spending_changes,
)


class PaymentPlanParseTests(unittest.TestCase):
    def test_none_parses_to_empty_tuple(self):
        self.assertEqual(parse_payment_plan("none"), ())

    def test_single_entry(self):
        self.assertEqual(
            parse_payment_plan("2024-03-03:25256"),
            (PlanEntry(date(2024, 3, 3), Decimal("25256")),),
        )

    def test_multi_entry_installments(self):
        # request_17's real installment plan (evaluation/inventory.md samples).
        got = parse_payment_plan("2026-03-01:95194.67|2026-03-31:95194.67|2026-04-30:95194.67")
        self.assertEqual(
            got,
            (
                PlanEntry(date(2026, 3, 1), Decimal("95194.67")),
                PlanEntry(date(2026, 3, 31), Decimal("95194.67")),
                PlanEntry(date(2026, 4, 30), Decimal("95194.67")),
            ),
        )

    def test_blank_string_is_an_error_not_none(self):
        with self.assertRaises(CsvFormatError):
            parse_payment_plan("")

    def test_malformed_entry_raises(self):
        with self.assertRaises(CsvFormatError):
            parse_payment_plan("2024-03-03")  # no ":amount"
        with self.assertRaises(CsvFormatError):
            parse_payment_plan("not-a-date:100")


class PaymentPlanRoundTripTests(unittest.TestCase):
    def test_round_trip_none(self):
        self.assertEqual(serialize_payment_plan(parse_payment_plan("none")), "none")

    def test_round_trip_single(self):
        raw = "2026-07-04:166.61"
        self.assertEqual(serialize_payment_plan(parse_payment_plan(raw)), raw)

    def test_round_trip_multi_preserves_trailing_zero_formatting(self):
        raw = "2024-09-04:28820|2024-09-15:10840"
        self.assertEqual(serialize_payment_plan(parse_payment_plan(raw)), raw)

    def test_serialize_does_not_reorder_out_of_order_input(self):
        # Deliberately out of chronological order -- serialize must not "fix" it.
        entries = (
            PlanEntry(date(2026, 1, 1), Decimal("100")),
            PlanEntry(date(2025, 1, 1), Decimal("50")),
        )
        self.assertEqual(serialize_payment_plan(entries), "2026-01-01:100|2025-01-01:50")


class ChronologyTests(unittest.TestCase):
    def test_empty_and_single_are_chronological(self):
        self.assertTrue(is_chronological(()))
        self.assertTrue(is_chronological((PlanEntry(date(2024, 1, 1), Decimal("1")),)))

    def test_ordered_is_chronological(self):
        entries = (
            PlanEntry(date(2024, 1, 1), Decimal("1")),
            PlanEntry(date(2024, 2, 1), Decimal("1")),
        )
        self.assertTrue(is_chronological(entries))

    def test_same_date_twice_is_chronological(self):
        entries = (
            PlanEntry(date(2024, 1, 1), Decimal("1")),
            PlanEntry(date(2024, 1, 1), Decimal("1")),
        )
        self.assertTrue(is_chronological(entries))

    def test_out_of_order_is_not_chronological(self):
        entries = (
            PlanEntry(date(2024, 2, 1), Decimal("1")),
            PlanEntry(date(2024, 1, 1), Decimal("1")),
        )
        self.assertFalse(is_chronological(entries))


class SpendingChangesParseTests(unittest.TestCase):
    def test_none_parses_to_empty_tuple(self):
        self.assertEqual(parse_spending_changes("none"), ())

    def test_single_stop(self):
        self.assertEqual(parse_spending_changes("stop:event_14"), (StopChange("event_14"),))

    def test_stop_and_reduce_different_events(self):
        got = parse_spending_changes("stop:event_1815|reduce_to:event_1816:23.50")
        self.assertEqual(
            got,
            (StopChange("event_1815"), ReduceChange("event_1816", Decimal("23.50"))),
        )

    def test_reduce_with_whole_number_amount(self):
        got = parse_spending_changes("reduce_to:event_989:665950")
        self.assertEqual(got, (ReduceChange("event_989", Decimal("665950")),))

    def test_same_event_stop_and_reduce_is_rejected(self):
        with self.assertRaises(CsvFormatError):
            parse_spending_changes("stop:event_1|reduce_to:event_1:100")

    def test_same_event_twice_is_rejected(self):
        with self.assertRaises(CsvFormatError):
            parse_spending_changes("stop:event_1|stop:event_1")

    def test_more_than_three_actions_rejected(self):
        with self.assertRaises(CsvFormatError):
            parse_spending_changes("stop:event_1|stop:event_2|stop:event_3|stop:event_4")

    def test_unrecognized_action_word_rejected(self):
        with self.assertRaises(CsvFormatError):
            parse_spending_changes("cancel:event_1")

    def test_blank_string_is_an_error_not_none(self):
        with self.assertRaises(CsvFormatError):
            parse_spending_changes("")


class SpendingChangesRoundTripTests(unittest.TestCase):
    def test_round_trip_none(self):
        self.assertEqual(serialize_spending_changes(parse_spending_changes("none")), "none")

    def test_round_trip_stop_and_reduce(self):
        raw = "stop:event_1815|reduce_to:event_1816:23.50"
        self.assertEqual(serialize_spending_changes(parse_spending_changes(raw)), raw)

    def test_round_trip_whole_number_reduce(self):
        raw = "reduce_to:event_989:665950"
        self.assertEqual(serialize_spending_changes(parse_spending_changes(raw)), raw)


if __name__ == "__main__":
    unittest.main()
