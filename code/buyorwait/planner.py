"""Production candidate generator and ranking engine (Stage 5).

Responsibilities (per S-04, S-05, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-14, S-15, S-24):
  * Complete candidate enumeration across all five classes:
      1. Full payment today (unaided).
      2. Complete supplied installment options respecting max_installment_months and deadline.
      3. Prescribed 2-payment partial schedule when eligible.
      4. Wait for full payment when full payment is accepted and completes by deadline.
      5. Candidates made feasible by legal spending changes (up to 3 streams, bounded reductions).
      6. Fallback not_recommended candidate.
  * Published 6-level plan ranking (S-14):
      1. Completes by desired_completion_date.
      2. Zero spending changes preferred.
      3. Minimum total paid.
      4. Earliest first payment date.
      5. Fewest payments.
      6. Lowest payment_option_id.
  * Every candidate is independently replayed and validated before ranking.
  * Rejection reasons are recorded for every evaluated candidate class.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import itertools
import re
from typing import Sequence

from .csv_format import PlanEntry, ReduceChange, SpendingChange, StopChange
from .forecast import (
    assemble_flows,
    calculate_amount_safe_to_pay,
    calculate_earliest_full_payment_date,
    forecast_headroom,
)
from .independent_verifier import PlanReplayResult, replay_plan
from .recurrence import detect_recurring_streams, normalize_stream_description
from .schemas import (
    AffordabilityStatus,
    Dataset,
    ExpenseCategory,
    Flexibility,
    PaymentOption,
    PaymentOptionMethod,
    PaymentPreference,
    RecommendedPaymentMethod,
    Request,
)
from .simulator import CashFlow, FlowKind, ScheduledPayment, simulate


@dataclass(frozen=True, slots=True)
class FlexibleStreamCandidate:
    category: ExpenseCategory
    description: str
    canonical_event_id: str
    typical_amount: Decimal
    minimum_allowed_amount: Decimal | None
    is_stoppable: bool
    is_reducible: bool


@dataclass(frozen=True, slots=True)
class Candidate:
    method: RecommendedPaymentMethod
    payment_plan: tuple[PlanEntry, ...]
    spending_changes: tuple[SpendingChange, ...]
    payment_option_id: str | None
    total_paid: Decimal
    completes_by_deadline: bool
    first_payment_date: date
    payment_count: int
    affordability_status: AffordabilityStatus
    replay: PlanReplayResult | None
    is_safe: bool
    flows_used: tuple[CashFlow, ...] = ()
    rejection_reason: str | None = None


def find_flexible_streams(dataset: Dataset, user_id: str, anchor_date: date) -> tuple[FlexibleStreamCandidate, ...]:
    """Find all recurring streams for user_id that are legally adjustable under S-15.
    
    Conditions:
      1. flexibility is STOPPABLE, REDUCIBLE, or REDUCIBLE_OR_STOPPABLE.
      2. category is NOT in profile.expense_categories_to_protect.
      3. category is in profile.expense_categories_user_is_willing_to_stop (for stop)
         or in profile.expense_categories_user_is_willing_to_reduce (for reduce).
      4. Canonical event ID is the most recent historical event in that stream prior to or on anchor_date.
    """
    profile = dataset.profiles_by_user[user_id]
    protect = set(profile.expense_categories_to_protect)
    stop_ok = set(profile.expense_categories_user_is_willing_to_stop)
    reduce_ok = set(profile.expense_categories_user_is_willing_to_reduce)

    user_events = dataset.events_by_user.get(user_id, ())
    historical = [e for e in user_events if (e.settlement_date or e.event_date) <= anchor_date]

    # Group by (category, normalized_description)
    groups: dict[tuple[ExpenseCategory, str], list] = {}
    for e in historical:
        if e.flexibility == Flexibility.FIXED:
            continue
        norm_desc = normalize_stream_description(e.description)
        groups.setdefault((e.category, norm_desc), []).append(e)

    candidates: list[FlexibleStreamCandidate] = []
    for (cat, norm_desc), evts in groups.items():
        if cat in protect:
            continue
        evts_sorted = sorted(evts, key=lambda e: e.settlement_date or e.event_date)
        latest_evt = evts_sorted[-1]
        flex = latest_evt.flexibility

        can_stop = (
            flex in (Flexibility.STOPPABLE, Flexibility.REDUCIBLE_OR_STOPPABLE)
            and cat in stop_ok
        )
        can_reduce = (
            flex in (Flexibility.REDUCIBLE, Flexibility.REDUCIBLE_OR_STOPPABLE)
            and cat in reduce_ok
            and latest_evt.minimum_allowed_amount is not None
        )

        if not can_stop and not can_reduce:
            continue

        candidates.append(
            FlexibleStreamCandidate(
                category=cat,
                description=norm_desc,
                canonical_event_id=latest_evt.event_id,
                typical_amount=latest_evt.amount or Decimal(0),
                minimum_allowed_amount=latest_evt.minimum_allowed_amount,
                is_stoppable=can_stop,
                is_reducible=can_reduce,
            )
        )

    return tuple(candidates)


def apply_spending_changes_to_flows(
    flows: tuple[CashFlow, ...],
    changes: tuple[SpendingChange, ...],
    stream_candidates: tuple[FlexibleStreamCandidate, ...],
) -> tuple[CashFlow, ...]:
    """Apply savings from spending changes to forward cash flows.
    
    - 'stop:<event_id>': completely cancels future occurrences of that recurring stream.
    - 'reduce_to:<event_id>:<new_amount>': reduces debit of future occurrences to new_amount.
    Only applies to FlowKind.SETTLED_RECURRING_PROJECTION; never touches reserved pending
    debits, explicit scheduled events, or essential variable spend.
    """
    if not changes:
        return flows

    event_to_stream = {sc.canonical_event_id: sc for sc in stream_candidates}
    modified_flows: list[CashFlow] = []

    stop_descriptions: list[str] = []
    reduce_map: dict[str, Decimal] = {}

    for ch in changes:
        sc = event_to_stream.get(ch.event_id)
        if sc is None:
            continue
        if isinstance(ch, StopChange):
            stop_descriptions.append(sc.description)
        elif isinstance(ch, ReduceChange):
            reduce_map[sc.description] = ch.new_amount

    def _matches_stream(stream_desc: str, flow_lbl: str) -> bool:
        s_clean = stream_desc.strip().lower()
        lbl_clean = flow_lbl.strip().lower()
        if lbl_clean.endswith(" (reduced)"):
            lbl_clean = lbl_clean[:-10].strip()
        if ": " in lbl_clean:
            desc_part = lbl_clean.split(": ", 1)[1].strip()
            return desc_part == s_clean
        return lbl_clean == s_clean or lbl_clean == f"recurring {s_clean}"

    for flow in flows:
        if flow.kind != FlowKind.SETTLED_RECURRING_PROJECTION:
            modified_flows.append(flow)
            continue

        matched_stop = False
        matched_reduce = None

        flow_lbl = flow.label.lower()
        for s_desc in stop_descriptions:
            if _matches_stream(s_desc, flow_lbl):
                matched_stop = True
                break

        if matched_stop:
            # Flow is completely stopped
            continue

        for r_desc, min_amt in reduce_map.items():
            if _matches_stream(r_desc, flow_lbl):
                matched_reduce = min_amt
                break

        if matched_reduce is not None:
            # Debit flow amount is negative Decimal; reduce magnitude to matched_reduce
            new_amt = -abs(matched_reduce)
            modified_flows.append(
                CashFlow(
                    flow_date=flow.flow_date,
                    amount=new_amt,
                    kind=flow.kind,
                    label=flow.label + " (reduced)",
                )
            )
        else:
            modified_flows.append(flow)

    return tuple(modified_flows)


def enumerate_candidates(
    dataset: Dataset,
    request_id: str,
    *,
    evidence_facts: tuple = (),
    image_amounts: dict[str, Decimal] | None = None,
    variable_spend_method: str = "trailing_3_month_mean_floored_at_latest_month",
) -> tuple[Candidate, ...]:
    """Enumerate all candidate plans across all classes for one request."""
    request = dataset.all_requests_by_id[request_id]
    user_id = request.user_id
    profile = dataset.profiles_by_user[user_id]
    anchor_date = request.request_date
    deadline = request.desired_completion_date
    requested_amount = request.requested_amount
    opening_balance = profile.current_available_balance
    minimum_balance = profile.minimum_balance_to_keep

    user_methods = {m.value for m in profile.payment_methods_user_will_consider}

    # 1. Baseline flows and headroom (WITHOUT spending changes)
    baseline_flows = assemble_flows(
        dataset,
        user_id,
        anchor_date,
        evidence_facts=evidence_facts,
        image_amounts=image_amounts,
        variable_spend_method=variable_spend_method,
    )
    baseline_headroom = forecast_headroom(
        dataset,
        user_id,
        anchor_date,
        flows=baseline_flows,
    )
    safe_today = calculate_amount_safe_to_pay(baseline_headroom, requested_amount)
    earliest_full_date = calculate_earliest_full_payment_date(
        dataset,
        user_id,
        anchor_date,
        requested_amount,
        flows=baseline_flows,
        evidence_facts=evidence_facts,
        image_amounts=image_amounts,
        variable_spend_method=variable_spend_method,
    )

    candidates: list[Candidate] = []

    # Helper to replay and create a candidate
    def check_and_add_candidate(
        *,
        method: RecommendedPaymentMethod,
        plan_entries: tuple[PlanEntry, ...],
        spending_changes: tuple[SpendingChange, ...] = (),
        payment_option_id: str | None = None,
        total_paid: Decimal,
        affordability_status: AffordabilityStatus,
        flows_to_use: tuple[CashFlow, ...],
    ) -> None:
        rep = replay_plan(
            opening_balance=opening_balance,
            minimum_balance_to_keep=minimum_balance,
            anchor_date=anchor_date,
            flows=flows_to_use,
            plan_entries=plan_entries,
            requested_amount=requested_amount,
            deadline=deadline,
            expected_total=total_paid,
        )
        is_safe = rep.simulation.is_safe
        first_d = plan_entries[0].entry_date if plan_entries else anchor_date
        completes_deadline = rep.completes_by_deadline and (
            plan_entries[-1].entry_date <= deadline if plan_entries else False
        )

        reason = None
        if not is_safe:
            b0 = rep.simulation.breaches[0]
            reason = f"breaches minimum floor on {b0.day} by shortfall {b0.shortfall}"
        elif not completes_deadline:
            reason = f"completes on {plan_entries[-1].entry_date} after deadline {deadline}"

        candidates.append(
            Candidate(
                method=method,
                payment_plan=plan_entries,
                spending_changes=spending_changes,
                payment_option_id=payment_option_id,
                total_paid=total_paid,
                completes_by_deadline=completes_deadline,
                first_payment_date=first_d,
                payment_count=len(plan_entries),
                affordability_status=affordability_status,
                replay=rep,
                is_safe=is_safe,
                flows_used=flows_to_use,
                rejection_reason=reason,
            )
        )

    # -------------------------------------------------------------------------
    # Candidate Class 1: Full payment today (unaided)
    # -------------------------------------------------------------------------
    if "full_payment" in user_methods:
        check_and_add_candidate(
            method=RecommendedPaymentMethod.FULL_PAYMENT,
            plan_entries=(PlanEntry(entry_date=anchor_date, amount=requested_amount),),
            spending_changes=(),
            payment_option_id=None,
            total_paid=requested_amount,
            affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
            flows_to_use=baseline_flows,
        )

    # -------------------------------------------------------------------------
    # Candidate Class 2: Complete supplied installment options (unaided)
    # -------------------------------------------------------------------------
    if "installments" in user_methods and profile.max_installment_months is not None:
        max_m = profile.max_installment_months
        options = dataset.options_by_request.get(request_id, ())
        for opt in options:
            if opt.payment_method != PaymentOptionMethod.INSTALLMENTS:
                continue

            # Check number of payments and schedule duration
            if opt.number_of_payments > max_m:
                continue

            freq = opt.payment_frequency_days or 30
            last_date = opt.first_payment_date + timedelta(days=freq * (opt.number_of_payments - 1))
            span_days = (last_date - anchor_date).days
            if span_days > max_m * 31:
                continue

            # Build complete schedule
            plan_entries = tuple(
                PlanEntry(
                    entry_date=opt.first_payment_date + timedelta(days=freq * k),
                    amount=opt.payment_amount,
                )
                for k in range(opt.number_of_payments)
            )

            if last_date > anchor_date + timedelta(days=90):
                candidates.append(
                    Candidate(
                        method=RecommendedPaymentMethod.INSTALLMENTS,
                        payment_plan=plan_entries,
                        spending_changes=(),
                        payment_option_id=opt.payment_option_id,
                        total_paid=opt.total_payable_amount,
                        completes_by_deadline=False,
                        first_payment_date=opt.first_payment_date,
                        payment_count=opt.number_of_payments,
                        affordability_status=AffordabilityStatus.NOT_AFFORDABLE,
                        replay=None,
                        is_safe=False,
                        flows_used=baseline_flows,
                        rejection_reason=f"final payment on {last_date} exceeds 90-day horizon",
                    )
                )
                continue

            check_and_add_candidate(
                method=RecommendedPaymentMethod.INSTALLMENTS,
                plan_entries=plan_entries,
                spending_changes=(),
                payment_option_id=opt.payment_option_id,
                total_paid=opt.total_payable_amount,
                affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
                flows_to_use=baseline_flows,
            )

    # -------------------------------------------------------------------------
    # Candidate Class 3: Prescribed partial payment (unaided)
    # -------------------------------------------------------------------------
    if (
        request.allows_partial_payment
        and "partial_payment" in user_methods
        and Decimal(0) < safe_today < requested_amount
        and earliest_full_date is not None
        and earliest_full_date <= deadline
        and earliest_full_date > anchor_date
    ):
        p1 = safe_today
        p2 = requested_amount - safe_today
        plan_entries = (
            PlanEntry(entry_date=anchor_date, amount=p1),
            PlanEntry(entry_date=earliest_full_date, amount=p2),
        )
        check_and_add_candidate(
            method=RecommendedPaymentMethod.PARTIAL_PAYMENT,
            plan_entries=plan_entries,
            spending_changes=(),
            payment_option_id=None,
            total_paid=requested_amount,
            affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
            flows_to_use=baseline_flows,
        )

    # -------------------------------------------------------------------------
    # Candidate Class 4: Wait for safe full payment (unaided)
    # -------------------------------------------------------------------------
    if (
        "full_payment" in user_methods
        and earliest_full_date is not None
        and anchor_date < earliest_full_date <= deadline
    ):
        plan_entries = (PlanEntry(entry_date=earliest_full_date, amount=requested_amount),)
        check_and_add_candidate(
            method=RecommendedPaymentMethod.WAIT,
            plan_entries=plan_entries,
            spending_changes=(),
            payment_option_id=None,
            total_paid=requested_amount,
            affordability_status=AffordabilityStatus.AFFORDABLE_LATER,
            flows_to_use=baseline_flows,
        )

    # -------------------------------------------------------------------------
    # Candidate Class 5: Candidates enabled by legal spending changes
    # -------------------------------------------------------------------------
    flexible_streams = find_flexible_streams(dataset, user_id, anchor_date)
    if flexible_streams:
        # Generate legal atomic changes per stream
        stream_atomic_changes: list[list[SpendingChange]] = []
        for sc in flexible_streams:
            sc_changes = []
            if sc.is_stoppable:
                sc_changes.append(StopChange(event_id=sc.canonical_event_id))
            if sc.is_reducible and sc.minimum_allowed_amount is not None:
                sc_changes.append(ReduceChange(event_id=sc.canonical_event_id, new_amount=sc.minimum_allowed_amount))
            if sc_changes:
                stream_atomic_changes.append(sc_changes)

        # Enumerate combinations up to 3 distinct streams
        all_change_sets: list[tuple[SpendingChange, ...]] = []
        for r in (1, 2, 3):
            if r > len(stream_atomic_changes):
                continue
            for stream_combo in itertools.combinations(stream_atomic_changes, r):
                # Product of choices across the selected streams
                for change_combo in itertools.product(*stream_combo):
                    all_change_sets.append(tuple(change_combo))

        for change_set in all_change_sets:
            mod_flows = apply_spending_changes_to_flows(baseline_flows, change_set, flexible_streams)

            # Test 5.1: Full payment today under spending changes
            if "full_payment" in user_methods:
                check_and_add_candidate(
                    method=RecommendedPaymentMethod.FULL_PAYMENT,
                    plan_entries=(PlanEntry(entry_date=anchor_date, amount=requested_amount),),
                    spending_changes=change_set,
                    payment_option_id=None,
                    total_paid=requested_amount,
                    affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
                    flows_to_use=mod_flows,
                )

            # Test 5.2: Installments under spending changes
            if "installments" in user_methods and profile.max_installment_months is not None:
                max_m = profile.max_installment_months
                options = dataset.options_by_request.get(request_id, ())
                for opt in options:
                    if opt.payment_method != PaymentOptionMethod.INSTALLMENTS:
                        continue
                    if opt.number_of_payments > max_m:
                        continue
                    freq = opt.payment_frequency_days or 30
                    last_date = opt.first_payment_date + timedelta(days=freq * (opt.number_of_payments - 1))
                    span_days = (last_date - anchor_date).days
                    if span_days > max_m * 31:
                        continue
                    if last_date > anchor_date + timedelta(days=90):
                        continue

                    plan_entries = tuple(
                        PlanEntry(
                            entry_date=opt.first_payment_date + timedelta(days=freq * k),
                            amount=opt.payment_amount,
                        )
                        for k in range(opt.number_of_payments)
                    )
                    check_and_add_candidate(
                        method=RecommendedPaymentMethod.INSTALLMENTS,
                        plan_entries=plan_entries,
                        spending_changes=change_set,
                        payment_option_id=opt.payment_option_id,
                        total_paid=opt.total_payable_amount,
                        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
                        flows_to_use=mod_flows,
                    )

    # -------------------------------------------------------------------------
    # Candidate Class 6: Fallback not_recommended
    # -------------------------------------------------------------------------
    status_for_nr = (
        AffordabilityStatus.AFFORDABLE_LATER
        if earliest_full_date is not None
        else AffordabilityStatus.NOT_AFFORDABLE
    )
    candidates.append(
        Candidate(
            method=RecommendedPaymentMethod.NOT_RECOMMENDED,
            payment_plan=(),
            spending_changes=(),
            payment_option_id=None,
            total_paid=Decimal(0),
            completes_by_deadline=False,
            first_payment_date=anchor_date,
            payment_count=0,
            affordability_status=status_for_nr,
            replay=None,
            is_safe=True,
            rejection_reason="fallback when no safe eligible plan exists",
        )
    )

    return tuple(candidates)


def rank_candidates(candidates: tuple[Candidate, ...]) -> Candidate:
    """Rank candidates according to S-14 6-level hierarchy and return the top plan.
    
    Ranking Criteria (in order):
      1. Completes by requested deadline (True before False).
      2. Zero spending changes preferred (fewer changes before more changes).
      3. Minimum total paid (smaller total before larger total).
      4. Earliest first payment date (earlier date before later date).
      5. Fewest payments (1 before 2 before 3...).
      6. Lowest payment_option_id as final published tie-breaker.
      7. Stable secondary tie-breaker on method.
    """
    safe_candidates = [c for c in candidates if c.is_safe and c.method != RecommendedPaymentMethod.NOT_RECOMMENDED]

    # Filter to safe candidates completing by deadline
    valid_candidates = [c for c in safe_candidates if c.completes_by_deadline]

    if not valid_candidates:
        # Return the not_recommended fallback
        for c in candidates:
            if c.method == RecommendedPaymentMethod.NOT_RECOMMENDED:
                return c
        # If somehow missing, construct it
        return Candidate(
            method=RecommendedPaymentMethod.NOT_RECOMMENDED,
            payment_plan=(),
            spending_changes=(),
            payment_option_id=None,
            total_paid=Decimal(0),
            completes_by_deadline=False,
            first_payment_date=date.min,
            payment_count=0,
            affordability_status=AffordabilityStatus.NOT_AFFORDABLE,
            replay=None,
            is_safe=True,
        )

    # Method priority tie-breaker (only reached if all 6 official levels are equal)
    method_pref = {
        RecommendedPaymentMethod.FULL_PAYMENT: 1,
        RecommendedPaymentMethod.PARTIAL_PAYMENT: 2,
        RecommendedPaymentMethod.WAIT: 3,
        RecommendedPaymentMethod.INSTALLMENTS: 4,
        RecommendedPaymentMethod.NOT_RECOMMENDED: 5,
    }

    def sort_key(c: Candidate):
        # 1. Completes by requested deadline (0 for True, 1 for False)
        level_1 = 0 if c.completes_by_deadline else 1
        # 2. Avoids spending changes (binary: 0 for no changes, 1 for changes needed per S-14)
        level_2 = 0 if len(c.spending_changes) == 0 else 1
        # 3. Minimizes total payment cost (smaller total before larger total)
        level_3 = c.total_paid
        # 4. Earliest first payment date (starts earlier)
        level_4 = c.first_payment_date
        # 5. Fewest payments (1 before 2 before 3...)
        level_5 = c.payment_count
        # 6. Fewer spending changes as tie-breaker among plans with spending changes
        level_6 = len(c.spending_changes)
        # 7. Lowest payment_option_id as final published tie-breaker (empty string sorts first)
        level_7 = c.payment_option_id or ""
        # 8. Method priority secondary tie-breaker
        level_8 = method_pref.get(c.method, 99)
        return (level_1, level_2, level_3, level_4, level_5, level_6, level_7, level_8)

    valid_candidates.sort(key=sort_key)
    return valid_candidates[0]
