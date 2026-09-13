"""Exact CSV serialization of a finished output row.

This module trusts its input completely: `OutputRow` is assumed to already
satisfy every rule in evaluation/contract.md section 2.3 (0 <=
amount_safe_to_pay <= requested_amount, a matching installment option, a
partial_payment plan that sums correctly, at most three well-formed spending
changes, and so on). Enforcing those rules is the job of whichever module
constructs an `OutputRow` -- the future planner and explain modules in
Stage 3/4 -- and of `code/evaluation/metrics.py`'s well-formedness checks,
which run independently against the CSV this module produces. Keeping
serialization free of business logic means a formatting bug can never masquerade
as a business-rule bug, and vice versa.

`REQUIRED_COLUMNS` and the CRLF line terminator match `dataset/output.csv`
exactly (evaluation/contract.md section 2.1): the reference template is
251 CRLF-terminated lines, and this writer reproduces that convention rather
than the platform default, so a byte-level diff against the template's line
endings is never itself a source of doubt about whether the file is well-formed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .csv_format import PlanEntry, SpendingChange, serialize_payment_plan, serialize_spending_changes
from .decimal_utils import format_capacity_amount
from .schemas import AffordabilityStatus, RecommendedPaymentMethod

REQUIRED_COLUMNS = (
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
)


@dataclass(frozen=True, slots=True)
class OutputRow:
    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: AffordabilityStatus
    recommended_payment_method: RecommendedPaymentMethod
    payment_plan: tuple[PlanEntry, ...]
    earliest_date_for_full_payment: date | None
    spending_changes_needed: tuple[SpendingChange, ...]
    decision_explanation: str


def to_csv_dict(row: OutputRow) -> dict[str, str]:
    """One `OutputRow` -> one CSV row, as a dict keyed by `REQUIRED_COLUMNS`."""
    return {
        "request_id": row.request_id,
        "amount_safe_to_pay": format_capacity_amount(row.amount_safe_to_pay),
        "affordability_status": row.affordability_status.value,
        "recommended_payment_method": row.recommended_payment_method.value,
        "payment_plan": serialize_payment_plan(row.payment_plan),
        "earliest_date_for_full_payment": (
            row.earliest_date_for_full_payment.isoformat()
            if row.earliest_date_for_full_payment is not None
            else ""
        ),
        "spending_changes_needed": serialize_spending_changes(row.spending_changes_needed),
        "decision_explanation": row.decision_explanation,
    }


def write_output_csv(path: str | Path, rows: Iterable[OutputRow]) -> None:
    """Write `rows` to `path` with the exact header, column order, and CRLF
    line endings of `dataset/output.csv`. Does not sort or deduplicate `rows`
    -- ordering and completeness are the caller's responsibility, checked
    independently by `code/evaluation/metrics.py`'s strict join."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REQUIRED_COLUMNS, lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(to_csv_dict(row))
