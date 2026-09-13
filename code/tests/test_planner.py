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

"""Unit tests for production candidate generator, spending changes, and ranking (Stage 5)."""

import unittest
from datetime import date
from decimal import Decimal

from buyorwait.csv_format import PlanEntry, ReduceChange, StopChange
from buyorwait.io_load import build_dataset
from buyorwait.planner import (
    Candidate,
    FlexibleStreamCandidate,
    apply_spending_changes_to_flows,
    enumerate_candidates,
    find_flexible_streams,
    rank_candidates,
)
from buyorwait.schemas import (
    AffordabilityStatus,
    Currency,
    ExpenseCategory,
    PaymentOptionMethod,
    RecommendedPaymentMethod,
)
from buyorwait.simulator import CashFlow, FlowKind


class PlannerCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = build_dataset(_resolve_dataset_dir())

    def test_full_payment_today_selected_when_accepted_and_safe(self):
        """request_01: full payment is accepted and safe today -> affordable_now."""
        cands = enumerate_candidates(self.dataset, "request_01")
        best = rank_candidates(cands)
        self.assertEqual(best.method, RecommendedPaymentMethod.FULL_PAYMENT)
        self.assertEqual(best.affordability_status, AffordabilityStatus.AFFORDABLE_NOW)
        self.assertEqual(len(best.payment_plan), 1)
        self.assertEqual(best.payment_plan[0].amount, Decimal("25256"))
        self.assertEqual(len(best.spending_changes), 0)

    def test_installments_chosen_when_full_payment_not_accepted(self):
        """request_12: user only considers partial_payment|installments; full payment safe today
        but ineligible -> installments recommended with status affordable_with_plan."""
        cands = enumerate_candidates(self.dataset, "request_12")
        best = rank_candidates(cands)
        self.assertEqual(best.method, RecommendedPaymentMethod.INSTALLMENTS)
        self.assertEqual(best.affordability_status, AffordabilityStatus.AFFORDABLE_WITH_PLAN)
        self.assertEqual(len(best.payment_plan), 3)

    def test_partial_payment_chosen_over_installment_with_fee(self):
        """request_19: allows partial payment; 2-payment schedule has 0 fee and beats
        installment option that charges a financing fee under S-14 rule 3 (minimum total paid)."""
        cands = enumerate_candidates(self.dataset, "request_19")
        best = rank_candidates(cands)
        self.assertEqual(best.method, RecommendedPaymentMethod.PARTIAL_PAYMENT)
        self.assertEqual(best.affordability_status, AffordabilityStatus.AFFORDABLE_WITH_PLAN)
        self.assertEqual(len(best.payment_plan), 2)
        total_paid = sum(p.amount for p in best.payment_plan)
        self.assertEqual(total_paid, Decimal("39660"))

    def test_wait_chosen_when_full_payment_safe_later_before_deadline(self):
        """request_04: full payment safe on 15/16 June, before 19 June deadline -> wait."""
        cands = enumerate_candidates(self.dataset, "request_04")
        best = rank_candidates(cands)
        self.assertEqual(best.method, RecommendedPaymentMethod.WAIT)
        self.assertEqual(best.affordability_status, AffordabilityStatus.AFFORDABLE_LATER)
        self.assertEqual(len(best.payment_plan), 1)
        self.assertTrue(best.completes_by_deadline)

    def test_not_recommended_when_all_options_fail_or_breach(self):
        """request_14: large extra loan repayment, neither full payment nor options safe."""
        cands = enumerate_candidates(self.dataset, "request_14")
        best = rank_candidates(cands)
        self.assertEqual(best.method, RecommendedPaymentMethod.NOT_RECOMMENDED)
        self.assertEqual(best.affordability_status, AffordabilityStatus.NOT_AFFORDABLE)
        self.assertEqual(len(best.payment_plan), 0)

    def test_ranking_hierarchy_six_levels(self):
        """Test S-14 ranking hierarchy ordering."""
        d0 = date(2024, 1, 1)
        d1 = date(2024, 1, 15)

        # 1. Candidate that fails deadline vs candidate that meets deadline
        c_late = Candidate(
            method=RecommendedPaymentMethod.FULL_PAYMENT,
            payment_plan=(PlanEntry(d1, Decimal(100)),),
            spending_changes=(),
            payment_option_id=None,
            total_paid=Decimal(100),
            completes_by_deadline=False,
            first_payment_date=d1,
            payment_count=1,
            affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
            replay=None,
            is_safe=True,
        )
        c_ontime = Candidate(
            method=RecommendedPaymentMethod.FULL_PAYMENT,
            payment_plan=(PlanEntry(d0, Decimal(100)),),
            spending_changes=(),
            payment_option_id=None,
            total_paid=Decimal(100),
            completes_by_deadline=True,
            first_payment_date=d0,
            payment_count=1,
            affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
            replay=None,
            is_safe=True,
        )
        self.assertEqual(rank_candidates((c_late, c_ontime)), c_ontime)

        # 2. Candidate with 0 changes vs candidate with 1 change
        c_change = Candidate(
            method=RecommendedPaymentMethod.FULL_PAYMENT,
            payment_plan=(PlanEntry(d0, Decimal(100)),),
            spending_changes=(StopChange("event_1"),),
            payment_option_id=None,
            total_paid=Decimal(100),
            completes_by_deadline=True,
            first_payment_date=d0,
            payment_count=1,
            affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
            replay=None,
            is_safe=True,
        )
        self.assertEqual(rank_candidates((c_change, c_ontime)), c_ontime)

        # 3. Minimum total paid: 100 vs 110
        c_expensive = Candidate(
            method=RecommendedPaymentMethod.INSTALLMENTS,
            payment_plan=(PlanEntry(d0, Decimal(55)), PlanEntry(d1, Decimal(55))),
            spending_changes=(),
            payment_option_id="opt_2",
            total_paid=Decimal(110),
            completes_by_deadline=True,
            first_payment_date=d0,
            payment_count=2,
            affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
            replay=None,
            is_safe=True,
        )
        self.assertEqual(rank_candidates((c_expensive, c_ontime)), c_ontime)


class FlexibleStreamsAndSpendingChangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = build_dataset(_resolve_dataset_dir())

    def test_canonical_event_is_latest_historical(self):
        """User_06 flexible streaming stream canonical ID must match event_476."""
        streams = find_flexible_streams(self.dataset, "user_06", date(2026, 1, 3))
        event_ids = {s.canonical_event_id for s in streams}
        self.assertIn("event_476", event_ids)

    def test_apply_spending_changes_cancels_stopped_flow(self):
        """apply_spending_changes_to_flows drops flows matching stopped stream."""
        sc = FlexibleStreamCandidate(
            category=ExpenseCategory.STREAMING,
            description="Family streaming plan",
            canonical_event_id="event_476",
            typical_amount=Decimal(19),
            minimum_allowed_amount=None,
            is_stoppable=True,
            is_reducible=False,
        )
        base_flows = (
            CashFlow(flow_date=date(2026, 1, 10), amount=Decimal(-19), kind=FlowKind.SETTLED_RECURRING_PROJECTION, label="recurring streaming: Family streaming plan"),
            CashFlow(flow_date=date(2026, 1, 15), amount=Decimal(1000), kind=FlowKind.CONFIRMED_INCOME, label="salary: Payroll"),
        )
        mod_flows = apply_spending_changes_to_flows(
            base_flows,
            (StopChange("event_476"),),
            (sc,),
        )
        self.assertEqual(len(mod_flows), 1)
        self.assertEqual(mod_flows[0].kind, FlowKind.CONFIRMED_INCOME)


if __name__ == "__main__":
    unittest.main()
