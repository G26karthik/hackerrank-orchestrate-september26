"""Result schemas for the evaluator (metrics.py) and the experiment register.

Every field of the required output is measured separately (Stage 2 instruction
and evaluation/workflow.md rule 6, addressing the "incomplete field evaluation"
weakness). There is deliberately no `overall_score` field anywhere in this
module: "Do not invent an official aggregate score or pool raw IDR and EUR
errors" is enforced by never defining a container that could hold one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True, slots=True)
class JoinError:
    """Every discrepancy between the candidate file's request_ids and the
    label set's request_ids. Raised, never silently tolerated -- see
    metrics.py's `StrictJoinError`."""

    missing_in_candidate: tuple[str, ...]  # label ids with no candidate row
    extra_in_candidate: tuple[str, ...]  # candidate ids not in the label set
    duplicate_in_candidate: tuple[str, ...]  # candidate ids appearing more than once

    @property
    def has_any(self) -> bool:
        return bool(self.missing_in_candidate or self.extra_in_candidate or self.duplicate_in_candidate)


@dataclass(frozen=True, slots=True)
class CategoricalFieldStats:
    """`affordability_status` and `recommended_payment_method` share this
    shape: a plain accuracy count plus a full confusion matrix, which is cheap
    for a 4- or 5-value enum and far more diagnostic than accuracy alone."""

    field_name: str
    n: int
    exact_matches: int
    confusion: Mapping[tuple[str, str], int]  # (expected_value, got_value) -> count

    @property
    def accuracy(self) -> float:
        return self.exact_matches / self.n if self.n else 0.0


@dataclass(frozen=True, slots=True)
class CapacityFieldStats:
    """`amount_safe_to_pay`. Errors are grouped by currency and never pooled
    -- an error of 100 INR and an error of 100 EUR are not the same
    magnitude of mistake, and averaging them would misrepresent both.
    `relative_errors_by_currency` divides by each row's own requested_amount
    (evaluation/contract.md R2), which is scale-free and DOES admit
    cross-currency comparison even though the absolute errors do not.
    """

    field_name: str
    n: int
    exact_matches: int  # Decimal equality after 2dp quantization
    signed_errors_by_currency: Mapping[str, tuple[Decimal, ...]]  # got - expected
    relative_errors_by_currency: Mapping[str, tuple[Decimal, ...]]  # (got - expected) / requested_amount

    @property
    def exact_match_rate(self) -> float:
        return self.exact_matches / self.n if self.n else 0.0


@dataclass(frozen=True, slots=True)
class ScheduleFieldStats:
    """`payment_plan`. Parsing is separated from matching: a malformed cell
    is always wrong regardless of any tolerance, and is reported by id so it
    can be inspected directly rather than folded into a mismatch count."""

    field_name: str = field(default="payment_plan")
    n: int = 0
    parse_failures: tuple[str, ...] = ()  # request_ids whose candidate cell didn't parse
    exact_matches: int = 0  # identical (date, amount) tuples in the same order
    date_set_matches: int = 0  # diagnostic only: same dates, amounts may differ
    sum_matches: int = 0  # diagnostic only: total paid matches, entries may differ

    @property
    def exact_match_rate(self) -> float:
        return self.exact_matches / self.n if self.n else 0.0


@dataclass(frozen=True, slots=True)
class EarliestDateFieldStats:
    """`earliest_date_for_full_payment`. Empty is a real, meaningful value
    (S-06: "never" within the forecast) and is compared for equality just
    like a date -- both-empty counts as a match, one-empty-one-not never does.
    `mismatches` lists every disagreement for direct inspection; there is no
    minimality check here yet (that needs the not-yet-built reference
    forecast -- see the module docstring for why)."""

    n: int
    exact_matches: int  # includes both-empty
    both_empty: int
    mismatches: tuple[tuple[str, str, str], ...]  # (request_id, expected_or_'', got_or_'')

    @property
    def exact_match_rate(self) -> float:
        return self.exact_matches / self.n if self.n else 0.0


@dataclass(frozen=True, slots=True)
class SpendingChangesFieldStats:
    """`spending_changes_needed`. Three independent checks, reported
    separately: does it PARSE at all; does the parsed action SET match the
    label exactly; and -- checkable without any label at all, purely from the
    rules -- is every action WELL-FORMED against the loaded Dataset (targets
    an existing event, that event is flexible and not fixed, its category is
    not protected, and its category is in the user's permitted reduce/stop
    list for that action type)."""

    n: int
    parse_failures: tuple[str, ...]
    exact_set_matches: int
    well_formed_count: int  # rows where every action satisfies the rule-based check
    rule_violations: tuple[tuple[str, str], ...]  # (request_id, description)

    @property
    def exact_match_rate(self) -> float:
        return self.exact_set_matches / self.n if self.n else 0.0


@dataclass(frozen=True, slots=True)
class ExplanationFieldStats:
    """`decision_explanation`. A deterministic, rule-based proxy for
    "grounded" -- does the text contain the row's own decisive numbers -- NOT
    a judgment of prose quality. evaluation/assumptions.md U-SCORE-2 records
    that no tolerance or judge is specified publicly; this is a floor check,
    not a substitute for human or model review.
    """

    n: int
    empty_count: int
    grounded_count: int  # contains at least the amount_safe_to_pay figure (or is a not_affordable row)
    ungrounded_request_ids: tuple[str, ...]

    @property
    def grounded_rate(self) -> float:
        return self.grounded_count / self.n if self.n else 0.0


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    n_rows: int
    amount_safe_to_pay: CapacityFieldStats
    affordability_status: CategoricalFieldStats
    recommended_payment_method: CategoricalFieldStats
    payment_plan: ScheduleFieldStats
    earliest_date_for_full_payment: EarliestDateFieldStats
    spending_changes_needed: SpendingChangesFieldStats
    decision_explanation: ExplanationFieldStats


# --------------------------- experiment register ---------------------------


@dataclass(frozen=True, slots=True)
class ExperimentEntry:
    """One append-only row in evaluation/experiments.jsonl.

    `exposure` is explicit and mandatory precisely because of the standing
    instruction that the 25 public samples are not a pristine holdout: every
    entry must say plainly whether the request_ids it covers were already
    seen during preparatory research (`prior_research_exposed`, always true
    for the 25 public samples) or are independently constructed
    (`independent_synthetic`, for fixtures in code/evaluation/fixtures/).
    """

    experiment_id: str
    timestamp_iso: str
    commit: str
    request_ids: tuple[str, ...]
    exposure: str  # "prior_research_exposed" | "independent_synthetic"
    report_summary_path: str | None
    notes: str
