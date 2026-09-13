"""The independent reference cash-flow simulator.

This module is deliberately simple and deliberately independent. It takes an
explicit, already-normalized list of signed cash flows plus an explicit
payment schedule, walks them day by day with `Decimal`, and reports whether
the minimum balance is ever breached. Nothing here calls, imports, or knows
about `forecast.py`, `planner.py`, or any future "safety function" the
production pipeline will eventually implement -- so when the planner exists,
this module can replay its candidate plan as a genuinely independent check,
not a restatement of the same logic. `independent_verifier.py` is the thin
production-facing wrapper that will do exactly that; this module is the
engine underneath it, and also underneath every hand-built test fixture in
`code/evaluation/fixtures/`.

WHAT THIS MODULE CAN AND CANNOT ESTABLISH
------------------------------------------
Correct replay only proves that a given schedule is *arithmetically safe*
against a given set of flows. It cannot establish that those flows are
*true*. If the caller hands this simulator an inferred recurring salary that
does not actually recur, or a recurrence-detector's guess about next month's
groceries that turns out wrong, the simulator will faithfully confirm that a
plan is "safe" against a fiction. Verifying feasibility and verifying the
underlying financial facts are two different problems; this module solves
only the first one. The second is the job of the evidence and recurrence
modules (currently interface stubs -- see evidence.py, resolver.py,
recurrence.py), and ultimately cannot be fully verified against reality at
all without ground truth the participant does not have.

RULES ENCODED HERE (all documented, none silently assumed)
------------------------------------------------------------
* Historical-settlement exclusion (hard validation): every flow's date must
  be >= `anchor_date` (the day the opening balance is valid as of, i.e.
  `request_date`). A flow dated strictly before the anchor is, by
  construction, already reflected in `opening_balance` -- passing one in is
  treated as a caller bug and raises, rather than being silently ignored,
  because silently ignoring it could hide a real double-counting mistake
  upstream. Flows dated exactly ON the anchor date ARE allowed: that is
  precisely where a same-day candidate payment or a same-day reserved
  pending debit lives.
* Same-day ordering (U-SIMORDER-1, new in this stage -- see
  evaluation/assumptions.md section 4): within one calendar date, ALL debits
  are treated as applied before ANY credit, when checking whether the floor
  is breached that day. This is the financially safer of the two possible
  orderings (S-24.4) and is what makes "a same-day debit pushes the balance
  below the floor even though the day ends comfortably above it" detectable
  at all -- checking only the end-of-day balance would miss it entirely.
* Forecast window (U-WINDOW-1, new in this stage): the 90-day window is
  `[anchor_date, anchor_date + 90 days]` inclusive of both ends. No public
  document states whether day 90 itself counts; inclusive is the wider,
  more conservative window.
* `<=` deadlines: a payment on `desired_completion_date` counts as on time,
  matching S-05's own wording ("on or before").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

FORECAST_HORIZON_DAYS = 90  # U-WINDOW-1: inclusive of both ends


class FlowKind(StrEnum):
    """Diagnostic tag only -- the simulator's arithmetic does not branch on
    this value (every flow is just a signed Decimal on a date). It exists so
    a breach report can say *what* caused the dip, which is what
    `decision_explanation` (Stage 4) will need to stay grounded."""

    RESERVED_PENDING_DEBIT = "reserved_pending_debit"
    SETTLED_RECURRING_PROJECTION = "settled_recurring_projection"
    VARIABLE_SPEND_PROJECTION = "variable_spend_projection"
    CONFIRMED_INCOME = "confirmed_income"
    CANDIDATE_PAYMENT = "candidate_payment"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CashFlow:
    """One signed, already-currency-converted cash movement.
    `amount` is positive for a credit, negative for a debit -- the sign
    carries the direction so the simulator never has to re-derive it from a
    `Direction` enum (that translation belongs to whichever module builds
    the flow list, e.g. the future forecast.py or a test fixture)."""

    flow_date: date
    amount: Decimal
    kind: FlowKind
    label: str  # human-readable source, e.g. "event_476 Family streaming plan"


@dataclass(frozen=True, slots=True)
class ScheduledPayment:
    payment_date: date
    amount: Decimal  # always positive; the simulator negates it internally
    label: str = "payment"


@dataclass(frozen=True, slots=True)
class DayBalance:
    day: date
    balance_before_debits: Decimal  # start-of-day balance, before that day's debits
    floor_check_balance: Decimal  # balance after debits, before credits (the worst point in the day)
    balance_end_of_day: Decimal  # after both debits and credits


@dataclass(frozen=True, slots=True)
class Breach:
    day: date
    floor_check_balance: Decimal
    minimum_balance_to_keep: Decimal
    shortfall: Decimal  # positive number: how far below the minimum


@dataclass(frozen=True, slots=True)
class SimulationResult:
    anchor_date: date
    horizon_end: date
    opening_balance: Decimal
    minimum_balance_to_keep: Decimal
    daily_balances: tuple[DayBalance, ...]
    breaches: tuple[Breach, ...]
    total_scheduled_paid: Decimal

    @property
    def is_safe(self) -> bool:
        """A plan is safe iff the floor is never breached anywhere in the
        forecast window (S-04 / the 90-Day Safety Check)."""
        return len(self.breaches) == 0 and self.opening_balance >= self.minimum_balance_to_keep

    def first_breach_date(self) -> date | None:
        if self.breaches:
            return self.breaches[0].day
        if self.opening_balance < self.minimum_balance_to_keep:
            return self.anchor_date
        return None


class SimulatorInputError(ValueError):
    """Raised for a caller mistake: a flow dated before the anchor (would
    double-count history already inside `opening_balance`), a flow or
    payment beyond the forecast horizon, or a non-positive scheduled
    payment amount."""


def simulate(
    *,
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    flows: Iterable[CashFlow] = (),
    schedule: Iterable[ScheduledPayment] = (),
    horizon_days: int = FORECAST_HORIZON_DAYS,
    same_day_order: str = "credits_first",
) -> SimulationResult:
    """Replay `flows` and `schedule` from `opening_balance` on `anchor_date`
    forward through `anchor_date + horizon_days` (inclusive), and report every
    day the floor is breached.

    Raises `SimulatorInputError` if any flow or scheduled payment is dated
    before `anchor_date` (historical-settlement exclusion) or after the
    horizon end (out of the window this call was asked to check).
    """
    horizon_end = anchor_date + timedelta(days=horizon_days)
    flows = tuple(flows)
    schedule = tuple(schedule)

    for f in flows:
        if f.flow_date < anchor_date:
            raise SimulatorInputError(
                f"flow {f.label!r} dated {f.flow_date} is before anchor_date {anchor_date}; "
                "historical flows must not be passed to the simulator -- they are already "
                "reflected in opening_balance"
            )
        if f.flow_date > horizon_end:
            raise SimulatorInputError(
                f"flow {f.label!r} dated {f.flow_date} is after the horizon end {horizon_end}"
            )
    for p in schedule:
        if p.amount <= 0:
            raise SimulatorInputError(f"scheduled payment {p.label!r} amount must be positive, got {p.amount}")
        if p.payment_date < anchor_date:
            raise SimulatorInputError(
                f"scheduled payment {p.label!r} dated {p.payment_date} is before anchor_date {anchor_date}"
            )
        if p.payment_date > horizon_end:
            raise SimulatorInputError(
                f"scheduled payment {p.label!r} dated {p.payment_date} is after the horizon end {horizon_end}"
            )

    # Bucket every movement by date. Same-day ordering (U-SIMORDER-1):
    # 'credits_first' (default) credits incoming flows (e.g. payroll direct deposit)
    # before candidate debits settle, resolving false same-day floor breaches.
    # 'debits_first' applies debits before credits for ultra-conservative worst-point testing.
    debits_by_day: dict[date, Decimal] = {}
    credits_by_day: dict[date, Decimal] = {}

    def add_debit(d: date, amount: Decimal) -> None:
        debits_by_day[d] = debits_by_day.get(d, Decimal(0)) + amount

    def add_credit(d: date, amount: Decimal) -> None:
        credits_by_day[d] = credits_by_day.get(d, Decimal(0)) + amount

    for f in flows:
        if f.amount < 0:
            add_debit(f.flow_date, -f.amount)
        elif f.amount > 0:
            add_credit(f.flow_date, f.amount)
        # amount == 0 contributes nothing; not an error, just a no-op flow.

    total_scheduled = Decimal(0)
    for p in schedule:
        add_debit(p.payment_date, p.amount)
        total_scheduled += p.amount

    active_days = sorted(set(debits_by_day) | set(credits_by_day))

    daily_balances: list[DayBalance] = []
    breaches: list[Breach] = []
    if opening_balance < minimum_balance_to_keep and (not active_days or active_days[0] > anchor_date):
        breaches.append(
            Breach(
                day=anchor_date,
                floor_check_balance=opening_balance,
                minimum_balance_to_keep=minimum_balance_to_keep,
                shortfall=minimum_balance_to_keep - opening_balance,
            )
        )
    running = opening_balance
    for day in active_days:
        start_of_day = running
        day_debits = debits_by_day.get(day, Decimal(0))
        day_credits = credits_by_day.get(day, Decimal(0))
        if same_day_order == "credits_first":
            post_credits = start_of_day + day_credits
            floor_check = post_credits - day_debits
            end_of_day = floor_check
        elif same_day_order == "debits_first":
            floor_check = start_of_day - day_debits
            end_of_day = floor_check + day_credits
        else:
            raise ValueError(f"Unknown same_day_order: {same_day_order!r}")

        if floor_check < minimum_balance_to_keep:
            breaches.append(
                Breach(
                    day=day,
                    floor_check_balance=floor_check,
                    minimum_balance_to_keep=minimum_balance_to_keep,
                    shortfall=minimum_balance_to_keep - floor_check,
                )
            )
        daily_balances.append(
            DayBalance(
                day=day,
                balance_before_debits=start_of_day,
                floor_check_balance=floor_check,
                balance_end_of_day=end_of_day,
            )
        )
        running = end_of_day

    return SimulationResult(
        anchor_date=anchor_date,
        horizon_end=horizon_end,
        opening_balance=opening_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        daily_balances=tuple(daily_balances),
        breaches=tuple(breaches),
        total_scheduled_paid=total_scheduled,
    )


def balance_on(result: SimulationResult, day: date) -> Decimal:
    """The end-of-day balance on `day`, or the most recent prior day's
    end-of-day balance if `day` had no activity, or `opening_balance` if
    `day` is before the first active day. Used by fixtures and tests to
    query the trajectory at an arbitrary date without re-walking it."""
    if day < result.anchor_date:
        raise SimulatorInputError(f"{day} is before anchor_date {result.anchor_date}")
    running = result.opening_balance
    for db in result.daily_balances:
        if db.day > day:
            break
        running = db.balance_end_of_day
    return running
