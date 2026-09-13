import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/buyorwait/writer.py."""

import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from buyorwait.csv_format import parse_payment_plan, parse_spending_changes
from buyorwait.schemas import AffordabilityStatus, RecommendedPaymentMethod
from buyorwait.writer import REQUIRED_COLUMNS, OutputRow, to_csv_dict, write_output_csv


def _row(**overrides) -> OutputRow:
    defaults = dict(
        request_id="request_01",
        amount_safe_to_pay=Decimal("25256.00"),
        affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
        recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
        payment_plan=parse_payment_plan("2024-03-03:25256"),
        earliest_date_for_full_payment=date(2024, 3, 3),
        spending_changes_needed=(),
        decision_explanation="Pay ZAR 25,256 today.",
    )
    defaults.update(overrides)
    return OutputRow(**defaults)


class ToCsvDictTests(unittest.TestCase):
    def test_matches_sample_request_01_exactly(self):
        got = to_csv_dict(_row())
        self.assertEqual(got["amount_safe_to_pay"], "25256")  # trimmed, per format_capacity_amount
        self.assertEqual(got["affordability_status"], "affordable_now")
        self.assertEqual(got["recommended_payment_method"], "full_payment")
        self.assertEqual(got["payment_plan"], "2024-03-03:25256")
        self.assertEqual(got["earliest_date_for_full_payment"], "2024-03-03")
        self.assertEqual(got["spending_changes_needed"], "none")

    def test_empty_earliest_date_serializes_to_empty_string_not_none(self):
        got = to_csv_dict(_row(earliest_date_for_full_payment=None, payment_plan=(),
                                affordability_status=AffordabilityStatus.NOT_AFFORDABLE,
                                recommended_payment_method=RecommendedPaymentMethod.NOT_RECOMMENDED))
        self.assertEqual(got["earliest_date_for_full_payment"], "")
        self.assertEqual(got["payment_plan"], "none")

    def test_spending_changes_round_trip_through_the_row(self):
        changes = parse_spending_changes("stop:event_1815|reduce_to:event_1816:23.50")
        got = to_csv_dict(_row(spending_changes_needed=changes))
        self.assertEqual(got["spending_changes_needed"], "stop:event_1815|reduce_to:event_1816:23.50")

    def test_fractional_capacity_amount_is_trimmed_not_schedule_formatted(self):
        got = to_csv_dict(_row(amount_safe_to_pay=Decimal("603.30")))
        self.assertEqual(got["amount_safe_to_pay"], "603.3")


class WriteOutputCsvTests(unittest.TestCase):
    def test_header_and_column_order_match_the_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.csv"
            write_output_csv(path, [_row()])
            raw = path.read_bytes()
            # Exact header line, CRLF-terminated, matching dataset/output.csv.
            self.assertTrue(raw.startswith(",".join(REQUIRED_COLUMNS).encode() + b"\r\n"))

    def test_row_count_matches_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.csv"
            rows = [_row(request_id=f"request_{i}") for i in range(5)]
            write_output_csv(path, rows)
            with path.open(newline="", encoding="utf-8") as fh:
                read_rows = list(csv.DictReader(fh))
            self.assertEqual(len(read_rows), 5)
            self.assertEqual([r["request_id"] for r in read_rows], [f"request_{i}" for i in range(5)])

    def test_uses_crlf_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.csv"
            write_output_csv(path, [_row(), _row(request_id="request_02")])
            raw = path.read_bytes()
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))
            self.assertNotIn(b"\n\n", raw.replace(b"\r\n", b""))


if __name__ == "__main__":
    unittest.main()
