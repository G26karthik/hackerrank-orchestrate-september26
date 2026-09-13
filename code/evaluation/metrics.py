"""The evaluator: joins a candidate CSV to a label set by request_id, fails
loudly on any join discrepancy, and measures all seven required output
fields independently.

Two hard rules from the Stage 2 instruction, both enforced structurally
rather than by convention:

  * "Never shrink a denominator to the shorter file." `evaluate()` never
    computes any statistic over `set(candidate_ids) & set(label_ids)`. The
    join is checked FIRST and must be an exact match of ID sets (no missing,
    no extra, no duplicate) or `evaluate()` raises `StrictJoinError` before a
    single field is scored. There is no code path in this module that scores
    a partial overlap.
  * "Do not invent an official aggregate score or pool raw IDR and EUR
    errors." There is no total/weighted score anywhere in this module or in
    `schemas.EvaluationReport`, and every numeric-error collection is keyed
    by currency.

This module needs a loaded `Dataset` (for `requested_amount`, `home_currency`,
`minimum_balance_to_keep`, and event lookups for the spending-changes
well-formedness check) in addition to the candidate file and the label set.
"""

from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from buyorwait.csv_format import (
    CsvFormatError,
    PlanEntry,
    ReduceChange,
    StopChange,
    parse_payment_plan,
    parse_spending_changes,
)
from buyorwait.decimal_utils import DecimalParseError, format_capacity_amount, format_schedule_amount, parse_decimal
from buyorwait.schemas import (
    AffordabilityStatus,
    Currency,
    Dataset,
    ExpenseCategory,
    Flexibility,
    RecommendedPaymentMethod,
    SampleLabel,
)
from buyorwait.writer import REQUIRED_COLUMNS

from .schemas import (
    CapacityFieldStats,
    CategoricalFieldStats,
    EarliestDateFieldStats,
    EvaluationReport,
    ExplanationFieldStats,
    JoinError,
    ScheduleFieldStats,
    SpendingChangesFieldStats,
)

_CAPACITY_TOLERANCE = Decimal("0.005")  # for "exact" Decimal-equality after 2dp rounding


class StrictJoinError(Exception):
    """Raised by `evaluate()` when the candidate's request_ids do not match
    the label set's request_ids exactly. Carries the full `JoinError` so the
    caller can print every missing/extra/duplicate id, not just a count."""

    def __init__(self, join_error: JoinError):
        self.join_error = join_error
        parts = []
        if join_error.missing_in_candidate:
            parts.append(f"missing {len(join_error.missing_in_candidate)} row(s): {join_error.missing_in_candidate}")
        if join_error.extra_in_candidate:
            parts.append(f"extra {len(join_error.extra_in_candidate)} row(s): {join_error.extra_in_candidate}")
        if join_error.duplicate_in_candidate:
            parts.append(f"duplicate {len(join_error.duplicate_in_candidate)} id(s): {join_error.duplicate_in_candidate}")
        super().__init__("candidate/label join failed: " + "; ".join(parts))


def read_candidate_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is not None and tuple(reader.fieldnames) != REQUIRED_COLUMNS:
            raise ValueError(
                f"candidate file header {tuple(reader.fieldnames)} does not match the "
                f"required columns {REQUIRED_COLUMNS}"
            )
        return list(reader)


def check_join(candidate_rows: list[dict[str, str]], label_ids: set[str]) -> JoinError:
    candidate_ids_list = [r["request_id"] for r in candidate_rows]
    counts = Counter(candidate_ids_list)
    duplicate_ids = tuple(sorted(cid for cid, n in counts.items() if n > 1))
    candidate_id_set = set(candidate_ids_list)
    missing = tuple(sorted(label_ids - candidate_id_set))
    extra = tuple(sorted(candidate_id_set - label_ids))
    return JoinError(missing_in_candidate=missing, extra_in_candidate=extra, duplicate_in_candidate=duplicate_ids)


# ------------------------------- per-field scorers -------------------------------


