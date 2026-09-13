"""The serialization/parsing contract for the two compound output fields:
`payment_plan` and `spending_changes_needed`.

This module is shared, byte-for-byte, between `writer.py` (typed object ->
CSV string, used to produce `output.csv`) and `code/evaluation/metrics.py`
(CSV string -> typed object, used to score a candidate `output.csv` or the
public `sample_requests.csv` labels). Writing both directions from ONE module
guarantees they can never silently drift apart -- a round-trip test
(`serialize(parse(x)) == x`) in tests/test_csv_format.py enforces this
directly rather than trusting it by inspection.

Grammar, from problem_statement.md "Allowed values":

    payment_plan            := "none" | entry ("|" entry)*
    entry                   := YYYY-MM-DD ":" amount
    spending_changes_needed := "none" | action ("|" action){0,2}
    action                  := "stop:" event_id
                              | "reduce_to:" event_id ":" amount

`payment_plan` entries must already be in chronological order (S-14 uses plan
timing for ranking); this module preserves whatever order it is given on
serialize and reports whatever order it finds on parse -- it does not sort or
otherwise "fix" a malformed plan, since silently repairing input would hide a
bug the evaluator exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .decimal_utils import DecimalParseError, format_schedule_amount, parse_decimal


class CsvFormatError(ValueError):
    """Raised when a `payment_plan` or `spending_changes_needed` cell does not
    match the grammar above. Never silently ignored or partially parsed."""


@dataclass(frozen=True, slots=True)
class PlanEntry:
    entry_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class StopChange:
    event_id: str


@dataclass(frozen=True, slots=True)
class ReduceChange:
    event_id: str
    new_amount: Decimal


SpendingChange = StopChange | ReduceChange


# --------------------------------- payment_plan ---------------------------------


def parse_payment_plan(raw: str) -> tuple[PlanEntry, ...]:
    """Parse a `payment_plan` cell. Returns () for "none". Raises
    `CsvFormatError` for anything that doesn't match the grammar, including a
    literal empty string (the spec's explicit "no payment" value is the word
    "none", not blank)."""
    text = raw.strip()
    if text == "none":
        return ()
    if text == "":
        raise CsvFormatError("payment_plan is blank; use the literal 'none' for no payment")
    entries = []
    for chunk in text.split("|"):
        if ":" not in chunk:
            raise CsvFormatError(f"payment_plan entry {chunk!r} is not 'YYYY-MM-DD:amount'")
        date_part, amount_part = chunk.split(":", 1)
        try:
            d = date.fromisoformat(date_part.strip())
        except ValueError as exc:
            raise CsvFormatError(f"payment_plan entry {chunk!r} has an invalid date") from exc
        try:
            amount = parse_decimal(amount_part, field="payment_plan amount", context=chunk)
        except DecimalParseError as exc:
            raise CsvFormatError(str(exc)) from exc
        entries.append(PlanEntry(entry_date=d, amount=amount))
    return tuple(entries)


def is_chronological(entries: tuple[PlanEntry, ...]) -> bool:
    """S-14 / problem_statement.md requires entries in chronological order.
    Ties (two entries on the same date) are accepted as chronological -- the
    spec never says entries on the same date must be ordered a particular way,
    and the only real schedules in this dataset (partial_payment, and every
    installment option) never repeat a date."""
    return all(entries[i].entry_date <= entries[i + 1].entry_date for i in range(len(entries) - 1))


def serialize_payment_plan(entries: tuple[PlanEntry, ...]) -> str:
    """Inverse of `parse_payment_plan`. Does not sort or validate chronology --
    callers (writer.py) are expected to construct entries in order already;
    tests/test_csv_format.py checks the round trip on both an ordered and an
    out-of-order input to confirm this function never silently reorders."""
    if not entries:
        return "none"
    return "|".join(f"{e.entry_date.isoformat()}:{format_schedule_amount(e.amount)}" for e in entries)


# ----------------------------- spending_changes_needed -----------------------------


def parse_spending_changes(raw: str) -> tuple[SpendingChange, ...]:
    """Parse a `spending_changes_needed` cell. Returns () for "none". Raises
    on malformed syntax, more than three actions, or the same event_id
    appearing in both a stop and a reduce action (mutually exclusive per
    problem_statement.md "Choosing Between Safe Plans"). Does NOT check
    whether the event is flexible, non-protected, or permitted -- that needs
    the loaded Dataset and belongs to the future spending_changes module; this
    function only enforces what is decidable from the string alone.
    """
    text = raw.strip()
    if text == "none":
        return ()
    if text == "":
        raise CsvFormatError("spending_changes_needed is blank; use the literal 'none' for no change")
    actions: list[SpendingChange] = []
    for chunk in text.split("|"):
        if chunk.startswith("stop:"):
            event_id = chunk[len("stop:"):].strip()
            if not event_id:
                raise CsvFormatError(f"spending_changes_needed action {chunk!r} has no event_id")
            actions.append(StopChange(event_id=event_id))
        elif chunk.startswith("reduce_to:"):
            rest = chunk[len("reduce_to:"):]
            if ":" not in rest:
                raise CsvFormatError(f"spending_changes_needed action {chunk!r} is not 'reduce_to:<id>:<amount>'")
            event_id, amount_part = rest.rsplit(":", 1)
            event_id = event_id.strip()
            if not event_id:
                raise CsvFormatError(f"spending_changes_needed action {chunk!r} has no event_id")
            try:
                amount = parse_decimal(amount_part, field="reduce_to amount", context=chunk)
            except DecimalParseError as exc:
                raise CsvFormatError(str(exc)) from exc
            actions.append(ReduceChange(event_id=event_id, new_amount=amount))
        else:
            raise CsvFormatError(f"spending_changes_needed action {chunk!r} is not 'stop:' or 'reduce_to:'")

    if len(actions) > 3:
        raise CsvFormatError(f"spending_changes_needed has {len(actions)} actions; at most 3 are allowed")

    seen_events: dict[str, str] = {}
    for a in actions:
        kind = "stop" if isinstance(a, StopChange) else "reduce_to"
        if a.event_id in seen_events and seen_events[a.event_id] != kind:
            raise CsvFormatError(
                f"event {a.event_id!r} appears in both a stop and a reduce_to action; mutually exclusive"
            )
        if a.event_id in seen_events and seen_events[a.event_id] == kind:
            raise CsvFormatError(f"event {a.event_id!r} appears more than once in spending_changes_needed")
        seen_events[a.event_id] = kind

    return tuple(actions)


def serialize_spending_changes(actions: tuple[SpendingChange, ...]) -> str:
    if not actions:
        return "none"
    parts = []
    for a in actions:
        if isinstance(a, StopChange):
            parts.append(f"stop:{a.event_id}")
        else:
            parts.append(f"reduce_to:{a.event_id}:{format_schedule_amount(a.new_amount)}")
    return "|".join(parts)
