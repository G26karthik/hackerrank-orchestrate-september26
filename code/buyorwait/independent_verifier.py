"""Independent verifier: replay a candidate `payment_plan` against a set of
cash flows and report every constraint from the written contract, using only
`simulator.py` (never the future planner). This is the production-facing
wrapper the responsibilities table calls out separately from the "reference
simulator" -- concretely, it is `simulate()` plus the plan-level checks
(deadline, sum-to-requested-amount, chronology) that turn a raw feasibility
replay into a verdict on one candidate `payment_plan` string.

It takes `PlanEntry` objects (code/buyorwait/csv_format.py) rather than a raw
CSV string, so the same object the writer is about to emit -- or the string
the evaluator just parsed out of someone else's `output.csv` -- can be handed
here unchanged. It never re-implements plan *ranking* (S-14): that is the
future planner's job. This module only answers "given this plan and these
flows, is it actually safe and complete", which is exactly what an
independent check should be able to answer without knowing how the plan was
chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from .csv_format import PlanEntry, is_chronological
from .simulator import CashFlow, FlowKind, ScheduledPayment, SimulationResult, simulate

_SUM_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PlanReplayResult:
    simulation: SimulationResult
    is_chronological: bool
    sums_to_requested_amount: bool
    completes_by_deadline: bool  # last entry (if any) is on or before the deadline (S-05's "<=")
    amount_gap: Decimal  # requested_amount - sum(entry amounts); 0 when it matches exactly

    @property
    def is_fully_valid(self) -> bool:
        """True only when EVERY independently-checkable constraint holds:
        floor never breached, entries in order, amounts sum to the requested
        total, and the last payment lands on or before the deadline."""
        return (
            self.simulation.is_safe
            and self.is_chronological
            and self.sums_to_requested_amount
            and self.completes_by_deadline
        )


def replay_plan(
    *,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    flows: Iterable[CashFlow],
    plan_entries: tuple[PlanEntry, ...],
    requested_amount: Decimal,
    deadline: date,
    expected_total: Decimal | None = None,
) -> PlanReplayResult:
    """Replay `plan_entries` as scheduled payments on top of `flows`, using
    `simulator.simulate`, and check the plan-level constraints that a bare
    feasibility replay does not know about on its own.
    """
    schedule = tuple(
        ScheduledPayment(payment_date=e.entry_date, amount=e.amount, label=f"plan:{e.entry_date.isoformat()}")
        for e in plan_entries
    )
    sim = simulate(
        opening_balance=opening_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=flows,
        schedule=schedule,
    )

    target_sum = expected_total if expected_total is not None else requested_amount
    total_paid = sum((e.amount for e in plan_entries), Decimal(0))
    gap = target_sum - total_paid
    sums_ok = abs(gap) <= _SUM_TOLERANCE

    if plan_entries:
        completes_ok = plan_entries[-1].entry_date <= deadline
    else:
        completes_ok = True  # nothing scheduled, so nothing can be late

    return PlanReplayResult(
        simulation=sim,
        is_chronological=is_chronological(plan_entries),
        sums_to_requested_amount=sums_ok,
        completes_by_deadline=completes_ok,
        amount_gap=gap,
    )


@dataclass(frozen=True, slots=True)
class DecisionVerificationResult:
    request_id: str
    is_valid: bool
    positive_plan_verified: bool
    negative_decision_verified: bool
    earliest_date_verified: bool
    safe_today_verified: bool
    plan_replay: PlanReplayResult | None
    candidate_rejections: dict[str, str]
    failure_notes: tuple[str, ...]


def verify_earliest_date_brute_force(
    *,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    flows: Iterable[CashFlow],
    requested_amount: Decimal,
    target_earliest_date: date | None,
    horizon_days: int = 90,
) -> bool:
    """Verify that target_earliest_date mathematically equals the earliest date
    found by brute-force injecting requested_amount into simulator.simulate().
    """
    flow_list = tuple(flows)
    bf_earliest: date | None = None

    for offset in range(horizon_days + 1):
        test_date = anchor_date + timedelta(days=offset)
        sim = simulate(
            opening_balance=opening_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            anchor_date=anchor_date,
            flows=flow_list,
            schedule=(ScheduledPayment(payment_date=test_date, amount=requested_amount),),
        )
        if sim.is_safe:
            bf_earliest = test_date
            break

    return bf_earliest == target_earliest_date


from .reference_evaluator import reference_calculate_capacity, reference_simulate
from .schemas import PaymentOption


def verify_decision(
    *,
    request_id: str,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    deadline: date,
    requested_amount: Decimal,
    user_accepted_methods: set[str],
    recommended_method: str,
    plan_entries: tuple[PlanEntry, ...],
    spending_changes: tuple,
    amount_safe_to_pay: Decimal,
    earliest_date_for_full_payment: date | None,
    baseline_flows: tuple[CashFlow, ...],
    modified_flows: tuple[CashFlow, ...] | None = None,
    candidate_rejections: dict[str, str] | None = None,
    expected_total: Decimal | None = None,
    payment_options: Iterable[RequestPaymentOption] = (),
    payment_option_id: str | None = None,
    allows_partial_payment: bool = False,
    max_installment_months: int | None = None,
) -> DecisionVerificationResult:
    """Independently verify both positive and negative decisions from end to end."""
    flows_to_use = modified_flows if modified_flows is not None else baseline_flows
    rejections = dict(candidate_rejections) if candidate_rejections else {}
    failures: list[str] = []

    pos_ok = False
    neg_ok = False
    plan_rep: PlanReplayResult | None = None

    # Compute independent maximal safe capacity today
    expected_capacity = reference_calculate_capacity(
        opening_balance=opening_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=baseline_flows,
        requested_amount=requested_amount,
    )

    if recommended_method != "not_recommended":
        # 1. Method must be accepted
        if recommended_method == "wait":
            method_ok = "full_payment" in user_accepted_methods
        else:
            method_ok = recommended_method in user_accepted_methods

        if not method_ok:
            failures.append(f"method '{recommended_method}' is not in user accepted methods {user_accepted_methods}")

        # 2. Independent expected total derivation (never from plan itself)
        if expected_total is not None:
            target_total = expected_total
        elif recommended_method in ("full_payment", "partial_payment", "wait"):
            target_total = requested_amount
        elif recommended_method == "installments":
            opt_map = {opt.payment_option_id: opt for opt in payment_options}
            if payment_option_id and payment_option_id in opt_map:
                target_total = opt_map[payment_option_id].total_payable_amount
            else:
                failures.append(
                    "installments verification requires expected_total or matching payment_option; "
                    "cannot derive expected total from plan itself"
                )
                target_total = requested_amount
        else:
            target_total = requested_amount

        # 3. Method-specific schedule constraints
        if recommended_method == "partial_payment":
            if len(plan_entries) != 2:
                failures.append(f"partial_payment must have exactly 2 entries, got {len(plan_entries)}")
            else:
                p1, p2 = plan_entries[0], plan_entries[1]
                if p1.entry_date != anchor_date:
                    failures.append(f"partial_payment first entry date {p1.entry_date} != request date {anchor_date}")
                if abs(p1.amount - amount_safe_to_pay) > _SUM_TOLERANCE:
                    failures.append(f"partial_payment first entry amount {p1.amount} != amount_safe_to_pay {amount_safe_to_pay}")
                if earliest_date_for_full_payment is not None and p2.entry_date != earliest_date_for_full_payment:
                    failures.append(f"partial_payment second entry date {p2.entry_date} != earliest_date {earliest_date_for_full_payment}")
                if p2.entry_date > deadline:
                    failures.append(f"partial_payment second entry date {p2.entry_date} exceeds deadline {deadline}")
                if abs((p1.amount + p2.amount) - requested_amount) > _SUM_TOLERANCE:
                    failures.append(f"partial_payment entries sum {p1.amount + p2.amount} != requested_amount {requested_amount}")

        elif recommended_method == "installments" and payment_options and payment_option_id:
            opt_map = {opt.payment_option_id: opt for opt in payment_options}
            if payment_option_id in opt_map:
                opt = opt_map[payment_option_id]
                if len(plan_entries) != opt.number_of_payments:
                    failures.append(
                        f"installment count {len(plan_entries)} does not match option payments {opt.number_of_payments}"
                    )
                if max_installment_months is not None and opt.number_of_payments > max_installment_months:
                    failures.append(
                        f"installment option {opt.payment_option_id} payments {opt.number_of_payments} > max_installment_months {max_installment_months}"
                    )
                for idx, entry in enumerate(plan_entries):
                    if abs(entry.amount - opt.payment_amount) > _SUM_TOLERANCE:
                        failures.append(
                            f"installment entry {idx} amount {entry.amount} != option payment_amount {opt.payment_amount}"
                        )
                if plan_entries and plan_entries[-1].entry_date > deadline:
                    failures.append(
                        f"installment final payment on {plan_entries[-1].entry_date} exceeds deadline {deadline}"
                    )

        # Plan replay must be fully valid against target_total
        plan_rep = replay_plan(
            opening_balance=opening_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            anchor_date=anchor_date,
            flows=flows_to_use,
            plan_entries=plan_entries,
            requested_amount=requested_amount,
            deadline=deadline,
            expected_total=target_total,
        )
        if not plan_rep.is_fully_valid:
            failures.append(
                f"plan replay invalid: safe={plan_rep.simulation.is_safe}, "
                f"chronological={plan_rep.is_chronological}, "
                f"sums={plan_rep.sums_to_requested_amount} (expected {target_total}, got {sum(e.amount for e in plan_entries)}), "
                f"completes={plan_rep.completes_by_deadline}"
            )
        else:
            pos_ok = True
    else:
        # Negative decision verification: ensure no spurious rejection (catch false negatives)
        if "full_payment" in user_accepted_methods:
            if expected_capacity >= requested_amount and anchor_date <= deadline:
                failures.append(
                    f"recommended 'not_recommended' but full payment of {requested_amount} is safe today (safe_today={expected_capacity})"
                )
            elif earliest_date_for_full_payment is not None and earliest_date_for_full_payment <= deadline:
                failures.append(
                    f"recommended 'not_recommended' but full payment is safe on {earliest_date_for_full_payment} on or before deadline {deadline}"
                )

        # Check if an installment option without spending changes was safe and eligible
        if "installments" in user_accepted_methods and payment_options:
            for opt in payment_options:
                opt_method = opt.payment_method.value if hasattr(opt.payment_method, "value") else str(opt.payment_method)
                if opt_method != "installments":
                    continue
                if max_installment_months is not None and opt.number_of_payments > max_installment_months:
                    continue
                freq = opt.payment_frequency_days or 30
                last_date = opt.first_payment_date + timedelta(days=freq * (opt.number_of_payments - 1))
                if last_date <= deadline and last_date <= anchor_date + timedelta(days=90):
                    opt_schedule = tuple(
                        ScheduledPayment(
                            payment_date=opt.first_payment_date + timedelta(days=freq * k),
                            amount=opt.payment_amount,
                        )
                        for k in range(opt.number_of_payments)
                    )
                    sim_opt = reference_simulate(
                        opening_balance=opening_balance,
                        minimum_balance_to_keep=minimum_balance_to_keep,
                        anchor_date=anchor_date,
                        flows=baseline_flows,
                        schedule=opt_schedule,
                    )
                    if sim_opt.is_safe:
                        failures.append(
                            f"recommended 'not_recommended' but installment option {opt.payment_option_id} is safe without spending changes"
                        )
                        break

        if not failures:
            neg_ok = True

    # 4. Verify amount_safe_to_pay equals maximal safe capacity today
    safe_today_ok = abs(amount_safe_to_pay - expected_capacity) <= Decimal("0.01")
    if not safe_today_ok:
        failures.append(
            f"amount_safe_to_pay {amount_safe_to_pay} does not equal maximal safe capacity {expected_capacity} "
            f"(must be maximum safe amount today capped at requested amount)"
        )

    # 5. Verify earliest_date_for_full_payment via brute force
    earliest_ok = verify_earliest_date_brute_force(
        opening_balance=opening_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=baseline_flows,
        requested_amount=requested_amount,
        target_earliest_date=earliest_date_for_full_payment,
    )
    if not earliest_ok:
        failures.append(f"earliest_date_for_full_payment {earliest_date_for_full_payment} does not match brute force")

    is_all_valid = (len(failures) == 0) and (pos_ok or neg_ok) and safe_today_ok and earliest_ok

    return DecisionVerificationResult(
        request_id=request_id,
        is_valid=is_all_valid,
        positive_plan_verified=pos_ok,
        negative_decision_verified=neg_ok,
        earliest_date_verified=earliest_ok,
        safe_today_verified=safe_today_ok,
        plan_replay=plan_rep,
        candidate_rejections=rejections,
        failure_notes=tuple(failures),
    )


__all__ = [
    "PlanReplayResult",
    "DecisionVerificationResult",
    "replay_plan",
    "verify_decision",
    "verify_earliest_date_brute_force",
    "CashFlow",
    "FlowKind",
]

