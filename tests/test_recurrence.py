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

"""Tests for code/buyorwait/recurrence.py.
Exercises recurring stream detection, calendar vs interval, reconciliation with
explicit future events, variable spend estimators, and evidence amendments.
"""

import unittest
from datetime import date, timedelta
from decimal import Decimal

from buyorwait.evidence import EvidenceFact, FactKind, TemporalScope
from buyorwait.io_load import build_dataset
from buyorwait.recurrence import (
    RecurrenceConfidence,
    RecurrenceScheduleType,
    RecurringStream,
    ScheduledOccurrence,
    VariableSpendEstimate,
    detect_recurring_streams,
    estimate_variable_spend,
    normalize_stream_description,
    project_occurrences,
)
from buyorwait.schemas import Currency, Direction, ExpenseCategory


class RecurrenceDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = build_dataset(_resolve_dataset_dir())

    def test_normalize_stream_description(self):
        self.assertEqual(
            normalize_stream_description("Family streaming plan INV-2024-001"),
            "Family streaming plan",
        )
        self.assertEqual(
            normalize_stream_description("Cloud Storage Monthly (Acct #9912)"),
            "Cloud Storage Monthly",
        )
        self.assertEqual(
            normalize_stream_description("Monthly Salary - August 2024"),
            "Monthly Salary",
        )

    def test_detect_streams_user_02(self):
        streams = detect_recurring_streams(self.dataset, "user_02")
        self.assertIsInstance(streams, tuple)
        self.assertGreater(len(streams), 0)

        # user_02 should have supported salary and utilities streams
        supported = [s for s in streams if s.confidence == RecurrenceConfidence.SUPPORTED]
        self.assertGreater(len(supported), 0)
        categories = {s.category for s in supported}
        self.assertIn(ExpenseCategory.SALARY, categories)
        self.assertIn(ExpenseCategory.UTILITIES, categories)

    def test_project_occurrences_reconciliation(self):
        # Create a synthetic stream on the 15th of each month
        stream = RecurringStream(
            user_id="user_test",
            category=ExpenseCategory.SALARY,
            description="Monthly Salary",
            typical_amount=Decimal("5000.00"),
            currency=Currency.USD,
            schedule_type=RecurrenceScheduleType.CALENDAR_MONTH,
            day_of_month=15,
            interval_days=None,
            direction=Direction.CREDIT,
            confidence=RecurrenceConfidence.SUPPORTED,
            supporting_event_ids=("evt_1", "evt_2"),
        )
        start = date(2024, 1, 1)
        end = date(2024, 3, 31)

        # Inferred occurrences without explicit event
        occs = project_occurrences((stream,), start=start, end=end)
        self.assertEqual(len(occs), 3)  # Jan 15, Feb 15, Mar 15
        self.assertFalse(occs[0].is_explicit_event)

        # Now suppose there is an explicit scheduled event for Jan 15
        from buyorwait.schemas import Event, EventStatus, EventType, Flexibility, freeze_row
        exp_evt = Event(
            event_id="exp_salary_jan",
            user_id="user_test",
            event_type=EventType.INCOME,
            description="Explicit Salary",
            category=ExpenseCategory.SALARY,
            direction=Direction.CREDIT,
            amount=Decimal("5200.00"),
            currency=Currency.USD,
            event_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 15),
            status=EventStatus.SCHEDULED,
            linked_event_id=None,
            flexibility=Flexibility.FIXED,
            minimum_allowed_amount=None,
            raw=freeze_row({}),
        )

        occs_rec = project_occurrences(
            (stream,),
            start=start,
            end=end,
            explicit_future_events=(exp_evt,),
            home_currency=Currency.USD,
        )
        # Should still be exactly 3 occurrences (no double counting!)
        self.assertEqual(len(occs_rec), 3)
        # First occurrence should be the reconciled explicit event
        self.assertTrue(occs_rec[0].is_explicit_event)
        self.assertEqual(occs_rec[0].reconciled_event_id, "exp_salary_jan")
        self.assertEqual(occs_rec[0].amount, Decimal("5200.00"))
        # Later occurrences remain inferred
        self.assertFalse(occs_rec[1].is_explicit_event)
        self.assertEqual(occs_rec[1].amount, Decimal("5000.00"))

    def test_variable_spend_estimators(self):
        req = next(r for r in self.dataset.sample_requests if r.user_id == "user_01")
        methods = [
            "trailing_3_month_mean_floored_at_latest_month",
            "trailing_3_month_median",
            "trailing_3_month_mean",
            "latest_complete_month",
        ]
        for m in methods:
            ests = estimate_variable_spend(self.dataset, "user_01", req.request_date, method=m)
            self.assertEqual(len(ests), 3)  # dining, groceries, transport
            for est in ests:
                self.assertGreaterEqual(est.monthly_estimate, Decimal(0))
                self.assertEqual(est.method, m)

    def test_evidence_fact_amendments(self):
        # Test income ended fact halts salary stream
        fact_ended = EvidenceFact(
            source_type="message",
            source_id="msg_ended",
            user_id="user_01",
            related_event_id=None,
            related_request_id=None,
            fact_kind=FactKind.INCOME_ENDED,
            amount=None,
            currency=None,
            temporal_scope=TemporalScope(None, None),
            ambiguous=False,
            ambiguity_note="",
            raw_excerpt="contract ended",
            observed_time="2024-01-01T00:00:00Z",
            effective_time=None,
        )
        streams = detect_recurring_streams(self.dataset, "user_01", evidence_facts=(fact_ended,))
        salary_stream = next((s for s in streams if s.category == ExpenseCategory.SALARY), None)
        if salary_stream:
            self.assertEqual(salary_stream.confidence, RecurrenceConfidence.INSUFFICIENT_HISTORY)

        # Test rent percentage increase
        fact_rent = EvidenceFact(
            source_type="message",
            source_id="msg_rent",
            user_id="user_01",
            related_event_id=None,
            related_request_id=None,
            fact_kind=FactKind.RENT_PERCENTAGE_INCREASE,
            amount=Decimal("12"),
            currency=None,
            temporal_scope=TemporalScope(None, None),
            ambiguous=False,
            ambiguity_note="",
            raw_excerpt="rent increase 12%",
            observed_time="2024-01-01T00:00:00Z",
            effective_time=None,
        )
        base_streams = detect_recurring_streams(self.dataset, "user_01")
        base_rent = next(s for s in base_streams if s.category == ExpenseCategory.RENT).typical_amount

        inc_streams = detect_recurring_streams(self.dataset, "user_01", evidence_facts=(fact_rent,))
        inc_rent = next(s for s in inc_streams if s.category == ExpenseCategory.RENT).typical_amount
        self.assertEqual(inc_rent, (base_rent * Decimal("1.12")).quantize(Decimal("0.01")))


if __name__ == "__main__":
    unittest.main()
