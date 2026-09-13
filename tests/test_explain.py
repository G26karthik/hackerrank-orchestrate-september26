import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

import os
from pathlib import Path

def _resolve_dataset_dir() -> Path:
    if 'DATASET_DIR' in os.environ and Path(os.environ['DATASET_DIR']).exists():
        return Path(os.environ['DATASET_DIR'])
    for cand in [Path('dataset'), Path(__file__).resolve().parents[1] / 'dataset', Path(__file__).resolve().parents[2] / 'dataset']:
        if cand.exists() and (cand / 'requests.csv').exists():
            return cand
    return Path('dataset')

"""Unit tests for explanation generator (Stage 5)."""

import unittest
from datetime import date
from decimal import Decimal

from buyorwait.csv_format import PlanEntry, ReduceChange, StopChange
from buyorwait.explain import explain, format_explanation_amount, format_explanation_date
from buyorwait.io_load import build_dataset
from buyorwait.planner import Candidate
from buyorwait.schemas import AffordabilityStatus, RecommendedPaymentMethod


class ExplainFormatTests(unittest.TestCase):
    def test_format_explanation_amount(self):
        self.assertEqual(format_explanation_amount(Decimal("25256")), "25,256")
        self.assertEqual(format_explanation_amount(Decimal("18000")), "18,000")
        self.assertEqual(format_explanation_amount(Decimal("620.40")), "620.40")
        self.assertEqual(format_explanation_amount(Decimal("996.6")), "996.60")
        self.assertEqual(format_explanation_amount(Decimal("15952906.67")), "15,952,906.67")

    def test_format_explanation_date(self):
        self.assertEqual(format_explanation_date(date(2025, 4, 15)), "15 April 2025")
        self.assertEqual(format_explanation_date(date(2024, 3, 3)), "3 March 2024")


class ExplainGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = build_dataset(_resolve_dataset_dir())

    def test_explain_full_payment_today(self):
        """request_01: full payment today explanation."""
        c = Candidate(
            method=RecommendedPaymentMethod.FULL_PAYMENT,
            payment_plan=(PlanEntry(date(2024, 3, 3), Decimal("25256")),),
            spending_changes=(),
            payment_option_id=None,
            total_paid=Decimal("25256"),
            completes_by_deadline=True,
            first_payment_date=date(2024, 3, 3),
            payment_count=1,
            affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
            replay=None,
            is_safe=True,
        )
        exp = explain(self.dataset, "request_01", c)
        self.assertEqual(
            exp,
            "Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days.",
        )

    def test_explain_installments(self):
        """request_12: 3 installments explanation."""
        c = Candidate(
            method=RecommendedPaymentMethod.INSTALLMENTS,
            payment_plan=(
                PlanEntry(date(2026, 4, 19), Decimal("22590.19")),
                PlanEntry(date(2026, 5, 20), Decimal("22590.19")),
                PlanEntry(date(2026, 6, 20), Decimal("22590.19")),
            ),
            spending_changes=(),
            payment_option_id="opt_x",
            total_paid=Decimal("67770.57"),
            completes_by_deadline=True,
            first_payment_date=date(2026, 4, 19),
            payment_count=3,
            affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
            replay=None,
            is_safe=True,
        )
        exp = explain(self.dataset, "request_12", c)
        self.assertEqual(
            exp,
            "Use 3 installments of ZAR 22,590.19, starting 19 April 2026. This leaves at least ZAR 43,200 available.",
        )

    def test_explain_spending_changes(self):
        """request_06: stop family streaming plan."""
        c = Candidate(
            method=RecommendedPaymentMethod.FULL_PAYMENT,
            payment_plan=(PlanEntry(date(2026, 1, 3), Decimal("620.40")),),
            spending_changes=(StopChange("event_476"),),
            payment_option_id=None,
            total_paid=Decimal("620.40"),
            completes_by_deadline=True,
            first_payment_date=date(2026, 1, 3),
            payment_count=1,
            affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
            replay=None,
            is_safe=True,
        )
        exp = explain(self.dataset, "request_06", c)
        self.assertIn("Stop the family streaming plan", exp)
        self.assertIn("EUR 620.40", exp)
        self.assertIn("EUR 800", exp)

    def test_validate_explanation(self):
        from buyorwait.explain import validate_explanation
        c = Candidate(
            method=RecommendedPaymentMethod.FULL_PAYMENT,
            payment_plan=(PlanEntry(date(2024, 3, 3), Decimal("25256")),),
            spending_changes=(),
            payment_option_id=None,
            total_paid=Decimal("25256"),
            completes_by_deadline=True,
            first_payment_date=date(2024, 3, 3),
            payment_count=1,
            affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
            replay=None,
            is_safe=True,
        )
        valid_exp = "Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days."
        ok, reason = validate_explanation(self.dataset, "request_01", c, valid_exp)
        self.assertTrue(ok)
        self.assertIsNone(reason)

        # Missing currency
        bad_exp = "Pay 25,256 today. This leaves 18,000 available."
        ok, reason = validate_explanation(self.dataset, "request_01", c, bad_exp)
        self.assertFalse(ok)
        self.assertIn("currency", reason)


if __name__ == "__main__":
    unittest.main()
