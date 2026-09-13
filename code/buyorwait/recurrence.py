"""Production recurrence detection and variable spending estimation.

Responsibilities (per S-11, S-12, S-18, S-19, S-20, U-FORECAST-1, U-INCOME-1, U-INCOME-2, U-RENT-1):
  * Distinguish calendar-month schedules (e.g. 15th of each month) from fixed-day
    intervals (7, 14, 21, 28, 30, 31 days).
  * Group changing descriptions when records support a shared spending stream
    (normalizing away dynamic invoice/transaction numbers) while preserving
    distinct counterparties and obligations.
  * Reconcile explicit supplied future occurrences against inferred occurrences
    to prevent double counting.
  * Integrate evidence facts (salary increases/reductions, date changes, contract endings,
    rent percentage increases) into stream projections.
  * Forecast essential variable expenses conservatively (groceries, transport, dining)
    comparing a declared set of robust estimators over trailing complete months.
  * Explicitly separate supported recurring streams from insufficient-history streams.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Sequence

from .evidence import EvidenceFact, FactKind
from .fx import convert
from .resolver import convert_with_fallback
from .schemas import (
    Currency,
    Dataset,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExpenseCategory,
)


class RecurrenceConfidence(StrEnum):
    SUPPORTED = "supported"  # enough consistent history to project forward
    INSUFFICIENT_HISTORY = "insufficient_history"  # too thin or erratic to project (S-19)


class RecurrenceScheduleType(StrEnum):
    CALENDAR_MONTH = "calendar_month"  # repeats on the same day of each month
    FIXED_INTERVAL = "fixed_interval"  # repeats every N days (e.g. 7, 14, 28, 30, 31)


@dataclass(frozen=True, slots=True)
class RecurringStream:
    user_id: str
    category: ExpenseCategory
    description: str  # normalized stream description
    typical_amount: Decimal  # in user's home currency
    currency: Currency
    schedule_type: RecurrenceScheduleType
    day_of_month: int | None  # 1-31 for calendar_month
    interval_days: int | None  # N for fixed_interval
    direction: Direction
    confidence: RecurrenceConfidence
    supporting_event_ids: tuple[str, ...]
    provenance_notes: str = ""
    last_observed_date: date | None = None


@dataclass(frozen=True, slots=True)
class ScheduledOccurrence:
    stream: RecurringStream
    occurrence_date: date
    amount: Decimal  # in user's home currency
    is_explicit_event: bool = False
    reconciled_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class VariableSpendEstimate:
    user_id: str
    category: ExpenseCategory
    monthly_estimate: Decimal  # in user's home currency
    method: str
    supporting_event_ids: tuple[str, ...]


# Essential variable categories requiring aggregate forecasting
VARIABLE_CATEGORIES = {
    ExpenseCategory.GROCERIES,
    ExpenseCategory.TRANSPORT,
    ExpenseCategory.DINING,
}

# Categories that represent anchored recurring commitments
ANCHORED_CATEGORIES = {
    ExpenseCategory.SALARY,
    ExpenseCategory.RENT,
    ExpenseCategory.UTILITIES,
    ExpenseCategory.INSURANCE,
    ExpenseCategory.STREAMING,
    ExpenseCategory.CLOUD_STORAGE,
    ExpenseCategory.MUSIC_SUBSCRIPTION,
    ExpenseCategory.DELIVERY_MEMBERSHIP,
    ExpenseCategory.GYM,
    ExpenseCategory.DEBT_REPAYMENT,
    ExpenseCategory.HOUSING,
    ExpenseCategory.FAMILY_SUPPORT,
    ExpenseCategory.EDUCATION,
}


def normalize_stream_description(desc: str) -> str:
    """Normalize a description to its underlying stream identity.
    Strips dynamic transaction references, invoice IDs, account hashes,
    and month/year references while preserving distinct counterparties.
    """
    # Remove references like INV-2024-001, #12345, Ref EMP-0001, Txn BAN-0123, Acct #9912
    cleaned = re.sub(r"(?i)(?:\b(?:inv|ref|txn|acct|bill|order)|#)[-:\s#]*[\w-]+", "", desc)
    # Remove year-month numbers like 2024-05, 2025/08, 08/2025 or standalone 4-digit years
    cleaned = re.sub(r"\b\d{4}[-/]\d{1,2}\b", "", cleaned)
    cleaned = re.sub(r"\b\d{1,2}[-/]\d{4}\b", "", cleaned)
    cleaned = re.sub(r"\b(?:19|20)\d{2}\b", "", cleaned)
    # Remove English and Indonesian month names
    cleaned = re.sub(
        r"(?i)\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)\b",
        "",
        cleaned,
    )
    # Remove empty parentheses/brackets
    cleaned = re.sub(r"\(\s*\)|\[\s*\]", "", cleaned)
    # Collapse multiple spaces and trim
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:,#")
    return cleaned or desc.strip()


def detect_recurring_streams(
    dataset: Dataset,
    user_id: str,
    evidence_facts: tuple[EvidenceFact, ...] = (),
    *,
    as_of_date: date | None = None,
    image_amounts: Mapping[str, Decimal] | None = None,
) -> tuple[RecurringStream, ...]:
    """Detect supported recurring streams from historical settled events for one user,
    incorporating any evidence fact amendments.
    """
    profile = dataset.profiles_by_user[user_id]
    home_currency = profile.home_currency

    if as_of_date is None:
        req = next((r for r in dataset.requests if r.user_id == user_id), None)
        if req is None:
            req = next((r for r in dataset.sample_requests if r.user_id == user_id), None)
        as_of_date = req.request_date if req is not None else date(2024, 1, 1)

    # Check evidence facts for salary or rent amendments
    salary_ended = False
    salary_amount_amendment: Decimal | None = None
    salary_date_amendment: int | None = None
    rent_increase_pct: Decimal | None = None

    all_events = dataset.events_by_user.get(user_id, ())
    # Check if user had a final employer payroll record without subsequent new salary
    final_payroll_dates = [
        (e.settlement_date or e.event_date) for e in all_events
        if e.category == ExpenseCategory.SALARY
        and any(w in e.description.lower() for w in ("final employer payroll", "final payroll", "severance", "terminal payroll"))
        and (e.settlement_date or e.event_date) <= as_of_date
    ]
    if final_payroll_dates:
        max_final = max(final_payroll_dates)
        has_newer = any(
            e.category == ExpenseCategory.SALARY
            and (e.settlement_date or e.event_date) > max_final
            and (e.settlement_date or e.event_date) <= as_of_date
            and not any(w in e.description.lower() for w in ("final", "severance"))
            for e in all_events
        )
        if not has_newer:
            salary_ended = True

    for f in evidence_facts:
        if f.user_id != user_id:
            continue
        if f.fact_kind == FactKind.INCOME_ENDED:
            salary_ended = True
        elif f.fact_kind == FactKind.INCOME_AMOUNT_CHANGE and f.amount is not None:
            # If foreign currency, convert at latest rate on or before as_of_date
            if f.currency and f.currency != home_currency:
                try:
                    salary_amount_amendment = convert_with_fallback(
                        f.amount,
                        from_currency=f.currency,
                        to_currency=home_currency,
                        on_date=as_of_date,
                        fx_rates=dataset.fx_rates,
                    )
                except LookupError:
                    salary_amount_amendment = f.amount
            else:
                salary_amount_amendment = f.amount
        elif f.fact_kind == FactKind.INCOME_DATE_CHANGE and f.temporal_scope.effective_from:
            salary_date_amendment = f.temporal_scope.effective_from.day
        elif f.fact_kind == FactKind.RENT_PERCENTAGE_INCREASE and f.amount is not None:
            rent_increase_pct = f.amount

    # Collect settled historical events
    historical = [
        e for e in all_events
        if e.status == EventStatus.SETTLED
        and (e.settlement_date or e.event_date) <= as_of_date
        and e.category not in VARIABLE_CATEGORIES
        and e.direction != Direction.NON_CASH
    ]

    # Group by stream identity: (category, normalized_description, direction)
    groups: dict[tuple[ExpenseCategory, str, Direction], list[Event]] = {}
    for e in historical:
        norm_desc = normalize_stream_description(e.description)
        key = (e.category, norm_desc, e.direction)
        groups.setdefault(key, []).append(e)

    streams: list[RecurringStream] = []

    user_facts = [f for f in evidence_facts if f.user_id == user_id]
    has_unconfirmed = any(f.fact_kind == FactKind.INCOME_NOT_YET_CONFIRMED for f in user_facts)

    for (cat, norm_desc, direction), evts in groups.items():
        # S-16: Exclude contingent credits (commissions, bonuses, reimbursements, arrears, unconfirmed payouts)
        is_contingent = any(w in norm_desc.lower() for w in ("commission", "bonus", "incentive", "reimbursement", "arrears"))
        is_unconfirmed_gig = has_unconfirmed and any(w in norm_desc.lower() for w in ("platform payout", "app earnings", "marketplace payout"))
        if direction == Direction.CREDIT and (is_contingent or is_unconfirmed_gig):
            first_amt = (image_amounts.get(evts[0].event_id, evts[0].amount) if image_amounts else evts[0].amount) or Decimal(0)
            streams.append(
                RecurringStream(
                    user_id=user_id,
                    category=cat,
                    description=norm_desc,
                    typical_amount=first_amt,
                    currency=home_currency,
                    schedule_type=RecurrenceScheduleType.CALENDAR_MONTH,
                    day_of_month=(evts[0].settlement_date or evts[0].event_date).day,
                    interval_days=None,
                    direction=direction,
                    confidence=RecurrenceConfidence.INSUFFICIENT_HISTORY,
                    supporting_event_ids=tuple(e.event_id for e in evts),
                    provenance_notes="contingent commission/bonus excluded from recurring projection under S-16",
                    last_observed_date=max((e.settlement_date or e.event_date) for e in evts),
                )
            )
            continue

        # Exclude non-recurring or one-off events
        if len(evts) < 2:
            # Less than 2 occurrences -> insufficient history (S-19)
            first_amt = (image_amounts.get(evts[0].event_id, evts[0].amount) if image_amounts else evts[0].amount) or Decimal(0)
            streams.append(
                RecurringStream(
                    user_id=user_id,
                    category=cat,
                    description=norm_desc,
                    typical_amount=first_amt,
                    currency=home_currency,
                    schedule_type=RecurrenceScheduleType.CALENDAR_MONTH,
                    day_of_month=(evts[0].settlement_date or evts[0].event_date).day,
                    interval_days=None,
                    direction=direction,
                    confidence=RecurrenceConfidence.INSUFFICIENT_HISTORY,
                    supporting_event_ids=tuple(e.event_id for e in evts),
                    provenance_notes="insufficient occurrences to establish recurrence (< 2)",
                    last_observed_date=max((e.settlement_date or e.event_date) for e in evts),
                )
            )
            continue

        # Sort chronologically
        evts_sorted = sorted(evts, key=lambda e: e.settlement_date or e.event_date)
        dates = [e.settlement_date or e.event_date for e in evts_sorted]
        last_obs = max(dates) if dates else None
        amounts = []
        for e in evts_sorted:
            eff_dt = e.settlement_date or e.event_date
            raw = (image_amounts.get(e.event_id, e.amount) if image_amounts else e.amount) or Decimal(0)
            if e.currency != home_currency:
                try:
                    converted = convert_with_fallback(
                        raw,
                        from_currency=e.currency,
                        to_currency=home_currency,
                        on_date=eff_dt,
                        fx_rates=dataset.fx_rates,
                    )
                except LookupError:
                    converted = raw
                amounts.append(converted)
            else:
                amounts.append(raw)

        # Calculate intervals
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
        days_of_month = [d.day for d in dates]

        # Determine if calendar_month:
        # Check if day of month is consistent (e.g. max - min <= 4 or mode frequency >= 50%)
        mode_day = max(set(days_of_month), key=days_of_month.count)
        day_spread = max(days_of_month) - min(days_of_month)
        median_interval = sorted(intervals)[len(intervals) // 2]

        is_calendar_month = (27 <= median_interval <= 33) and (day_spread <= 4 or days_of_month.count(mode_day) >= len(days_of_month) / 2)
        
        schedule_type = RecurrenceScheduleType.CALENDAR_MONTH if is_calendar_month else RecurrenceScheduleType.FIXED_INTERVAL
        dom = mode_day if is_calendar_month else None
        int_days = median_interval if not is_calendar_month else None

        # Typical amount: median of historical amounts
        median_amt = sorted(amounts)[len(amounts) // 2]

        # Apply amendments
        notes = "detected from historical settled events"
        if cat == ExpenseCategory.SALARY and direction == Direction.CREDIT:
            if salary_ended:
                # Do not project salary if employment ended
                streams.append(
                    RecurringStream(
                        user_id=user_id,
                        category=cat,
                        description=norm_desc,
                        typical_amount=median_amt,
                        currency=home_currency,
                        schedule_type=schedule_type,
                        day_of_month=dom,
                        interval_days=int_days,
                        direction=direction,
                        confidence=RecurrenceConfidence.INSUFFICIENT_HISTORY,
                        supporting_event_ids=tuple(e.event_id for e in evts_sorted),
                        provenance_notes="salary ended per message evidence",
                        last_observed_date=last_obs,
                    )
                )
                continue
            if salary_amount_amendment is not None:
                median_amt = salary_amount_amendment
                notes += f"; amount amended to {median_amt} from evidence"
            if salary_date_amendment is not None:
                dom = salary_date_amendment
                notes += f"; salary day amended to {dom} from evidence"

        elif cat == ExpenseCategory.RENT:
            if rent_increase_pct is not None:
                multiplier = Decimal(1) + (rent_increase_pct / Decimal(100))
                median_amt = (median_amt * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                notes += f"; rent increased by {rent_increase_pct}% to {median_amt}"

        streams.append(
            RecurringStream(
                user_id=user_id,
                category=cat,
                description=norm_desc,
                typical_amount=median_amt,
                currency=home_currency,
                schedule_type=schedule_type,
                day_of_month=dom,
                interval_days=int_days,
                direction=direction,
                confidence=RecurrenceConfidence.SUPPORTED,
                supporting_event_ids=tuple(e.event_id for e in evts_sorted),
                provenance_notes=notes,
                last_observed_date=last_obs,
            )
        )

    # Check if a scheduled salary event establishes the recurring salary stream
    has_supported_salary = any(
        s.category == ExpenseCategory.SALARY and s.confidence == RecurrenceConfidence.SUPPORTED
        for s in streams
    )
    if not has_supported_salary and not salary_ended:
        sched_salary = [
            e for e in all_events
            if e.category == ExpenseCategory.SALARY
            and e.status in (EventStatus.SCHEDULED, EventStatus.PENDING)
            and (e.settlement_date or e.event_date) >= as_of_date
            and not any(w in e.description.lower() for w in ("commission", "bonus", "reimbursement"))
        ]
        if sched_salary:
            sched_salary_sorted = sorted(sched_salary, key=lambda e: e.settlement_date or e.event_date)
            se = sched_salary_sorted[0]
            se_dt = se.settlement_date or se.event_date
            se_amt = (image_amounts.get(se.event_id, se.amount) if image_amounts else se.amount) or Decimal(0)
            if se.currency != home_currency:
                try:
                    se_amt = convert_with_fallback(
                        se_amt,
                        from_currency=se.currency,
                        to_currency=home_currency,
                        on_date=se_dt,
                        fx_rates=dataset.fx_rates,
                    )
                except LookupError:
                    pass

            se_dom = se_dt.day
            notes = "established from confirmed future scheduled salary event"
            if salary_amount_amendment is not None:
                se_amt = salary_amount_amendment
                notes += f"; amount amended to {se_amt} from evidence"
            if salary_date_amendment is not None:
                se_dom = salary_date_amendment
                notes += f"; salary day amended to {se_dom} from evidence"

            streams.append(
                RecurringStream(
                    user_id=user_id,
                    category=ExpenseCategory.SALARY,
                    description=normalize_stream_description(se.description),
                    typical_amount=se_amt,
                    currency=home_currency,
                    schedule_type=RecurrenceScheduleType.CALENDAR_MONTH,
                    day_of_month=se_dom,
                    interval_days=None,
                    direction=Direction.CREDIT,
                    confidence=RecurrenceConfidence.SUPPORTED,
                    supporting_event_ids=(se.event_id,),
                    provenance_notes=notes,
                    last_observed_date=se_dt,
                )
            )

    return tuple(streams)


def _matches_explicit_event(
    exp: Event,
    stream: RecurringStream,
    target_date: date,
    tolerance_days: int,
    reconciled_ids: set[str],
    all_streams: Sequence[RecurringStream],
) -> bool:
    if exp.event_id in reconciled_ids:
        return False
    if exp.category != stream.category or exp.direction != stream.direction:
        return False
    exp_dt = exp.settlement_date or exp.event_date
    if abs((exp_dt - target_date).days) > tolerance_days:
        return False
    # If this category/direction has only one supported stream, match directly
    cat_streams = [
        s for s in all_streams
        if s.category == stream.category and s.direction == stream.direction and s.confidence == RecurrenceConfidence.SUPPORTED
    ]
    if len(cat_streams) <= 1:
        return True
    # If multiple streams share category, require counterparty / token overlap
    exp_norm = normalize_stream_description(exp.description).lower()
    stream_norm = stream.description.lower()
    if exp_norm == stream_norm or exp_norm in stream_norm or stream_norm in exp_norm:
        return True
    exp_tokens = set(re.findall(r"\w+", exp_norm))
    stream_tokens = set(re.findall(r"\w+", stream_norm))
    meaningful = {t for t in (exp_tokens & stream_tokens) if len(t) > 2 and t not in ("the", "and", "plan", "monthly", "payment", "subscription")}
    return len(meaningful) > 0


def project_occurrences(
    streams: tuple[RecurringStream, ...],
    *,
    start: date,
    end: date,
    explicit_future_events: tuple[Event, ...] = (),
    home_currency: Currency | None = None,
    dataset: Dataset | None = None,
) -> tuple[ScheduledOccurrence, ...]:
    """Project supported RecurringStream objects onto [start, end].
    Reconciles explicit scheduled future events with inferred occurrences
    to prevent double counting, preserving schedule phase.
    """
    occurrences: list[ScheduledOccurrence] = []
    reconciled_explicit_ids: set[str] = set()

    for stream in streams:
        if stream.confidence != RecurrenceConfidence.SUPPORTED:
            continue

        if stream.schedule_type == RecurrenceScheduleType.CALENDAR_MONTH and stream.day_of_month:
            # Walk months from start to end
            cur_year, cur_month = start.year, start.month
            end_year, end_month = end.year, end.month

            while (cur_year, cur_month) <= (end_year, end_month):
                days_in_month = calendar.monthrange(cur_year, cur_month)[1]
                target_day = min(stream.day_of_month, days_in_month)
                occ_date = date(cur_year, cur_month, target_day)

                if start <= occ_date <= end:
                    matched_exp = None
                    for exp in explicit_future_events:
                        if _matches_explicit_event(exp, stream, occ_date, tolerance_days=3, reconciled_ids=reconciled_explicit_ids, all_streams=streams):
                            matched_exp = exp
                            break

                    if matched_exp is not None:
                        reconciled_explicit_ids.add(matched_exp.event_id)
                        exp_dt = matched_exp.settlement_date or matched_exp.event_date
                        exp_amt = matched_exp.amount or stream.typical_amount
                        if home_currency and matched_exp.currency != home_currency and dataset:
                            try:
                                exp_amt = convert_with_fallback(
                                    exp_amt,
                                    from_currency=matched_exp.currency,
                                    to_currency=home_currency,
                                    on_date=exp_dt,
                                    fx_rates=dataset.fx_rates,
                                )
                            except LookupError:
                                pass

                        occurrences.append(
                            ScheduledOccurrence(
                                stream=stream,
                                occurrence_date=exp_dt,
                                amount=exp_amt,
                                is_explicit_event=True,
                                reconciled_event_id=matched_exp.event_id,
                            )
                        )
                    else:
                        occurrences.append(
                            ScheduledOccurrence(
                                stream=stream,
                                occurrence_date=occ_date,
                                amount=stream.typical_amount,
                                is_explicit_event=False,
                                reconciled_event_id=None,
                            )
                        )

                # Next month
                if cur_month == 12:
                    cur_year += 1
                    cur_month = 1
                else:
                    cur_month += 1

        elif stream.schedule_type == RecurrenceScheduleType.FIXED_INTERVAL and stream.interval_days:
            # Anchor to stream's observed last occurrence to preserve schedule phase
            step = stream.interval_days
            anchor = stream.last_observed_date or start
            cur_date = anchor
            if cur_date < start:
                days_diff = (start - cur_date).days
                steps_needed = (days_diff + step - 1) // step
                cur_date = cur_date + timedelta(days=steps_needed * step)
            elif cur_date > start:
                while cur_date - timedelta(days=step) >= start:
                    cur_date -= timedelta(days=step)

            while cur_date <= end:
                matched_exp = None
                for exp in explicit_future_events:
                    if _matches_explicit_event(exp, stream, cur_date, tolerance_days=2, reconciled_ids=reconciled_explicit_ids, all_streams=streams):
                        matched_exp = exp
                        break

                if matched_exp is not None:
                    reconciled_explicit_ids.add(matched_exp.event_id)
                    exp_dt = matched_exp.settlement_date or matched_exp.event_date
                    exp_amt = matched_exp.amount or stream.typical_amount
                    if home_currency and matched_exp.currency != home_currency and dataset:
                        try:
                            exp_amt = convert_with_fallback(
                                exp_amt,
                                from_currency=matched_exp.currency,
                                to_currency=home_currency,
                                on_date=exp_dt,
                                fx_rates=dataset.fx_rates,
                            )
                        except LookupError:
                            pass

                    occurrences.append(
                        ScheduledOccurrence(
                            stream=stream,
                            occurrence_date=exp_dt,
                            amount=exp_amt,
                            is_explicit_event=True,
                            reconciled_event_id=matched_exp.event_id,
                        )
                    )
                else:
                    occurrences.append(
                        ScheduledOccurrence(
                            stream=stream,
                            occurrence_date=cur_date,
                            amount=stream.typical_amount,
                            is_explicit_event=False,
                            reconciled_event_id=None,
                        )
                    )
                cur_date += timedelta(days=step)

    # Sort chronological
    occurrences.sort(key=lambda o: o.occurrence_date)
    return tuple(occurrences)


def estimate_variable_spend(
    dataset: Dataset,
    user_id: str,
    anchor_date: date,
    method: str = "trailing_3_month_mean_floored_at_latest_month",
    image_amounts: Mapping[str, Decimal] | None = None,
) -> tuple[VariableSpendEstimate, ...]:
    """Conservative variable-spend estimation for groceries, transport, and dining.
    Compares declared robust estimators over trailing complete calendar months.
    """
    profile = dataset.profiles_by_user[user_id]
    home_currency = profile.home_currency

    # Compute bounds for 3 complete calendar months prior to anchor_date
    first_of_anchor_month = anchor_date.replace(day=1)
    
    # Month -1
    m1_end = first_of_anchor_month - timedelta(days=1)
    m1_start = m1_end.replace(day=1)

    # Month -2
    m2_end = m1_start - timedelta(days=1)
    m2_start = m2_end.replace(day=1)

    # Month -3
    m3_end = m2_start - timedelta(days=1)
    m3_start = m3_end.replace(day=1)

    months = [(m1_start, m1_end), (m2_start, m2_end), (m3_start, m3_end)]

    user_events = dataset.events_by_user.get(user_id, ())

    estimates: list[VariableSpendEstimate] = []

    for cat in sorted(VARIABLE_CATEGORIES, key=lambda c: c.value):
        supporting_ids: list[str] = []
        month_totals: list[Decimal] = []

        for m_start, m_end in months:
            total = Decimal(0)
            for e in user_events:
                if e.category == cat and e.status == EventStatus.SETTLED and e.direction == Direction.DEBIT:
                    dt = e.settlement_date or e.event_date
                    if m_start <= dt <= m_end:
                        supporting_ids.append(e.event_id)
                        amt = (image_amounts.get(e.event_id, e.amount) if image_amounts else e.amount) or Decimal(0)
                        if e.currency != home_currency:
                            try:
                                amt = convert_with_fallback(
                                    amt,
                                    from_currency=e.currency,
                                    to_currency=home_currency,
                                    on_date=dt,
                                    fx_rates=dataset.fx_rates,
                                )
                            except LookupError:
                                pass
                        total += amt
            month_totals.append(total)

        t_m1, t_m2, t_m3 = month_totals[0], month_totals[1], month_totals[2]
        mean_3m = (t_m1 + t_m2 + t_m3) / Decimal(3)

        if method == "trailing_3_month_mean_floored_at_latest_month":
            # U-FORECAST-1 default: mean of trailing 3 months, floored at latest month
            est = max(mean_3m, t_m1)
        elif method == "trailing_3_month_median":
            est = sorted([t_m1, t_m2, t_m3])[1]
        elif method == "trailing_3_month_mean":
            est = mean_3m
        elif method == "latest_complete_month":
            est = t_m1
        else:
            est = max(mean_3m, t_m1)

        estimates.append(
            VariableSpendEstimate(
                user_id=user_id,
                category=cat,
                monthly_estimate=est.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                method=method,
                supporting_event_ids=tuple(supporting_ids),
            )
        )

    return tuple(estimates)
