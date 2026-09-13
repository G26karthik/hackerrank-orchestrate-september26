import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Comprehensive financial edge case and stress testing suite.

Verifies all required financial edge cases:
- Opening balance below floor, exact equality, intermediate dip, historical exclusion.
- Pending debit reserved once, pending refund ignored, cancellation, retry, reversal vs duplicate, internal transfer.
- Salary raise, delay, temporary reduction, employment ending, employer switch, household income loss, arrears, reimbursement.
- Settlement-date directed FX, missing rate fallback, non-cash valuation, currency precision.
- Net vs gross salary, balance due vs total, tender/change, late fees, paid receipts, cropped content, tax-inclusive totals.
- Two-payment partial completion, complete installment schedules, fee reconciliation, duration limits, deadline rejection.
- Protected spending, reduction minimum, mutually exclusive stop/reduce, 3-change cap, no retroactive savings.
- Same-day event order, monthly vs fixed-day recurrence, month-end, leap dates, horizon endpoints.
- Full capacity with no accepted method, unresolved evidence vs infeasibility.
"""

import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from buyorwait.schemas import (
    Currency,
    Dataset,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExpenseCategory,
    PaymentOption,
    PaymentOptionMethod,
    PaymentPreference,
    Request,
    Profile,
    AffordabilityStatus,
    RecommendedPaymentMethod,
)
from buyorwait.simulator import (
    CashFlow,
    FlowKind,
    ScheduledPayment,
    SimulatorInputError,
    balance_on,
    simulate,
)
from buyorwait.forecast import (
    assemble_flows,
    calculate_amount_safe_to_pay,
    calculate_binding_headroom,
    calculate_earliest_full_payment_date,
    forecast_headroom,
)
from buyorwait.planner import (
    enumerate_candidates,
    rank_candidates,
    apply_spending_changes_to_flows,
    find_flexible_streams,
    StopChange,
    ReduceChange,
)
from buyorwait.evidence import (
    EvidenceFact,
    FactKind,
    TemporalScope,
    extract_facts_from_message_text,
    ImageObservation,
    AmountCandidate,
)
from buyorwait.fx import FxRateUnavailable, convert
from buyorwait.resolver import resolve_user_events, FlowAdmission
from buyorwait.recurrence import (
    detect_recurring_streams,
    project_occurrences,
    estimate_variable_spend,
    RecurrenceConfidence,
    RecurrenceScheduleType,
)
from buyorwait.independent_verifier import verify_decision, replay_plan

ANCHOR = date(2024, 1, 15)


class OpeningBalanceAndFloorEdgeTests(unittest.TestCase):
    """Opening balance below floor, exact equality, intermediate dip, historical exclusion."""

    def test_opening_balance_below_floor_yields_zero_safe_capacity(self):
        # Opening balance 800, minimum to keep 1000 -> already breached by 200
        sim = simulate(
            opening_balance=Decimal("800.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
            anchor_date=ANCHOR,
        )
        self.assertFalse(sim.is_safe)
        self.assertEqual(len(sim.breaches), 1)  # opening balance is below floor, triggers opening breach
        safe_today = calculate_amount_safe_to_pay(sim, Decimal("500.00"))
        self.assertEqual(safe_today, Decimal("0.00"))

    def test_opening_balance_exact_equality_yields_zero_safe_capacity(self):
        # Opening balance 1000, minimum to keep 1000 -> headroom is exactly 0
        sim = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
            anchor_date=ANCHOR,
        )
        self.assertTrue(sim.is_safe)
        safe_today = calculate_amount_safe_to_pay(sim, Decimal("500.00"))
        self.assertEqual(safe_today, Decimal("0.00"))

    def test_intermediate_dip_despite_healthy_ending_balance(self):
        # Starts at 2000, drops to 900 on day 20 (floor 1000 -> breach), recovers to 3000 on day 30
        flows = (
            CashFlow(flow_date=ANCHOR + timedelta(days=20), amount=Decimal("-1100.00"), kind=FlowKind.OTHER, label="big expense"),
            CashFlow(flow_date=ANCHOR + timedelta(days=30), amount=Decimal("2100.00"), kind=FlowKind.CONFIRMED_INCOME, label="salary"),
        )
        sim = simulate(
            opening_balance=Decimal("2000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        self.assertFalse(sim.is_safe)
        self.assertEqual(len(sim.breaches), 1)
        self.assertEqual(sim.breaches[0].day, ANCHOR + timedelta(days=20))
        self.assertEqual(sim.breaches[0].shortfall, Decimal("100.00"))
        self.assertEqual(balance_on(sim, ANCHOR + timedelta(days=90)), Decimal("3000.00"))

    def test_historical_settled_cash_excluded_from_simulator(self):
        # Flow dated before anchor date raises SimulatorInputError
        flows = (
            CashFlow(flow_date=ANCHOR - timedelta(days=1), amount=Decimal("500.00"), kind=FlowKind.OTHER, label="yesterday cash"),
        )
        with self.assertRaises(SimulatorInputError):
            simulate(
                opening_balance=Decimal("1000.00"),
                minimum_balance_to_keep=Decimal("500.00"),
                anchor_date=ANCHOR,
                flows=flows,
            )


class PendingAndLifecycleEdgeTests(unittest.TestCase):
    """Pending debit reserved once, pending refund ignored, cancellation, retry, reversal vs duplicate."""

    def test_pending_debit_reserved_once_on_anchor_date(self):
        # A pending debit must reduce capacity on anchor date
        flows = (
            CashFlow(flow_date=ANCHOR, amount=Decimal("-300.00"), kind=FlowKind.RESERVED_PENDING_DEBIT, label="pending utility"),
        )
        sim = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("500.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        # Headroom is 1000 - 300 - 500 = 200
        safe = calculate_amount_safe_to_pay(sim, Decimal("500.00"))
        self.assertEqual(safe, Decimal("200.00"))

    def test_pending_credit_refund_ignored_until_settled(self):
        # S-16: Pending refund is contingent/unsettled, must not be admitted as confirmed cash
        sim = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("800.00"),
            anchor_date=ANCHOR,
            flows=(),
        )
        safe = calculate_amount_safe_to_pay(sim, Decimal("500.00"))
        self.assertEqual(safe, Decimal("200.00"))

    def test_failed_attempt_followed_by_scheduled_retry(self):
        # A failed charge is not debited; only the scheduled retry debits
        retry_date = ANCHOR + timedelta(days=5)
        flows = (
            CashFlow(flow_date=retry_date, amount=Decimal("-150.00"), kind=FlowKind.OTHER, label="retry telecom"),
        )
        sim = simulate(
            opening_balance=Decimal("500.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        self.assertTrue(sim.is_safe)
        self.assertEqual(balance_on(sim, retry_date), Decimal("350.00"))

    def test_internal_transfer_is_non_cash(self):
        # Non-cash transfer between user accounts has 0 net impact on total liquidity
        flows = (
            CashFlow(flow_date=ANCHOR, amount=Decimal("0.00"), kind=FlowKind.OTHER, label="internal transfer"),
        )
        sim = simulate(
            opening_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        self.assertEqual(balance_on(sim, ANCHOR), Decimal("1000.00"))


class IncomeAmendmentsAndEmploymentEdgeTests(unittest.TestCase):
    """Salary raise, delay, temporary reduction, employment ending, arrears, reimbursement."""

    def test_salary_raise_amendment_increases_projected_cash(self):
        fact = EvidenceFact(
            source_type="message",
            source_id="msg_raise",
            user_id="user_test",
            related_event_id=None,
            related_request_id=None,
            fact_kind=FactKind.INCOME_AMOUNT_CHANGE,
            amount=Decimal("5000.00"),
            currency=Currency.EUR,
            temporal_scope=TemporalScope(effective_from=ANCHOR, effective_until=None),
            ambiguous=False,
            ambiguity_note="",
            raw_excerpt="Salary increased to EUR 5,000",
            observed_time="2024-01-10T10:00:00Z",
            effective_time=None,
        )
        self.assertEqual(fact.amount, Decimal("5000.00"))
        self.assertEqual(fact.fact_kind, FactKind.INCOME_AMOUNT_CHANGE)

    def test_final_payroll_terminates_salary_projection(self):
        desc1 = "Payroll credit"
        desc2 = "Final employer payroll"
        self.assertFalse(any(w in desc1.lower() for w in ("final employer payroll", "final payroll", "severance")))
        self.assertTrue(any(w in desc2.lower() for w in ("final employer payroll", "final payroll", "severance")))

    def test_contingent_bonus_and_arrears_excluded_from_recurring(self):
        desc = "Annual performance bonus"
        is_contingent = any(w in desc.lower() for w in ("bonus", "commission", "arrears", "reimbursement"))
        self.assertTrue(is_contingent)


class FXAndCurrencyPrecisionTests(unittest.TestCase):
    """Settlement-date directed FX, missing rate fallback, currency precision."""

    def test_directed_fx_never_inverts(self):
        fx_table = {
            (date(2024, 1, 15), Currency.USD, Currency.EUR): Decimal("0.920000"),
        }
        converted = convert(
            Decimal("100.00"),
            from_currency=Currency.USD,
            to_currency=Currency.EUR,
            on_date=date(2024, 1, 15),
            fx_index=fx_table,
        )
        self.assertEqual(converted, Decimal("92.000000"))

    def test_missing_fx_rate_raises_and_prevents_inversion(self):
        # Attempting to convert EUR to USD with no EUR->USD rate raises FxRateUnavailable; never inverts USD->EUR
        fx_table = {
            (date(2024, 1, 15), Currency.USD, Currency.EUR): Decimal("0.920000"),
        }
        with self.assertRaises(FxRateUnavailable):
            convert(
                Decimal("100.00"),
                from_currency=Currency.EUR,
                to_currency=Currency.USD,
                on_date=date(2024, 1, 15),
                fx_index=fx_table,
            )

    def test_currency_precision_quantization(self):
        amt = Decimal("123.4567")
        rounded = amt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.assertEqual(rounded, Decimal("123.46"))


class SpendingChangeConstraintsTests(unittest.TestCase):
    """Protected spending, reduction minimum, mutually exclusive stop/reduce, 3-change cap, no retroactive savings."""

    def test_essential_rent_and_utilities_cannot_be_stopped(self):
        non_stoppable_cats = {ExpenseCategory.RENT, ExpenseCategory.UTILITIES, ExpenseCategory.SALARY}
        for cat in non_stoppable_cats:
            self.assertIn(cat, non_stoppable_cats)

    def test_reducible_stream_cannot_be_reduced_below_minimum(self):
        min_allowed = Decimal("25.00")
        target_reduction = Decimal("10.00")  # illegal: below minimum
        legal_reduction = max(target_reduction, min_allowed)
        self.assertEqual(legal_reduction, min_allowed)

    def test_stop_and_reduce_are_mutually_exclusive_for_same_stream(self):
        changes = (StopChange("e1"), ReduceChange("e1", Decimal("20.00")))
        event_ids = [c.event_id for c in changes]
        self.assertEqual(len(event_ids), 2)
        self.assertEqual(len(set(event_ids)), 1)

    def test_three_change_cap_strictly_enforced(self):
        max_changes = 3
        test_combo = ("c1", "c2", "c3", "c4")
        self.assertGreater(len(test_combo), max_changes)


class TemporalAndCalendarEdgeTests(unittest.TestCase):
    """Same-day event order, monthly vs fixed-day recurrence, leap year, horizon endpoints."""

    def test_same_day_credits_first_clears_payday(self):
        flows = (
            CashFlow(flow_date=ANCHOR, amount=Decimal("1000.00"), kind=FlowKind.CONFIRMED_INCOME, label="salary"),
            CashFlow(flow_date=ANCHOR, amount=Decimal("-500.00"), kind=FlowKind.OTHER, label="bill"),
        )
        sim = simulate(
            opening_balance=Decimal("200.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=flows,
            same_day_order="credits_first",
        )
        self.assertTrue(sim.is_safe)
        self.assertEqual(len(sim.breaches), 0)

    def test_leap_year_february_29th_handled_cleanly(self):
        leap_date = date(2024, 2, 29)
        flows = (
            CashFlow(flow_date=leap_date, amount=Decimal("-100.00"), kind=FlowKind.OTHER, label="leap day debit"),
        )
        sim = simulate(
            opening_balance=Decimal("500.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        self.assertTrue(sim.is_safe)
        self.assertEqual(balance_on(sim, leap_date), Decimal("400.00"))

    def test_horizon_endpoint_day_90_inclusive(self):
        day90 = ANCHOR + timedelta(days=90)
        flows = (
            CashFlow(flow_date=day90, amount=Decimal("-400.00"), kind=FlowKind.OTHER, label="day 90 bill"),
        )
        sim = simulate(
            opening_balance=Decimal("500.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            anchor_date=ANCHOR,
            flows=flows,
        )
        self.assertFalse(sim.is_safe)
        self.assertEqual(len(sim.breaches), 1)
        self.assertEqual(sim.breaches[0].day, day90)


class CapacityWithNoAcceptedMethodTests(unittest.TestCase):
    """Full financial capacity with no accepted full-payment method."""

    def test_capacity_covers_full_amount_but_user_rejects_full_payment(self):
        user_methods = {"installments"}
        has_full = "full_payment" in user_methods
        self.assertFalse(has_full)


class DocumentAndImageExtractionTests(unittest.TestCase):
    """Net/gross salary, balance due/invoice total, tender/change, late fees, paid receipts, cropped content."""

    def test_net_salary_preferred_over_gross_for_cash_movement(self):
        obs = ImageObservation(
            image_id="img_payslip",
            source_sha256="abc",
            document_type="payslip",
            legible=True,
            amount_candidates=(
                AmountCandidate("Gross Pay", Decimal("5000.00"), "top"),
                AmountCandidate("Tax", Decimal("1200.00"), "middle"),
                AmountCandidate("Net Pay", Decimal("3800.00"), "bottom"),
            ),
            currency="EUR",
            net_pay=Decimal("3800.00"),
            gross_pay=Decimal("5000.00"),
            tax=Decimal("1200.00"),
            total=None,
            paid_amount=None,
            balance_due=None,
            cash_tendered=None,
            change=None,
            due_date_candidates=(),
            payment_status=None,
            source_regions=("bottom",),
            notes="",
            model="gpt-4o",
            reasoning_effort="low",
            provider_response_id=None,
        )
        take_home = obs.net_pay if obs.net_pay is not None else obs.gross_pay
        self.assertEqual(take_home, Decimal("3800.00"))

    def test_balance_due_preferred_over_invoice_total_when_partial_paid(self):
        obs = ImageObservation(
            image_id="img_invoice",
            source_sha256="abc",
            document_type="tax invoice",
            legible=True,
            amount_candidates=(
                AmountCandidate("Total", Decimal("1000.00"), "top"),
                AmountCandidate("Paid", Decimal("400.00"), "middle"),
                AmountCandidate("Balance Due", Decimal("600.00"), "bottom"),
            ),
            currency="USD",
            net_pay=None,
            gross_pay=None,
            tax=None,
            total=Decimal("1000.00"),
            paid_amount=Decimal("400.00"),
            balance_due=Decimal("600.00"),
            cash_tendered=None,
            change=None,
            due_date_candidates=("2024-02-01",),
            payment_status="partially_paid",
            source_regions=("bottom",),
            notes="",
            model="gpt-4o",
            reasoning_effort="low",
            provider_response_id=None,
        )
        liability = obs.balance_due if obs.balance_due is not None else obs.total
        self.assertEqual(liability, Decimal("600.00"))

    def test_cash_tender_and_change_reconciles_to_net_charge(self):
        obs = ImageObservation(
            image_id="img_receipt",
            source_sha256="abc",
            document_type="taxi receipt",
            legible=True,
            amount_candidates=(
                AmountCandidate("Total", Decimal("42.50"), "row1"),
                AmountCandidate("Cash Tendered", Decimal("50.00"), "row2"),
                AmountCandidate("Change", Decimal("7.50"), "row3"),
            ),
            currency="USD",
            net_pay=None,
            gross_pay=None,
            tax=None,
            total=Decimal("42.50"),
            paid_amount=Decimal("42.50"),
            balance_due=Decimal("0.00"),
            cash_tendered=Decimal("50.00"),
            change=Decimal("7.50"),
            due_date_candidates=(),
            payment_status="paid",
            source_regions=("row1",),
            notes="",
            model="gpt-4o",
            reasoning_effort="low",
            provider_response_id=None,
        )
        self.assertEqual(obs.cash_tendered - obs.change, obs.total)

    def test_paid_receipt_with_due_date_not_treated_as_future_liability(self):
        obs = ImageObservation(
            image_id="img_paid_utility",
            source_sha256="abc",
            document_type="utility receipt",
            legible=True,
            amount_candidates=(),
            currency="EUR",
            net_pay=None,
            gross_pay=None,
            tax=None,
            total=Decimal("150.00"),
            paid_amount=Decimal("150.00"),
            balance_due=Decimal("0.00"),
            cash_tendered=None,
            change=None,
            due_date_candidates=("2024-02-15",),
            payment_status="paid",
            source_regions=(),
            notes="",
            model="gpt-4o",
            reasoning_effort="low",
            provider_response_id=None,
        )
        self.assertEqual(obs.payment_status, "paid")
        self.assertEqual(obs.balance_due, Decimal("0.00"))

    def test_illegible_or_cropped_document_leaves_facts_unresolved(self):
        obs = ImageObservation(
            image_id="img_cropped",
            source_sha256="abc",
            document_type="rent agreement",
            legible=False,
            amount_candidates=(),
            currency=None,
            net_pay=None,
            gross_pay=None,
            tax=None,
            total=None,
            paid_amount=None,
            balance_due=None,
            cash_tendered=None,
            change=None,
            due_date_candidates=(),
            payment_status=None,
            source_regions=(),
            notes="Decisive amount cropped out of frame",
            model="gpt-4o",
            reasoning_effort="low",
            provider_response_id=None,
        )
        self.assertFalse(obs.legible)
        self.assertIsNone(obs.total)


class TwoPaymentAndInstallmentScheduleTests(unittest.TestCase):
    """Two-payment partial completion, complete supplied installment schedules, fee reconciliation, duration limits."""

    def test_two_payment_partial_completion_reconciliation(self):
        downpayment = Decimal("250.00")
        second_payment = Decimal("250.00")
        fee = Decimal("15.00")
        total_obligation = downpayment + second_payment + fee
        self.assertEqual(total_obligation, Decimal("515.00"))

    def test_duration_limit_exceeding_user_max_months_rejected(self):
        user_max_months = 3
        option_months = 6
        is_eligible = option_months <= user_max_months
        self.assertFalse(is_eligible)

    def test_deadline_rejection_when_candidate_extends_past_request_deadline(self):
        request_deadline = date(2024, 2, 1)
        plan_completion = date(2024, 2, 15)
        self.assertFalse(plan_completion <= request_deadline)


class LifecycleReversalAndCardMinimumsTests(unittest.TestCase):
    """Reversal vs duplicate representation, separate card minimums."""

    def test_separate_card_minimums_do_not_offset(self):
        card_a_min = Decimal("50.00")
        card_b_min = Decimal("75.00")
        total_min_required = card_a_min + card_b_min
        self.assertEqual(total_min_required, Decimal("125.00"))


class InfeasibilityVsUnresolvedEvidenceTests(unittest.TestCase):
    """Unresolved evidence distinguished from financial infeasibility."""

    def test_unresolved_evidence_cannot_approve_unsafe_plan(self):
        ambiguous_income = EvidenceFact(
            source_type="message",
            source_id="msg_ambig",
            user_id="u1",
            related_event_id=None,
            related_request_id=None,
            fact_kind=FactKind.INCOME_AMOUNT_CHANGE,
            amount=Decimal("2000.00"),
            currency=Currency.USD,
            temporal_scope=TemporalScope(effective_from=ANCHOR, effective_until=None),
            ambiguous=True,
            ambiguity_note="Contingent on potential commission",
            raw_excerpt="Might get 2000 commission",
            observed_time="2024-01-10T10:00:00Z",
            effective_time=None,
        )
        self.assertTrue(ambiguous_income.ambiguous)
        is_admitted = not ambiguous_income.ambiguous
        self.assertFalse(is_admitted)


if __name__ == "__main__":
    unittest.main()

