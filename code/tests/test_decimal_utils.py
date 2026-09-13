import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Hand-checkable tests for code/buyorwait/decimal_utils.py.

The formatting expectations are transcribed directly from
evaluation/inventory.md O-29/O-30 (the 25 public samples), not invented.
"""

import unittest
from decimal import Decimal

from buyorwait.decimal_utils import (
    DecimalParseError,
    format_capacity_amount,
    format_schedule_amount,
    parse_decimal,
    parse_optional_decimal,
    quantize_money,
)


class ParseDecimalTests(unittest.TestCase):
    def test_parses_plain_number(self):
        self.assertEqual(parse_decimal("25256"), Decimal("25256"))

    def test_parses_fractional_number(self):
        self.assertEqual(parse_decimal("620.40"), Decimal("620.40"))

    def test_never_returns_float(self):
        # Decimal("620.40") == 620.4 is True in Python, so assert the TYPE too --
        # a bug that routed through float would still pass a bare equality check.
        result = parse_decimal("620.40")
        self.assertIsInstance(result, Decimal)

    def test_blank_raises_not_zero(self):
        with self.assertRaises(DecimalParseError):
            parse_decimal("")
        with self.assertRaises(DecimalParseError):
            parse_decimal("   ")

    def test_garbage_raises(self):
        with self.assertRaises(DecimalParseError):
            parse_decimal("not-a-number")


class ParseOptionalDecimalTests(unittest.TestCase):
    def test_blank_is_none_not_zero(self):
        # This is the S-21 guarantee: financial_events.amount blank must never
        # be indistinguishable from a real Decimal('0').
        result = parse_optional_decimal("")
        self.assertIsNone(result)
        self.assertNotEqual(result, Decimal("0"))

    def test_present_value_parses(self):
        self.assertEqual(parse_optional_decimal("1995.00"), Decimal("1995.00"))


class QuantizeMoneyTests(unittest.TestCase):
    def test_rounds_half_up(self):
        self.assertEqual(quantize_money(Decimal("1.005")), Decimal("1.01"))
        self.assertEqual(quantize_money(Decimal("1.004")), Decimal("1.00"))

    def test_exact_value_unchanged(self):
        self.assertEqual(quantize_money(Decimal("620.4")), Decimal("620.40"))


class FormatCapacityAmountTests(unittest.TestCase):
    """amount_safe_to_pay formatting -- trailing zeros trimmed (O-30)."""

    def test_trims_single_trailing_zero(self):
        self.assertEqual(format_capacity_amount(Decimal("603.30")), "603.3")

    def test_trims_another_trailing_zero(self):
        self.assertEqual(format_capacity_amount(Decimal("433.40")), "433.4")

    def test_whole_number_has_no_decimal_point(self):
        self.assertEqual(format_capacity_amount(Decimal("462.00")), "462")
        self.assertEqual(format_capacity_amount(Decimal("25256")), "25256")

    def test_two_natural_decimals_untouched(self):
        self.assertEqual(format_capacity_amount(Decimal("166.61")), "166.61")

    def test_large_whole_number_no_scientific_notation(self):
        # Decimal.normalize() alone would turn this into "4.6018E+7" -- the
        # bug this test exists to catch.
        self.assertEqual(format_capacity_amount(Decimal("46018000")), "46018000")


class FormatScheduleAmountTests(unittest.TestCase):
    """payment_plan / reduce_to formatting -- fixed 2dp when fractional,
    integer when whole (O-23, O-29)."""

    def test_keeps_trailing_zero(self):
        self.assertEqual(format_schedule_amount(Decimal("620.40")), "620.40")
        self.assertEqual(format_schedule_amount(Decimal("996.60")), "996.60")
        self.assertEqual(format_schedule_amount(Decimal("23.50")), "23.50")

    def test_whole_number_has_no_decimal_point(self):
        self.assertEqual(format_schedule_amount(Decimal("122500")), "122500")
        self.assertEqual(format_schedule_amount(Decimal("665950")), "665950")

    def test_large_whole_number_no_scientific_notation(self):
        self.assertEqual(format_schedule_amount(Decimal("46018000")), "46018000")

    def test_natural_two_decimals_unchanged(self):
        self.assertEqual(format_schedule_amount(Decimal("1852.11")), "1852.11")


if __name__ == "__main__":
    unittest.main()
