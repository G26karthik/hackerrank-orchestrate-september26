"""Reference Evaluator: Pure first-principles financial evaluation and differential checking.

This module is a completely independent reference implementation of cash-flow
simulation, capacity calculation, earliest safe date search, candidate plan
evaluation, and S-14 ranking hierarchy.

It does NOT call simulator.simulate(), forecast.forecast_headroom(), or
planner.enumerate_candidates(). It serves as an independent benchmark for
property testing, differential verification, and catching false negatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence, Iterable

from .csv_format import PlanEntry
from .schemas import (
    AffordabilityStatus,
    Dataset,
    ExpenseCategory,
    Flexibility,
    PaymentPreference,
    RecommendedPaymentMethod,
    PaymentOption,
)
from .simulator import CashFlow, FlowKind, ScheduledPayment


# ---------------------------------------------------------------------------
# 1. Pure First-Principles Cash Flow Simulation
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ReferenceSimulationResult:
    is_safe: bool
    worst_headroom: Decimal
    binding_date: date
    first_breach_date: date | None
    breaches: tuple[tuple[date, Decimal], ...]  # (date, shortfall)
    daily_balances: tuple[tuple[date, Decimal, Decimal], ...]  # (date, floor_check, end_of_day)


def reference_simulate(
    *,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    flows: Iterable[CashFlow],
    schedule: Iterable[ScheduledPayment] = (),
    same_day_order: str = "credits_first",
    horizon_days: int = 90,
) -> ReferenceSimulationResult:
    """Pure first-principles ledger simulation over [anchor_date, anchor_date + horizon_days]."""
    horizon_end = anchor_date + timedelta(days=horizon_days)

    # Accumulate debits and credits by day
    debits_by_day: dict[date, Decimal] = {}
    credits_by_day: dict[date, Decimal] = {}
    active_days: set[date] = set()

    for f in flows:
        if f.flow_date < anchor_date or f.flow_date > horizon_end:
            continue
        active_days.add(f.flow_date)
        if f.amount < 0:
            debits_by_day[f.flow_date] = debits_by_day.get(f.flow_date, Decimal(0)) + (-f.amount)
        else:
            credits_by_day[f.flow_date] = credits_by_day.get(f.flow_date, Decimal(0)) + f.amount

    for p in schedule:
        if p.payment_date < anchor_date or p.payment_date > horizon_end:
            continue
        active_days.add(p.payment_date)
        debits_by_day[p.payment_date] = debits_by_day.get(p.payment_date, Decimal(0)) + p.amount

    running = opening_balance
    worst_headroom = opening_balance - minimum_balance_to_keep
    binding_date = anchor_date
    breaches: list[tuple[date, Decimal]] = []
    daily_records: list[tuple[date, Decimal, Decimal]] = []

    # Check start of anchor date
    if opening_balance < minimum_balance_to_keep:
        breaches.append((anchor_date, minimum_balance_to_keep - opening_balance))

    # Evaluate sequentially across every day from anchor_date to horizon_end
    curr = anchor_date
    while curr <= horizon_end:
        day_deb = debits_by_day.get(curr, Decimal(0))
        day_cred = credits_by_day.get(curr, Decimal(0))

        if day_deb == Decimal(0) and day_cred == Decimal(0):
            # No movements on curr
            curr += timedelta(days=1)
            continue

        if same_day_order == "credits_first":
            floor_check = running + day_cred - day_deb
            end_of_day = floor_check
        elif same_day_order == "debits_first":
            floor_check = running - day_deb
            end_of_day = floor_check + day_cred
        else:
            raise ValueError(f"Unknown same_day_order: {same_day_order}")

        headroom = floor_check - minimum_balance_to_keep
        if headroom < worst_headroom:
            worst_headroom = headroom
            binding_date = curr

        if floor_check < minimum_balance_to_keep:
            breaches.append((curr, minimum_balance_to_keep - floor_check))

        daily_records.append((curr, floor_check, end_of_day))
        running = end_of_day
        curr += timedelta(days=1)

    is_safe = (len(breaches) == 0) and (opening_balance >= minimum_balance_to_keep)
    first_breach = breaches[0][0] if breaches else None

    return ReferenceSimulationResult(
        is_safe=is_safe,
        worst_headroom=worst_headroom,
        binding_date=binding_date,
        first_breach_date=first_breach,
        breaches=tuple(breaches),
        daily_balances=tuple(daily_records),
    )


# ---------------------------------------------------------------------------
# 2. Pure First-Principles Capacity Calculation
# ---------------------------------------------------------------------------

def reference_calculate_capacity(
    *,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    flows: Iterable[CashFlow],
    requested_amount: Decimal,
    same_day_order: str = "credits_first",
    horizon_days: int = 90,
) -> Decimal:
    """S-03: Largest amount safe on request_date before optional spending changes,
    capped at requested_amount. Capacity must be the MAXIMUM safe amount today,
    not merely a feasible amount.
    """
    sim = reference_simulate(
        opening_balance=opening_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=flows,
        schedule=(),
        same_day_order=same_day_order,
        horizon_days=horizon_days,
    )
    return max(Decimal(0), min(sim.worst_headroom, requested_amount))


# ---------------------------------------------------------------------------
# 3. Pure First-Principles Earliest Safe Date Search
# ---------------------------------------------------------------------------

def reference_calculate_earliest_full_payment_date(
    *,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    flows: Iterable[CashFlow],
    requested_amount: Decimal,
    same_day_order: str = "credits_first",
    horizon_days: int = 90,
) -> date | None:
    """S-06: First date in [anchor_date, anchor_date + horizon_days] where injecting
    one full payment of requested_amount keeps balance >= minimum_balance_to_keep
    over the entire horizon.
    """
    flow_list = tuple(flows)
    for offset in range(horizon_days + 1):
        target_d = anchor_date + timedelta(days=offset)
        sim = reference_simulate(
            opening_balance=opening_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            anchor_date=anchor_date,
            flows=flow_list,
            schedule=(ScheduledPayment(payment_date=target_d, amount=requested_amount),),
            same_day_order=same_day_order,
            horizon_days=horizon_days,
        )
        if sim.is_safe:
            return target_d
    return None


# ---------------------------------------------------------------------------
# 4. Pure Reference Candidate Generation & S-14 Ranking
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    method: RecommendedPaymentMethod
    payment_plan: tuple[PlanEntry, ...]
    spending_changes: tuple
    payment_option_id: str | None
    total_paid: Decimal
    completes_by_deadline: bool
    first_payment_date: date
    payment_count: int
    is_safe: bool
    rejection_reason: str | None = None


def reference_evaluate_candidates(
    *,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    deadline: date,
    requested_amount: Decimal,
    user_accepted_methods: set[str],
    options: Iterable[PaymentOption],
    flows: Iterable[CashFlow],
    allows_partial_payment: bool,
    max_installment_months: int | None = None,
    same_day_order: str = "credits_first",
    horizon_days: int = 90,
) -> tuple[ReferenceCandidate, tuple[ReferenceCandidate, ...]]:
    """Enumerate all eligible candidate plan families and rank them strictly per S-14.
    Returns (winning_candidate, all_candidates).
    """
    flow_list = tuple(flows)
    candidates: list[ReferenceCandidate] = []

    # 1. Capacity & Earliest date
    capacity = reference_calculate_capacity(
        opening_balance=opening_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=flow_list,
        requested_amount=requested_amount,
        same_day_order=same_day_order,
        horizon_days=horizon_days,
    )
    earliest_date = reference_calculate_earliest_full_payment_date(
        opening_balance=opening_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=flow_list,
        requested_amount=requested_amount,
        same_day_order=same_day_order,
        horizon_days=horizon_days,
    )

    # 2. Full payment today
    if "full_payment" in user_accepted_methods:
        is_safe = capacity >= requested_amount
        completes = anchor_date <= deadline
        candidates.append(
            ReferenceCandidate(
                method=RecommendedPaymentMethod.FULL_PAYMENT,
                payment_plan=(PlanEntry(entry_date=anchor_date, amount=requested_amount),),
                spending_changes=(),
                payment_option_id=None,
                total_paid=requested_amount,
                completes_by_deadline=completes,
                first_payment_date=anchor_date,
                payment_count=1,
                is_safe=is_safe,
                rejection_reason=None if is_safe else f"capacity {capacity} < requested {requested_amount}",
            )
        )

    # 3. Installments
    if "installments" in user_accepted_methods:
        for opt in options:
            opt_method = opt.payment_method.value if hasattr(opt.payment_method, "value") else str(opt.payment_method)
            if opt_method != "installments" or opt.number_of_payments <= 1:
                continue
            if max_installment_months is not None and opt.number_of_payments > max_installment_months:
                candidates.append(
                    ReferenceCandidate(
                        method=RecommendedPaymentMethod.INSTALLMENTS,
                        payment_plan=(),
                        spending_changes=(),
                        payment_option_id=opt.payment_option_id,
                        total_paid=opt.total_payable_amount,
                        completes_by_deadline=False,
                        first_payment_date=opt.first_payment_date,
                        payment_count=opt.number_of_payments,
                        is_safe=False,
                        rejection_reason=f"payments {opt.number_of_payments} > max_installment_months {max_installment_months}",
                    )
                )
                continue

            freq = opt.payment_frequency_days or 30
            last_date = opt.first_payment_date + timedelta(days=freq * (opt.number_of_payments - 1))
            schedule = tuple(
                ScheduledPayment(
                    payment_date=opt.first_payment_date + timedelta(days=freq * k),
                    amount=opt.payment_amount,
                )
                for k in range(opt.number_of_payments)
            )
            plan_entries = tuple(
                PlanEntry(entry_date=s.payment_date, amount=s.amount)
                for s in schedule
            )

            # Check horizon
            if last_date > anchor_date + timedelta(days=horizon_days):
                candidates.append(
                    ReferenceCandidate(
                        method=RecommendedPaymentMethod.INSTALLMENTS,
                        payment_plan=plan_entries,
                        spending_changes=(),
                        payment_option_id=opt.payment_option_id,
                        total_paid=opt.total_payable_amount,
                        completes_by_deadline=False,
                        first_payment_date=opt.first_payment_date,
                        payment_count=opt.number_of_payments,
                        is_safe=False,
                        rejection_reason=f"final payment on {last_date} exceeds {horizon_days}-day horizon",
                    )
                )
                continue

            # Simulate
            sim = reference_simulate(
                opening_balance=opening_balance,
                minimum_balance_to_keep=minimum_balance_to_keep,
                anchor_date=anchor_date,
                flows=flow_list,
                schedule=schedule,
                same_day_order=same_day_order,
                horizon_days=horizon_days,
            )
            completes = last_date <= deadline
            candidates.append(
                ReferenceCandidate(
                    method=RecommendedPaymentMethod.INSTALLMENTS,
                    payment_plan=plan_entries,
                    spending_changes=(),
                    payment_option_id=opt.payment_option_id,
                    total_paid=opt.total_payable_amount,
                    completes_by_deadline=completes,
                    first_payment_date=opt.first_payment_date,
                    payment_count=opt.number_of_payments,
                    is_safe=sim.is_safe,
                    rejection_reason=None if sim.is_safe else f"breaches floor on {sim.first_breach_date}",
                )
            )

    # 4. Partial payment
    if (
        allows_partial_payment
        and "partial_payment" in user_accepted_methods
        and Decimal(0) < capacity < requested_amount
        and earliest_date is not None
        and earliest_date <= deadline
        and earliest_date > anchor_date
    ):
        p1 = capacity
        p2 = requested_amount - capacity
        schedule = (
            ScheduledPayment(payment_date=anchor_date, amount=p1),
            ScheduledPayment(payment_date=earliest_date, amount=p2),
        )
        sim = reference_simulate(
            opening_balance=opening_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            anchor_date=anchor_date,
            flows=flow_list,
            schedule=schedule,
            same_day_order=same_day_order,
            horizon_days=horizon_days,
        )
        plan_entries = (
            PlanEntry(entry_date=anchor_date, amount=p1),
            PlanEntry(entry_date=earliest_date, amount=p2),
        )
        candidates.append(
            ReferenceCandidate(
                method=RecommendedPaymentMethod.PARTIAL_PAYMENT,
                payment_plan=plan_entries,
                spending_changes=(),
                payment_option_id=None,
                total_paid=requested_amount,
                completes_by_deadline=earliest_date <= deadline,
                first_payment_date=anchor_date,
                payment_count=2,
                is_safe=sim.is_safe,
                rejection_reason=None if sim.is_safe else f"partial payment breaches floor on {sim.first_breach_date}",
            )
        )

    # 5. Wait for full payment
    if (
        "full_payment" in user_accepted_methods
        and earliest_date is not None
        and anchor_date < earliest_date <= deadline
    ):
        candidates.append(
            ReferenceCandidate(
                method=RecommendedPaymentMethod.WAIT,
                payment_plan=(PlanEntry(entry_date=earliest_date, amount=requested_amount),),
                spending_changes=(),
                payment_option_id=None,
                total_paid=requested_amount,
                completes_by_deadline=True,
                first_payment_date=earliest_date,
                payment_count=1,
                is_safe=True,
                rejection_reason=None,
            )
        )

    # Filter safe candidates
    safe_candidates = [c for c in candidates if c.is_safe]

    if not safe_candidates:
        # not_recommended
        not_rec = ReferenceCandidate(
            method=RecommendedPaymentMethod.NOT_RECOMMENDED,
            payment_plan=(),
            spending_changes=(),
            payment_option_id=None,
            total_paid=Decimal(0),
            completes_by_deadline=False,
            first_payment_date=anchor_date,
            payment_count=0,
            is_safe=True,
            rejection_reason="No eligible candidate plan keeps minimum protected balance",
        )
        return not_rec, tuple(candidates)

    # S-14 Ranking Hierarchy:
    # 1. Completes by deadline (True before False)
    # 2. No spending changes preferred over any changes (binary: 0 changes before >=1 changes)
    # 3. Minimizes total payment cost
    # 4. Starts earlier (first_payment_date)
    # 5. Fewer payments (payment_count)
    # 6. Option ID (alphabetical)
    # 7. Method priority
    def _method_priority(m: RecommendedPaymentMethod) -> int:
        priorities = {
            RecommendedPaymentMethod.FULL_PAYMENT: 1,
            RecommendedPaymentMethod.PARTIAL_PAYMENT: 2,
            RecommendedPaymentMethod.INSTALLMENTS: 3,
            RecommendedPaymentMethod.WAIT: 4,
            RecommendedPaymentMethod.NOT_RECOMMENDED: 5,
        }
        return priorities.get(m, 99)

    ranked = sorted(
        safe_candidates,
        key=lambda c: (
            0 if c.completes_by_deadline else 1,
            0 if len(c.spending_changes) == 0 else 1,
            c.total_paid,
            c.first_payment_date,
            c.payment_count,
            len(c.spending_changes),
            c.payment_option_id or "",
            _method_priority(c.method),
        ),
    )

    return ranked[0], tuple(candidates)
