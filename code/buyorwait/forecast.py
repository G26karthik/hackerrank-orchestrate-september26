"""Production 90-day cash-flow forecast and headroom engine.

Responsibilities (per S-03, S-04, S-06, S-16, S-17, S-18, S-19, U-WINDOW-1, U-SIMORDER-1):
  * Assembles signed CashFlow sequence for one user from resolved fields (resolver.py),
    projected recurring streams (recurrence.py), and conservative variable-spend estimates.
  * Preserves S-16 pending-debit reservation: immediate reserve on anchor_date, never
    deducted twice.
  * Preserves S-17 exclusions: pending credits, failed/cancelled rows, and unrealized
    investment valuations are never added.
  * Preserves historical-settlement exclusion: no flow dated < anchor_date is ever passed
    to the simulator.
  * Exposes 90-day baseline trajectory, binding date, and available headroom.
  * Computes amount_safe_to_pay and scans earliest_date_for_full_payment via
    replaying through reference simulator.simulate().
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from .evidence import EvidenceFact
from .recurrence import (
    RecurrenceConfidence,
    detect_recurring_streams,
    estimate_variable_spend,
    project_occurrences,
)
from .resolver import FlowAdmission, LifecycleGroup, resolve_user_events
from .schemas import Currency, Dataset, Direction, EventStatus, ExpenseCategory
from .simulator import (
    FORECAST_HORIZON_DAYS,
    CashFlow,
    FlowKind,
    ScheduledPayment,
    SimulationResult,
    simulate,
)


def assemble_flows(
    dataset: Dataset,
    user_id: str,
    anchor_date: date,
    evidence_facts: tuple[EvidenceFact, ...] = (),
    *,
    image_amounts: dict[str, Decimal] | None = None,
    variable_spend_method: str = "trailing_3_month_mean_floored_at_latest_month",
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> tuple[CashFlow, ...]:
    """Build the ordered CashFlow sequence for one user across [anchor_date, anchor_date + horizon_days].

    Includes:
      1. Reserved pending debits on anchor_date (S-16, U-DUP-1).
      2. Admitted explicit future events (non-recurring scheduled debits/credits).
      3. Projected recurring streams (salary, rent, subscriptions, utilities, debt).
      4. Conservative variable essential spending (groceries, transport, dining).

    Excludes:
      1. All flows dated < anchor_date (already in opening balance).
      2. All pending credits (S-16).
      3. Cancelled and failed events (S-17).
      4. Unrealized/non-cash valuations (S-17).
      5. Internal self-transfers.
    """
    horizon_end = anchor_date + timedelta(days=horizon_days)
    profile = dataset.profiles_by_user[user_id]
    home_currency = profile.home_currency

    # 1. Resolve normalized flows and lifecycle graph
    resolved_fields, normalized_flows = resolve_user_events(
        dataset,
        user_id,
        evidence_facts=evidence_facts,
        as_of_date=anchor_date,
        image_amounts=image_amounts,
    )

    # 2. Detect recurring streams and project occurrences
    streams = detect_recurring_streams(
        dataset,
        user_id,
        evidence_facts=evidence_facts,
        as_of_date=anchor_date,
        image_amounts=image_amounts,
    )

    # Collect explicit future events for reconciliation
    explicit_future = tuple(
        e for e in dataset.events_by_user.get(user_id, ())
        if e.status in (EventStatus.SCHEDULED, EventStatus.PENDING)
        and (e.settlement_date or e.event_date) >= anchor_date
    )

    occurrences = project_occurrences(
        streams,
        start=anchor_date,
        end=horizon_end,
        explicit_future_events=explicit_future,
        home_currency=home_currency,
        dataset=dataset,
    )

    # Collect which explicit event IDs were reconciled into recurring occurrences
    reconciled_event_ids = {
        occ.reconciled_event_id
        for occ in occurrences
        if occ.is_explicit_event and occ.reconciled_event_id is not None
    }

    # Collect which event IDs are reserved pending debits (to suppress matching recurring projections)
    reserved_pending_ids: set[str] = set()

    flows: list[CashFlow] = []

    # 3. Add reserved pending debits (on anchor_date, S-16 / U-DUP-1)
    for nf in normalized_flows:
        if nf.is_reserved_pending_debit and nf.admission == FlowAdmission.ADMITTED:
            reserved_pending_ids.add(nf.flow_id)
            # Reserve on anchor_date
            flows.append(
                CashFlow(
                    flow_date=anchor_date,
                    amount=nf.converted_amount,  # negative Decimal for debit
                    kind=FlowKind.RESERVED_PENDING_DEBIT,
                    label=f"reserved {nf.flow_id}: {nf.description}",
                )
            )

    # 4. Add admitted future explicit events (that were NOT reconciled into recurring stream).
    # Strictly exclude any flow that is pending-credit (S-16 / S-17): the resolver already
    # marks these as EXCLUDED_PENDING_CREDIT; we must respect that here rather than
    # re-admitting them through a narrower check.
    from .resolver import FlowAdmission as _FA  # already imported above, alias for clarity
    for nf in normalized_flows:
        if nf.admission != FlowAdmission.ADMITTED:
            continue  # covers EXCLUDED_PENDING_CREDIT and all other exclusions
        if nf.is_reserved_pending_debit:
            continue  # already handled in step 3
        if anchor_date <= nf.flow_date <= horizon_end:
            if nf.flow_id in reconciled_event_ids:
                continue  # already counted via reconciled recurring occurrence
            kind = FlowKind.CONFIRMED_INCOME if nf.direction == Direction.CREDIT else FlowKind.OTHER
            flows.append(
                CashFlow(
                    flow_date=nf.flow_date,
                    amount=nf.converted_amount,
                    kind=kind,
                    label=f"{nf.flow_id}: {nf.description}",
                )
            )

    # 5. Add recurring stream occurrences.
    # If a pending debit was already reserved in step 3, its stream's inferred recurring
    # occurrence on the same date must be suppressed to avoid double-counting.
    for occ in occurrences:
        if anchor_date <= occ.occurrence_date <= horizon_end:
            # Suppress projection if the occurrence reconciles to a pending debit that
            # was already reserved, or if the projected date matches an existing reserved
            # pending debit from the same stream category.
            if occ.reconciled_event_id in reserved_pending_ids:
                continue  # pending debit already reserved; don't also project it

            if occ.stream.direction == Direction.CREDIT:
                amt = occ.amount
                kind = FlowKind.CONFIRMED_INCOME
                # S-16: never project a CREDIT occurrence whose reconciled event is pending
                if occ.reconciled_event_id is not None:
                    # Check whether the reconciled event is still pending (excluded credit)
                    reconciled_evt = None
                    if dataset is not None:
                        reconciled_evt = dataset.events_by_id.get(occ.reconciled_event_id)
                    if reconciled_evt is not None and reconciled_evt.status == EventStatus.PENDING:
                        continue  # pending credit; excluded per S-16
            else:
                amt = -occ.amount
                kind = FlowKind.SETTLED_RECURRING_PROJECTION

            flows.append(
                CashFlow(
                    flow_date=occ.occurrence_date,
                    amount=amt,
                    kind=kind,
                    label=f"recurring {occ.stream.category.value}: {occ.stream.description}",
                )
            )

    # 6. Add conservative variable spending estimates (groceries, transport, dining)
    var_estimates = estimate_variable_spend(
        dataset,
        user_id,
        anchor_date=anchor_date,
        method=variable_spend_method,
        image_amounts=image_amounts,
    )

    # Distribute variable spend into weekly increments across the horizon
    # 90 days = ~13 weekly chunks. Each week: (monthly_estimate * 12) / 52
    for vest in var_estimates:
        if vest.monthly_estimate <= 0:
            continue
        weekly_chunk = ((vest.monthly_estimate * Decimal(12)) / Decimal(52)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        cur_d = anchor_date + timedelta(days=7)
        while cur_d <= horizon_end:
            flows.append(
                CashFlow(
                    flow_date=cur_d,
                    amount=-weekly_chunk,
                    kind=FlowKind.VARIABLE_SPEND_PROJECTION,
                    label=f"variable spend {vest.category.value}",
                )
            )
            cur_d += timedelta(days=7)

    # Sort flows chronologically
    flows.sort(key=lambda f: f.flow_date)
    return tuple(flows)


def forecast_headroom(
    dataset: Dataset,
    user_id: str,
    anchor_date: date,
    flows: tuple[CashFlow, ...] | None = None,
    *,
    evidence_facts: tuple[EvidenceFact, ...] = (),
    image_amounts: dict[str, Decimal] | None = None,
    variable_spend_method: str = "trailing_3_month_mean_floored_at_latest_month",
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> SimulationResult:
    """Run baseline simulation across [anchor_date, anchor_date + horizon_days] with
    opening_balance and minimum_balance_to_keep from financial_profiles.csv.
    """
    profile = dataset.profiles_by_user[user_id]
    if flows is None:
        flows = assemble_flows(
            dataset,
            user_id,
            anchor_date=anchor_date,
            evidence_facts=evidence_facts,
            image_amounts=image_amounts,
            variable_spend_method=variable_spend_method,
            horizon_days=horizon_days,
        )

    return simulate(
        opening_balance=profile.current_available_balance,
        minimum_balance_to_keep=profile.minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=flows,
        schedule=(),
        horizon_days=horizon_days,
    )


def calculate_binding_headroom(sim_result: SimulationResult) -> tuple[Decimal, date]:
    """Extract minimum headroom H_min = min_t (floor_check_balance(t) - minimum_balance_to_keep)
    and the earliest date that achieves it (the binding date).
    """
    min_bal = sim_result.minimum_balance_to_keep
    if not sim_result.daily_balances:
        return (sim_result.opening_balance - min_bal, sim_result.anchor_date)

    # Headroom on day t is floor_check_balance - min_bal
    # We also check start-of-day before day 1 movements
    worst_headroom = sim_result.opening_balance - min_bal
    binding_date = sim_result.anchor_date

    for db in sim_result.daily_balances:
        headroom = db.floor_check_balance - min_bal
        if headroom < worst_headroom:
            worst_headroom = headroom
            binding_date = db.day

    return (worst_headroom, binding_date)


def calculate_amount_safe_to_pay(sim_result: SimulationResult, requested_amount: Decimal) -> Decimal:
    """S-03: Largest amount safe on request_date before optional spending changes,
    capped at requested_amount.
    """
    headroom, _ = calculate_binding_headroom(sim_result)
    return max(Decimal(0), min(headroom, requested_amount))


def calculate_earliest_full_payment_date(
    dataset: Dataset,
    user_id: str,
    anchor_date: date,
    requested_amount: Decimal,
    flows: tuple[CashFlow, ...] | None = None,
    *,
    evidence_facts: tuple[EvidenceFact, ...] = (),
    image_amounts: dict[str, Decimal] | None = None,
    variable_spend_method: str = "trailing_3_month_mean_floored_at_latest_month",
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> date | None:
    """S-06: First date the full requested_amount passes the safety check without
    optional spending changes. Equals anchor_date if safe today; empty (None) if
    never safe within the 90-day window.
    """
    profile = dataset.profiles_by_user[user_id]
    if flows is None:
        flows = assemble_flows(
            dataset,
            user_id,
            anchor_date=anchor_date,
            evidence_facts=evidence_facts,
            image_amounts=image_amounts,
            variable_spend_method=variable_spend_method,
            horizon_days=horizon_days,
        )

    # 1. Test today (anchor_date)
    res_today = simulate(
        opening_balance=profile.current_available_balance,
        minimum_balance_to_keep=profile.minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=flows,
        schedule=[ScheduledPayment(payment_date=anchor_date, amount=requested_amount)],
        horizon_days=horizon_days,
    )
    if res_today.is_safe:
        return anchor_date

    # 2. Test subsequent days where cash improvements occur (e.g. credit dates) or day by day
    # Testing all active credit days and their day-afters first
    credit_dates = sorted({f.flow_date for f in flows if f.amount > 0 and f.flow_date > anchor_date})
    candidate_dates = set(credit_dates)
    # Also include all dates in the window to be exhaustive
    for i in range(1, horizon_days + 1):
        candidate_dates.add(anchor_date + timedelta(days=i))

    for cand_date in sorted(candidate_dates):
        res = simulate(
            opening_balance=profile.current_available_balance,
            minimum_balance_to_keep=profile.minimum_balance_to_keep,
            anchor_date=anchor_date,
            flows=flows,
            schedule=[ScheduledPayment(payment_date=cand_date, amount=requested_amount)],
            horizon_days=horizon_days,
        )
        if res.is_safe:
            return cand_date

    return None