def _score_capacity(
    candidate_by_id: Mapping[str, dict[str, str]],
    labels_by_id: Mapping[str, SampleLabel],
    dataset: Dataset,
) -> CapacityFieldStats:
    n = 0
    exact = 0
    signed: dict[str, list[Decimal]] = {}
    relative: dict[str, list[Decimal]] = {}
    for rid, label in labels_by_id.items():
        req = dataset.all_requests_by_id[rid]
        currency = dataset.profiles_by_user[req.user_id].home_currency.value
        n += 1
        raw = candidate_by_id[rid]["amount_safe_to_pay"]
        try:
            got = parse_decimal(raw, field="amount_safe_to_pay", context=rid)
        except DecimalParseError:
            # An unparsable capacity value is a maximal error, not a skip;
            # record it as the full requested_amount off so it is never
            # invisible in the currency-grouped error report.
            got = label.amount_safe_to_pay - req.requested_amount - Decimal("1")
        expected = label.amount_safe_to_pay
        err = got - expected
        signed.setdefault(currency, []).append(err)
        relative.setdefault(currency, []).append(err / req.requested_amount if req.requested_amount else Decimal(0))
        if abs(err) <= _CAPACITY_TOLERANCE:
            exact += 1
    return CapacityFieldStats(
        field_name="amount_safe_to_pay",
        n=n,
        exact_matches=exact,
        signed_errors_by_currency={k: tuple(v) for k, v in signed.items()},
        relative_errors_by_currency={k: tuple(v) for k, v in relative.items()},
    )


def _score_categorical(
    candidate_by_id: Mapping[str, dict[str, str]],
    labels_by_id: Mapping[str, SampleLabel],
    *,
    field_name: str,
    label_value,
) -> CategoricalFieldStats:
    n = 0
    exact = 0
    confusion: Counter[tuple[str, str]] = Counter()
    for rid, label in labels_by_id.items():
        n += 1
        expected = getattr(label, field_name).value
        got = candidate_by_id[rid][field_name].strip()
        confusion[(expected, got)] += 1
        if got == expected:
            exact += 1
    return CategoricalFieldStats(field_name=field_name, n=n, exact_matches=exact, confusion=dict(confusion))


def _entries_equal(a: tuple[PlanEntry, ...], b: tuple[PlanEntry, ...]) -> bool:
    if len(a) != len(b):
        return False
    return all(x.entry_date == y.entry_date and x.amount == y.amount for x, y in zip(a, b))


def _score_schedule(
    candidate_by_id: Mapping[str, dict[str, str]], labels_by_id: Mapping[str, SampleLabel]
) -> ScheduleFieldStats:
    n = 0
    parse_failures: list[str] = []
    exact = 0
    date_set_matches = 0
    sum_matches = 0
    for rid, label in labels_by_id.items():
        n += 1
        expected = parse_payment_plan(label.payment_plan_raw)  # labels are trusted, already validated at load
        raw = candidate_by_id[rid]["payment_plan"]
        try:
            got = parse_payment_plan(raw)
        except CsvFormatError:
            parse_failures.append(rid)
            continue
        if _entries_equal(expected, got):
            exact += 1
        if {e.entry_date for e in expected} == {e.entry_date for e in got}:
            date_set_matches += 1
        if sum(e.amount for e in expected) == sum((e.amount for e in got), Decimal(0)):
            sum_matches += 1
    return ScheduleFieldStats(
        n=n,
        parse_failures=tuple(parse_failures),
        exact_matches=exact,
        date_set_matches=date_set_matches,
        sum_matches=sum_matches,
    )


def _score_earliest_date(
    candidate_by_id: Mapping[str, dict[str, str]], labels_by_id: Mapping[str, SampleLabel]
) -> EarliestDateFieldStats:
    n = 0
    exact = 0
    both_empty = 0
    mismatches: list[tuple[str, str, str]] = []
    for rid, label in labels_by_id.items():
        n += 1
        expected = label.earliest_date_for_full_payment.isoformat() if label.earliest_date_for_full_payment else ""
        got = candidate_by_id[rid]["earliest_date_for_full_payment"].strip()
        if expected == "" and got == "":
            both_empty += 1
            exact += 1
        elif expected == got:
            exact += 1
        else:
            mismatches.append((rid, expected, got))
    return EarliestDateFieldStats(n=n, exact_matches=exact, both_empty=both_empty, mismatches=tuple(mismatches))


