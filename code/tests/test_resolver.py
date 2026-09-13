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

"""Tests for code/buyorwait/resolver.py.
Exercises lifecycle groups, conflict precedence, pending debit reservation,
image amount resolution, and historical exclusion.
"""

import unittest
from datetime import date
from decimal import Decimal

from buyorwait.evidence import EvidenceFact, FactKind, TemporalScope
from buyorwait.resolver import (
    FlowAdmission,
    LifecycleGroup,
    ResolutionPrecedence,
    load_image_audit_amounts,
    resolve,
    resolve_user_events,
)
from buyorwait.schemas import (
    Currency,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExpenseCategory,
    Flexibility,
    Profile,
    Request,
    freeze_row,
)
from buyorwait.io_load import build_dataset


def _make_event(**overrides) -> Event:
    defaults = dict(
        event_id="event_test",
        user_id="user_test",
        event_type=EventType.EXPENSE,
        description="test expense",
        category=ExpenseCategory.SHOPPING,
        direction=Direction.DEBIT,
        amount=Decimal("100.00"),
        currency=Currency.USD,
        event_date=date(2024, 1, 1),
        settlement_date=date(2024, 1, 1),
        status=EventStatus.SETTLED,
        linked_event_id=None,
        flexibility=Flexibility.FIXED,
        minimum_allowed_amount=None,
        raw=freeze_row({}),
    )
    defaults.update(overrides)
    return Event(**defaults)


class ResolverLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = build_dataset(_resolve_dataset_dir())

    def test_real_dataset_user_02_resolution(self):
        resolved_fields, flows = resolve_user_events(self.dataset, "user_02")
        self.assertIsInstance(resolved_fields, tuple)
        self.assertIsInstance(flows, tuple)
        self.assertGreater(len(flows), 0)

        # Historical settled events should be marked excluded from forecast
        req = next(r for r in self.dataset.sample_requests if r.user_id == "user_02")
        for f in flows:
            if f.status == EventStatus.SETTLED and f.flow_date < req.request_date:
                self.assertTrue(f.is_represented_in_opening_balance)
                self.assertEqual(f.admission, FlowAdmission.EXCLUDED_HISTORICAL_SETTLED)

    def test_pending_debit_reservation(self):
        # Pending debit should be admitted as a reserved pending debit
        evt = _make_event(
            event_id="evt_pending",
            event_date=date(2024, 2, 5),
            settlement_date=date(2024, 2, 5),
            status=EventStatus.PENDING,
            direction=Direction.DEBIT,
        )
        resolved_fields, flows = resolve_user_events(
            self.dataset, "user_01", as_of_date=date(2024, 2, 1)
        )
        # Find any pending debits in user_01
        for f in flows:
            if f.status == EventStatus.PENDING and f.direction == Direction.DEBIT:
                self.assertTrue(f.is_reserved_pending_debit)
                self.assertEqual(f.admission, FlowAdmission.ADMITTED)

    def test_pending_credit_excluded(self):
        # Pending credit should be excluded per S-16
        for f in resolve_user_events(self.dataset, "user_19")[1]:
            if f.status == EventStatus.PENDING and f.direction == Direction.CREDIT:
                self.assertEqual(f.admission, FlowAdmission.EXCLUDED_PENDING_CREDIT)

    def test_cancelled_and_failed_dropped(self):
        for f in resolve_user_events(self.dataset, "user_01")[1]:
            if f.status == EventStatus.CANCELLED:
                self.assertEqual(f.admission, FlowAdmission.EXCLUDED_CANCELLED)
            elif f.status == EventStatus.FAILED:
                self.assertEqual(f.admission, FlowAdmission.EXCLUDED_FAILED)

    def test_image_amount_resolution(self):
        # event_253 has blank amount, resolved from image_01 (4365000)
        resolved_fields, flows = resolve_user_events(self.dataset, "user_03")
        f_253 = next(f for f in flows if f.flow_id == "event_253")
        self.assertEqual(f_253.original_amount, Decimal("4365000"))
        self.assertIn("image_01", f_253.source_ids)

    def test_as_of_date_policy(self):
        # Fact observed after as-of date should be discarded as future leakage
        future_fact = EvidenceFact(
            source_type="message",
            source_id="msg_future",
            user_id="user_01",
            related_event_id=None,
            related_request_id=None,
            fact_kind=FactKind.INCOME_AMOUNT_CHANGE,
            amount=Decimal("99999"),
            currency=Currency.INR,
            temporal_scope=TemporalScope(effective_from=date(2024, 5, 1), effective_until=None),
            ambiguous=False,
            ambiguity_note="",
            raw_excerpt="future observation",
            observed_time="2024-03-01T00:00:00Z",
            effective_time="2024-05-01",
        )
        resolved_fields, flows = resolve_user_events(
            self.dataset,
            "user_01",
            evidence_facts=(future_fact,),
            as_of_date=date(2024, 2, 1),  # before observed_time
        )
        discarded = [rf for rf in resolved_fields if rf.field_name == "observation_discarded"]
        self.assertEqual(len(discarded), 1)
        self.assertEqual(discarded[0].precedence_used, ResolutionPrecedence.SAFER_INTERPRETATION)

    def test_self_transfer_exclusion(self):
        fact = EvidenceFact(
            source_type="message",
            source_id="msg_transfer",
            user_id="user_01",
            related_event_id=None,
            related_request_id=None,
            fact_kind=FactKind.SELF_TRANSFER,
            amount=None,
            currency=None,
            temporal_scope=TemporalScope(None, None),
            ambiguous=False,
            ambiguity_note="",
            raw_excerpt="transfer between accounts",
            observed_time="2024-01-01T00:00:00Z",
            effective_time=None,
        )
        resolved_fields, flows = resolve_user_events(
            self.dataset, "user_01", evidence_facts=(fact,), as_of_date=date(2024, 2, 1)
        )
        st_fields = [rf for rf in resolved_fields if rf.field_name == "self_transfer"]
        self.assertEqual(len(st_fields), 1)
        self.assertEqual(st_fields[0].precedence_used, ResolutionPrecedence.EXPLICIT_AMENDMENT)


if __name__ == "__main__":
    unittest.main()
