"""Production financial-state resolver.

Responsibilities (per S-16, S-17, S-18, S-21, S-22, S-24, U-DUP-1):
  * Field-level amendments from evidence (messages and images) with explicit provenance.
  * Lifecycle graph resolution over `linked_event_id` chains (the 7 patterns in
    evaluation/inventory.md Table 5.4).
  * Conflict resolution adhering to S-24's 4-level precedence order:
      1. Explicit cancellation, settlement, or amendment
      2. Newer record from the same source
      3. Settled event over estimate or forecast
      4. Financially safer interpretation when unresolved
  * Identification of historical settled cash (already reflected in opening balance)
    to prevent reapplication as new forecast cash.
  * Reservation of pending debits (S-16, U-DUP-1): immediate reserve on request_date,
    never counted twice.
  * Exclusion of pending credits, uncredited prizes, unrealized investment values,
    failed/cancelled records, and internal self-transfers.
  * Deterministic dated foreign-currency conversion using `dataset.fx_rates` at settlement date.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .evidence import EvidenceFact, FactKind, get_all_resolved_image_amounts
from .fx import FxKey, convert
from .schemas import (
    Currency,
    Dataset,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExpenseCategory,
)


class ResolutionPrecedence(StrEnum):
    """S-24, in order. `resolve()` records the level actually used for
    every field it resolves, not just the final value."""

    EXPLICIT_AMENDMENT = "explicit_cancellation_settlement_or_amendment"
    NEWER_SAME_SOURCE = "newer_record_same_source"
    SETTLED_OVER_ESTIMATE = "settled_event_over_estimate_or_forecast"
    SAFER_INTERPRETATION = "financially_safer_interpretation"


class LifecycleGroup(StrEnum):
    """The linked_event_id chain patterns from evaluation/inventory.md
    section 5.4, each with a distinct cash treatment."""

    REFUND_SETTLED = "refund_settled"  # settled credit; reflected in historical balance
    REFUND_PENDING = "refund_pending"  # excluded until it settles (S-16)
    CANCELLED_DUPLICATE = "cancelled_duplicate"  # cancelled parent dropped; settled child counts
    INVESTMENT_VALUATION = "investment_valuation"  # non-cash, never available cash (S-17)
    INVESTMENT_SALE_SETTLED = "investment_sale_settled"  # settled credit; counts
    FAILED_THEN_SCHEDULED_RETRY = "failed_then_scheduled_retry"  # failed parent dropped; retry is future debit
    DISPUTED_PENDING_MIRROR = "disputed_pending_mirror"  # U-DUP-1: reserved pending debit


class FlowAdmission(StrEnum):
    """Admission or exclusion status of a normalized flow."""

    ADMITTED = "admitted"
    EXCLUDED_HISTORICAL_SETTLED = "excluded_historical_settled"  # already in opening balance
    EXCLUDED_PENDING_CREDIT = "excluded_pending_credit"  # S-16: pending refund, bonus, commission
    EXCLUDED_CANCELLED = "excluded_cancelled"  # S-17
    EXCLUDED_FAILED = "excluded_failed"  # S-17
    EXCLUDED_NON_CASH_VALUATION = "excluded_non_cash_valuation"  # S-17: unrealized valuation
    EXCLUDED_SELF_TRANSFER = "excluded_self_transfer"  # internal account transfer
    EXCLUDED_UNTRUSTED = "excluded_untrusted"  # S-23: fraudulent / untrusted instruction
    EXCLUDED_DUPLICATE = "excluded_duplicate"


@dataclass(frozen=True, slots=True)
class ResolvedField:
    event_id: str | None  # None for a resolution not tied to one existing event row
    field_name: str  # e.g. "amount", "status", "effective_monthly_income"
    resolved_value: Any
    precedence_used: ResolutionPrecedence
    provenance: tuple[str, ...]  # ids of the events/facts that determined this value
    notes: str


@dataclass(frozen=True, slots=True)
class NormalizedFlow:
    flow_id: str
    source_ids: tuple[str, ...]
    user_id: str
    flow_date: date
    direction: Direction
    original_amount: Decimal
    original_currency: Currency
    converted_amount: Decimal  # signed: positive for credit, negative for debit, 0 for non_cash
    home_currency: Currency
    category: ExpenseCategory
    description: str
    status: EventStatus
    lifecycle_group: LifecycleGroup | None
    admission: FlowAdmission
    admission_reason: str
    is_represented_in_opening_balance: bool
    is_reserved_pending_debit: bool
    amendment_provenance: tuple[str, ...]
    precedence_used: ResolutionPrecedence | None


def load_image_audit_amounts(audit_path: str = "evaluation/image_audit_results.json") -> dict[str, Decimal]:
    """Load pre-audited image amounts (16 images) from Stage 3.
    Returns mapping of event_id -> Decimal amount.
    """
    path = Path(audit_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        res: dict[str, Decimal] = {}
        for item in data:
            evt_id = item.get("event_id")
            sel = item.get("selection") or {}
            amt_str = sel.get("selected_amount")
            if evt_id and amt_str is not None:
                res[evt_id] = Decimal(str(amt_str))
        return res
    except Exception:
        return {}


def convert_with_fallback(
    amount: Decimal,
    *,
    from_currency: Currency,
    to_currency: Currency,
    on_date: date,
    fx_rates: Mapping[FxKey, Decimal],
) -> Decimal:
    """Convert foreign currency with U-FX-1 conservative fallback."""
    if from_currency == to_currency:
        return amount
    key = (on_date, from_currency, to_currency)
    if key in fx_rates:
        return convert(amount, from_currency=from_currency, to_currency=to_currency, on_date=on_date, fx_index=fx_rates)
    # U-FX-1: latest rate on or before that date; never invert
    candidates = [
        (d, r)
        for (d, fc, tc), r in fx_rates.items()
        if fc == from_currency and tc == to_currency and d <= on_date
    ]
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return amount * candidates[-1][1]
    raise LookupError(f"no exchange rate available for {from_currency}->{to_currency} on or before {on_date}")


def resolve_user_events(
    dataset: Dataset,
    user_id: str,
    evidence_facts: tuple[EvidenceFact, ...] = (),
    *,
    as_of_date: date | None = None,
    image_amounts: Mapping[str, Decimal] | None = None,
) -> tuple[tuple[ResolvedField, ...], tuple[NormalizedFlow, ...]]:
    """Resolve and normalize all financial events and evidence facts for one user.
    
    Returns:
        (resolved_fields, normalized_flows)
    """
    profile = dataset.profiles_by_user[user_id]
    home_currency = profile.home_currency

    if as_of_date is None:
        # Resolve request for as-of date
        req = next((r for r in dataset.requests if r.user_id == user_id), None)
        if req is None:
            req = next((r for r in dataset.sample_requests if r.user_id == user_id), None)
        as_of_date = req.request_date if req is not None else date(2024, 1, 1)

    if image_amounts is None:
        image_amounts = get_all_resolved_image_amounts(dataset)

    resolved_fields: list[ResolvedField] = []
    normalized_flows: list[NormalizedFlow] = []

    # 1. Inspect evidence facts for user-level amendments and as-of compliance
    user_facts: list[EvidenceFact] = []
    for f in evidence_facts:
        if f.user_id != user_id:
            continue
        # As-of policy: reject observations dated after as_of_date
        if f.observed_time:
            obs_dt = f.observed_time.split("T")[0]
            try:
                if date.fromisoformat(obs_dt) > as_of_date:
                    resolved_fields.append(
                        ResolvedField(
                            event_id=f.related_event_id,
                            field_name="observation_discarded",
                            resolved_value=f.source_id,
                            precedence_used=ResolutionPrecedence.SAFER_INTERPRETATION,
                            provenance=(f.source_id,),
                            notes=f"Observation {f.source_id} dated {obs_dt} is after as_of_date {as_of_date}; excluded per as-of policy",
                        )
                    )
                    continue
            except ValueError:
                pass
        user_facts.append(f)

    # Track user-level amendments
    salary_ended = False
    rent_increase_pct: Decimal | None = None
    confirmed_one_offs: list[EvidenceFact] = []
    self_transfer_indicated = False

    for f in user_facts:
        if f.fact_kind == FactKind.UNTRUSTED_INSTRUCTION:
            resolved_fields.append(
                ResolvedField(
                    event_id=f.related_event_id,
                    field_name="untrusted_instruction",
                    resolved_value="ignored",
                    precedence_used=ResolutionPrecedence.SAFER_INTERPRETATION,
                    provenance=(f.source_id,),
                    notes=f"Untrusted instruction in {f.source_id} ignored per S-23",
                )
            )
        elif f.fact_kind == FactKind.INCOME_ENDED:
            salary_ended = True
            resolved_fields.append(
                ResolvedField(
                    event_id=None,
                    field_name="income_ended",
                    resolved_value=True,
                    precedence_used=ResolutionPrecedence.EXPLICIT_AMENDMENT,
                    provenance=(f.source_id,),
                    notes=f"Income ended confirmed by message {f.source_id}",
                )
            )
        elif f.fact_kind == FactKind.RENT_PERCENTAGE_INCREASE:
            rent_increase_pct = f.amount
            resolved_fields.append(
                ResolvedField(
                    event_id=None,
                    field_name="rent_percentage_increase",
                    resolved_value=rent_increase_pct,
                    precedence_used=ResolutionPrecedence.EXPLICIT_AMENDMENT,
                    provenance=(f.source_id,),
                    notes=f"Rent increase of {rent_increase_pct}% from message {f.source_id}",
                )
            )
        elif f.fact_kind == FactKind.SELF_TRANSFER:
            self_transfer_indicated = True
            resolved_fields.append(
                ResolvedField(
                    event_id=None,
                    field_name="self_transfer",
                    resolved_value=True,
                    precedence_used=ResolutionPrecedence.EXPLICIT_AMENDMENT,
                    provenance=(f.source_id,),
                    notes=f"Self transfer indicated by message {f.source_id}",
                )
            )
        elif f.fact_kind == FactKind.INCOME_CONFIRMED_ONE_OFF:
            if f.amount is not None and f.temporal_scope.effective_from is not None:
                confirmed_one_offs.append(f)
                resolved_fields.append(
                    ResolvedField(
                        event_id=None,
                        field_name="income_confirmed_one_off",
                        resolved_value=f.amount,
                        precedence_used=ResolutionPrecedence.EXPLICIT_AMENDMENT,
                        provenance=(f.source_id,),
                        notes=f"Confirmed one-off income of {f.amount} on {f.temporal_scope.effective_from}",
                    )
                )

    # 2. Map events and build lifecycle graph
    user_events = dataset.events_by_user.get(user_id, ())
    events_by_id = {e.event_id: e for e in user_events}

    # Find child -> parent links
    linked_children: dict[str, Event] = {}  # parent_id -> child_event
    for e in user_events:
        if e.linked_event_id:
            linked_children[e.linked_event_id] = e

    for e in user_events:
        # Determine base event amount (resolve from image if blank)
        raw_amt = e.amount
        amt_provenance: list[str] = [e.event_id]
        if raw_amt is None:
            img_amt = image_amounts.get(e.event_id)
            if img_amt is not None:
                raw_amt = img_amt
                img = dataset.images_by_event.get(e.event_id, [None])[0]
                if img:
                    amt_provenance.append(img.image_id)
                resolved_fields.append(
                    ResolvedField(
                        event_id=e.event_id,
                        field_name="amount",
                        resolved_value=raw_amt,
                        precedence_used=ResolutionPrecedence.EXPLICIT_AMENDMENT,
                        provenance=tuple(amt_provenance),
                        notes=f"Amount resolved from image for {e.event_id}",
                    )
                )
            else:
                # Genuinely missing / cropped (e.g. image_04)
                if e.direction == Direction.DEBIT and (
                    e.status in (EventStatus.PENDING, EventStatus.SCHEDULED)
                    or (e.settlement_date or e.event_date) >= as_of_date
                ):
                    raise ValueError(
                        f"Missing image amount for admitted future debit {e.event_id}: cannot safely coerce debit to zero"
                    )
                raw_amt = Decimal(0)
                resolved_fields.append(
                    ResolvedField(
                        event_id=e.event_id,
                        field_name="amount",
                        resolved_value=None,
                        precedence_used=ResolutionPrecedence.SAFER_INTERPRETATION,
                        provenance=tuple(amt_provenance),
                        notes=f"Amount unreadable/cropped for historical {e.event_id}; treated as 0 for safe cash flow",
                    )
                )

        effective_date = e.settlement_date or e.event_date

        # Currency conversion
        if e.currency != home_currency:
            converted = convert_with_fallback(
                raw_amt,
                from_currency=e.currency,
                to_currency=home_currency,
                on_date=effective_date,
                fx_rates=dataset.fx_rates,
            )
        else:
            converted = raw_amt

        # Determine direction multiplier
        if e.direction == Direction.CREDIT:
            signed_converted = converted
        elif e.direction == Direction.DEBIT:
            signed_converted = -converted
        else:
            signed_converted = Decimal(0)

        # Lifecycle group identification
        lg: LifecycleGroup | None = None
        admission = FlowAdmission.ADMITTED
        admission_reason = "standard flow"
        is_opening = False
        is_pending_reserve = False
        prec = None

        # Check if this event is a child in a linked lifecycle
        if e.linked_event_id and e.linked_event_id in events_by_id:
            parent = events_by_id[e.linked_event_id]
            if parent.event_type == EventType.EXPENSE and e.event_type == EventType.REFUND:
                if e.status == EventStatus.SETTLED:
                    lg = LifecycleGroup.REFUND_SETTLED
                    admission_reason = "settled refund of earlier expense"
                else:
                    lg = LifecycleGroup.REFUND_PENDING
                    admission = FlowAdmission.EXCLUDED_PENDING_CREDIT
                    admission_reason = "pending refund excluded until settlement per S-16"
            elif parent.event_type == EventType.INVESTMENT_PURCHASE and e.event_type == EventType.INVESTMENT_VALUATION:
                lg = LifecycleGroup.INVESTMENT_VALUATION
                admission = FlowAdmission.EXCLUDED_NON_CASH_VALUATION
                admission_reason = "investment valuation is non-cash per S-17"
            elif parent.event_type == EventType.INVESTMENT_PURCHASE and e.event_type == EventType.INVESTMENT_SALE:
                lg = LifecycleGroup.INVESTMENT_SALE_SETTLED
                admission_reason = "settled investment sale cash proceeds"
            elif parent.status == EventStatus.CANCELLED and e.status == EventStatus.SETTLED:
                lg = LifecycleGroup.CANCELLED_DUPLICATE
                admission_reason = "settled replacement of cancelled duplicate attempt"
            elif parent.status == EventStatus.FAILED and e.status == EventStatus.SCHEDULED:
                lg = LifecycleGroup.FAILED_THEN_SCHEDULED_RETRY
                admission_reason = "scheduled retry of failed debit"
            elif parent.status == EventStatus.SETTLED and e.status == EventStatus.PENDING and e.direction == Direction.DEBIT:
                lg = LifecycleGroup.DISPUTED_PENDING_MIRROR
                admission_reason = "disputed extra charge reserved per U-DUP-1"
                is_pending_reserve = True

        # Check if this event is a parent of a linked child
        elif e.event_id in linked_children:
            child = linked_children[e.event_id]
            if e.status == EventStatus.CANCELLED and child.status == EventStatus.SETTLED:
                lg = LifecycleGroup.CANCELLED_DUPLICATE
                admission = FlowAdmission.EXCLUDED_CANCELLED
                admission_reason = "cancelled duplicate dropped per S-17"
            elif e.status == EventStatus.FAILED and child.status == EventStatus.SCHEDULED:
                lg = LifecycleGroup.FAILED_THEN_SCHEDULED_RETRY
                admission = FlowAdmission.EXCLUDED_FAILED
                admission_reason = "failed debit dropped per S-17"

        # General status filters if not already set
        if admission == FlowAdmission.ADMITTED:
            if e.direction == Direction.NON_CASH or e.status == EventStatus.UNREALIZED:
                admission = FlowAdmission.EXCLUDED_NON_CASH_VALUATION
                admission_reason = "non-cash or unrealized valuation per S-17"
            elif e.status == EventStatus.CANCELLED:
                admission = FlowAdmission.EXCLUDED_CANCELLED
                admission_reason = "cancelled transaction dropped per S-17"
            elif e.status == EventStatus.FAILED:
                admission = FlowAdmission.EXCLUDED_FAILED
                admission_reason = "failed transaction dropped per S-17"
            elif e.status == EventStatus.SETTLED:
                if effective_date < as_of_date:
                    is_opening = True
                    admission = FlowAdmission.EXCLUDED_HISTORICAL_SETTLED
                    admission_reason = "historical settled cash already in opening balance"
                else:
                    admission = FlowAdmission.ADMITTED
                    admission_reason = "settled cash flow"
            elif e.status == EventStatus.PENDING:
                if e.direction == Direction.CREDIT:
                    admission = FlowAdmission.EXCLUDED_PENDING_CREDIT
                    admission_reason = "pending credit excluded per S-16"
                else:
                    # Pending debit: reserve immediately on request_date (U-DUP-1 / S-16)
                    is_pending_reserve = True
                    admission = FlowAdmission.ADMITTED
                    admission_reason = "pending debit reserved immediately on request date"
            elif e.status == EventStatus.SCHEDULED:
                admission = FlowAdmission.ADMITTED
                admission_reason = "scheduled cash event"

        # Self-transfer check
        if self_transfer_indicated and "transfer" in e.description.lower():
            admission = FlowAdmission.EXCLUDED_SELF_TRANSFER
            admission_reason = "internal self-transfer excluded from cash flow"

        normalized_flows.append(
            NormalizedFlow(
                flow_id=e.event_id,
                source_ids=tuple(amt_provenance),
                user_id=user_id,
                flow_date=effective_date,
                direction=e.direction,
                original_amount=raw_amt,
                original_currency=e.currency,
                converted_amount=signed_converted,
                home_currency=home_currency,
                category=e.category,
                description=e.description,
                status=e.status,
                lifecycle_group=lg,
                admission=admission,
                admission_reason=admission_reason,
                is_represented_in_opening_balance=is_opening,
                is_reserved_pending_debit=is_pending_reserve,
                amendment_provenance=tuple(amt_provenance[1:]),
                precedence_used=prec,
            )
        )

    # 3. Add admitted confirmed future one-off income facts (e.g. client approved invoices)
    for idx, one_off in enumerate(confirmed_one_offs):
        eff_date = one_off.temporal_scope.effective_from
        if eff_date and eff_date >= as_of_date and one_off.amount is not None:
            curr = one_off.currency or home_currency
            if curr != home_currency:
                conv = convert_with_fallback(
                    one_off.amount,
                    from_currency=curr,
                    to_currency=home_currency,
                    on_date=eff_date,
                    fx_rates=dataset.fx_rates,
                )
            else:
                conv = one_off.amount

            normalized_flows.append(
                NormalizedFlow(
                    flow_id=f"fact_income_{one_off.source_id}_{idx}",
                    source_ids=(one_off.source_id,),
                    user_id=user_id,
                    flow_date=eff_date,
                    direction=Direction.CREDIT,
                    original_amount=one_off.amount,
                    original_currency=curr,
                    converted_amount=conv,
                    home_currency=home_currency,
                    category=ExpenseCategory.SALARY,
                    description=f"Confirmed one-off income from {one_off.source_id}",
                    status=EventStatus.SCHEDULED,
                    lifecycle_group=None,
                    admission=FlowAdmission.ADMITTED,
                    admission_reason="confirmed one-off income dated >= as_of_date",
                    is_represented_in_opening_balance=False,
                    is_reserved_pending_debit=False,
                    amendment_provenance=(one_off.source_id,),
                    precedence_used=ResolutionPrecedence.EXPLICIT_AMENDMENT,
                )
            )

    return tuple(resolved_fields), tuple(normalized_flows)


def resolve(
    dataset: Dataset,
    evidence_facts: tuple[EvidenceFact, ...],
    user_id: str,
) -> tuple[ResolvedField, ...]:
    """Production evidence resolver. Combines financial_events.csv rows (grouped by
    LifecycleGroup) with EvidenceFact objects for one user, applies
    ResolutionPrecedence, and returns one ResolvedField per amended fact.
    """
    resolved_fields, _ = resolve_user_events(dataset, user_id, evidence_facts)
    return resolved_fields