def _action_is_well_formed(action, dataset: Dataset, user_id: str) -> str | None:
    """Returns None when the action is well-formed against S-15, else a
    human-readable violation description. Checkable purely from the rules
    and the loaded Dataset -- no label required."""
    event = dataset.events_by_id.get(action.event_id)
    if event is None:
        return f"targets unknown event_id {action.event_id!r}"
    if event.user_id != user_id:
        return f"event {action.event_id!r} belongs to a different user"
    if event.flexibility == Flexibility.FIXED:
        return f"event {action.event_id!r} is not flexible (flexibility=fixed)"
    profile = dataset.profiles_by_user[user_id]
    if event.category in profile.expense_categories_to_protect:
        return f"event {action.event_id!r} category {event.category.value} is protected"
    if isinstance(action, StopChange):
        if event.category not in profile.expense_categories_user_is_willing_to_stop:
            return f"event {action.event_id!r} category {event.category.value} is not in the user's stop list"
    elif isinstance(action, ReduceChange):
        if event.category not in profile.expense_categories_user_is_willing_to_reduce:
            return f"event {action.event_id!r} category {event.category.value} is not in the user's reduce list"
        if event.minimum_allowed_amount is not None and action.new_amount < event.minimum_allowed_amount:
            return (
                f"event {action.event_id!r} reduce_to {action.new_amount} is below its "
                f"minimum_allowed_amount {event.minimum_allowed_amount}"
            )
    return None


def _score_spending_changes(
    candidate_by_id: Mapping[str, dict[str, str]],
    labels_by_id: Mapping[str, SampleLabel],
    dataset: Dataset,
) -> SpendingChangesFieldStats:
    n = 0
    parse_failures: list[str] = []
    exact = 0
    well_formed = 0
    violations: list[tuple[str, str]] = []
    for rid, label in labels_by_id.items():
        n += 1
        expected = set(parse_spending_changes(label.spending_changes_needed_raw))
        raw = candidate_by_id[rid]["spending_changes_needed"]
        try:
            got_tuple = parse_spending_changes(raw)
        except CsvFormatError as exc:
            parse_failures.append(rid)
            violations.append((rid, f"parse error: {exc}"))
            continue
        if set(got_tuple) == expected:
            exact += 1
        user_id = dataset.all_requests_by_id[rid].user_id
        row_violations = [
            v for v in (_action_is_well_formed(a, dataset, user_id) for a in got_tuple) if v is not None
        ]
        if row_violations:
            violations.append((rid, "; ".join(row_violations)))
        else:
            well_formed += 1
    return SpendingChangesFieldStats(
        n=n,
        parse_failures=tuple(parse_failures),
        exact_set_matches=exact,
        well_formed_count=well_formed,
        rule_violations=tuple(violations),
    )


def _is_grounded(
    explanation: str,
    *,
    amount_safe_to_pay: Decimal,
    minimum_balance_to_keep: Decimal,
    plan_entries: tuple[PlanEntry, ...],
) -> bool:
    """Deterministic proxy only -- see schemas.ExplanationFieldStats
    docstring. True when the text contains at least one of the row's own
    decisive figures: the capacity amount, the minimum balance, or a plan
    amount, with thousands separators stripped from the text before matching
    (the samples write "25,256" in prose but "25256" in the field itself)."""
    text = explanation.replace(",", "")
    candidates = [format_capacity_amount(amount_safe_to_pay), format_capacity_amount(minimum_balance_to_keep)]
    candidates += [format_schedule_amount(e.amount) for e in plan_entries]
    return any(c and c in text for c in candidates)


def _score_explanation(
    candidate_by_id: Mapping[str, dict[str, str]],
    labels_by_id: Mapping[str, SampleLabel],
    dataset: Dataset,
) -> ExplanationFieldStats:
    n = 0
    empty = 0
    grounded = 0
    ungrounded: list[str] = []
    for rid, label in labels_by_id.items():
        n += 1
        text = candidate_by_id[rid]["decision_explanation"].strip()
        if not text:
            empty += 1
            ungrounded.append(rid)
            continue
        req = dataset.all_requests_by_id[rid]
        profile = dataset.profiles_by_user[req.user_id]
        try:
            plan_entries = parse_payment_plan(candidate_by_id[rid]["payment_plan"])
        except CsvFormatError:
            plan_entries = ()
        try:
            capacity = parse_decimal(candidate_by_id[rid]["amount_safe_to_pay"], field="amount_safe_to_pay")
        except DecimalParseError:
            capacity = label.amount_safe_to_pay
        if _is_grounded(
            text,
            amount_safe_to_pay=capacity,
            minimum_balance_to_keep=profile.minimum_balance_to_keep,
            plan_entries=plan_entries,
        ):
            grounded += 1
        else:
            ungrounded.append(rid)
    return ExplanationFieldStats(n=n, empty_count=empty, grounded_count=grounded, ungrounded_request_ids=tuple(ungrounded))


# ------------------------------------ entry point ------------------------------------


def evaluate(
    dataset: Dataset,
    candidate_path: str | Path,
    labels_by_id: Mapping[str, SampleLabel] | None = None,
) -> EvaluationReport:
    """Score `candidate_path` (a CSV shaped like output.csv) against
    `labels_by_id` (defaults to `dataset.sample_labels_by_id` -- the 25
    public samples). Raises `StrictJoinError` before scoring anything if the
    candidate's request_ids do not exactly match the label set.
    """
    if labels_by_id is None:
        labels_by_id = dataset.sample_labels_by_id

    candidate_rows = read_candidate_rows(Path(candidate_path))
    join_error = check_join(candidate_rows, set(labels_by_id.keys()))
    if join_error.has_any:
        raise StrictJoinError(join_error)

    candidate_by_id = {r["request_id"]: r for r in candidate_rows}

    return EvaluationReport(
        n_rows=len(labels_by_id),
        amount_safe_to_pay=_score_capacity(candidate_by_id, labels_by_id, dataset),
        affordability_status=_score_categorical(
            candidate_by_id, labels_by_id, field_name="affordability_status", label_value=AffordabilityStatus
        ),
        recommended_payment_method=_score_categorical(
            candidate_by_id, labels_by_id, field_name="recommended_payment_method", label_value=RecommendedPaymentMethod
        ),
        payment_plan=_score_schedule(candidate_by_id, labels_by_id),
        earliest_date_for_full_payment=_score_earliest_date(candidate_by_id, labels_by_id),
        spending_changes_needed=_score_spending_changes(candidate_by_id, labels_by_id, dataset),
        decision_explanation=_score_explanation(candidate_by_id, labels_by_id, dataset),
    )


def render_report_text(report: EvaluationReport) -> str:
    """Human-readable report. No aggregate score is computed or printed."""
    lines = [f"Evaluation report -- {report.n_rows} rows scored", ""]

    c = report.amount_safe_to_pay
    lines.append(f"amount_safe_to_pay: exact matches {c.exact_matches}/{c.n} ({c.exact_match_rate:.1%})")
    for currency in sorted(c.signed_errors_by_currency):
        errs = c.signed_errors_by_currency[currency]
        rel = c.relative_errors_by_currency[currency]
        mean_abs = sum(abs(e) for e in errs) / len(errs)
        mean_rel = sum(abs(r) for r in rel) / len(rel)
        lines.append(
            f"  {currency}: n={len(errs)} mean|error|={mean_abs} mean|relative error|={mean_rel:.4%}"
        )

    for stats in (report.affordability_status, report.recommended_payment_method):
        lines.append(f"{stats.field_name}: exact matches {stats.exact_matches}/{stats.n} ({stats.accuracy:.1%})")

    p = report.payment_plan
    lines.append(
        f"payment_plan: exact {p.exact_matches}/{p.n} ({p.exact_match_rate:.1%}); "
        f"parse failures {len(p.parse_failures)}; date-set matches {p.date_set_matches}; sum matches {p.sum_matches}"
    )

    e = report.earliest_date_for_full_payment
    lines.append(f"earliest_date_for_full_payment: exact {e.exact_matches}/{e.n} ({e.exact_match_rate:.1%}), of which both-empty {e.both_empty}")

    s = report.spending_changes_needed
    lines.append(
        f"spending_changes_needed: exact set match {s.exact_set_matches}/{s.n} ({s.exact_match_rate:.1%}); "
        f"parse failures {len(s.parse_failures)}; rule-well-formed {s.well_formed_count}/{s.n}"
    )

    x = report.decision_explanation
    lines.append(f"decision_explanation: grounded {x.grounded_count}/{x.n} ({x.grounded_rate:.1%}); empty {x.empty_count}")

    return "\n".join(lines) + "\n"
