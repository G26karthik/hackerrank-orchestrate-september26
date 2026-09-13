"""The typed input layer: CSV loading, validation, indexing, and source hashing.

Why enums fail loudly instead of degrading gracefully
------------------------------------------------------
`dataset/requests.csv` and every other participant-facing file are fixed,
already fully delivered, and fully profiled in evaluation/inventory.md -- there
is no future "unseen input file" coming later in this challenge; the only thing
withheld is the *ground-truth labels*, not the input schema. Every enum in
schemas.py is the exact closed set that inventory.md already found by reading
every row. So when a value doesn't match, that is either a bug in this loader
or a corrupted/edited source file, and the honest response is to say so loudly
and stop, not to invent a fallback category. This module never treats an
unrecognized enum value, a blank required field, or a broken reference as a
warning: those raise. Only the *dataset-shape observations* recorded as O-*
items in evaluation/assumptions.md (payment-option arithmetic, exactly-one
full_payment row, 2-4 options per request, non-decreasing deadlines) are
treated as soft, collected as `Dataset.warnings` -- because nothing in the
specification actually requires them to hold, even though they held for every
row inventory.md checked.

Validation runs in two passes so a single call surfaces every problem at once
instead of forcing a fix-rerun-fix loop:
  1. parse every row of every file (collect ALL parse errors before deciding
     whether to proceed);
  2. cross-file structural validation -- unique IDs, user ownership, and
     referential integrity (collect ALL of these before raising too).
A `DatasetValidationError` lists every failure found in one message.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .decimal_utils import DecimalParseError, parse_decimal, parse_optional_decimal
from .fx import build_fx_index
from .schemas import (
    AffordabilityStatus,
    Currency,
    Dataset,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExchangeRate,
    ExpenseCategory,
    Flexibility,
    Image,
    Message,
    MessageSourceType,
    PaymentOption,
    PaymentOptionMethod,
    PaymentPreference,
    PriorityCategory,
    RecommendedPaymentMethod,
    Request,
    RequestType,
    SampleLabel,
    Profile,
    freeze_row,
)

# ---------------------------------------------------------------------------
# Source hashes, recorded in evaluation/contract.md section 1.3 (Stage 1,
# 2026-09-12). Cross-checked at every load so silent dataset drift is caught
# instead of silently changing what the pipeline assumes about its inputs.
# ---------------------------------------------------------------------------

EXPECTED_CSV_HASHES: Mapping[str, str] = MappingProxyType(
    {
        "requests.csv": "13663d50b7098b28a8c087a02eb085041260999707adade5230d29f1c2e6595d",
        "sample_requests.csv": "117bf2ab9e5f0054bae48afe8506f5daa35929559cb771f2c27dd4fe18da62f6",
        "financial_profiles.csv": "fa173608f8ec99c8d9d633eace762695aeaa2d276a509989f0edd8e123c07964",
        "financial_events.csv": "b6c3f43a8ad3a80ca11c72cce6f2818eea06621a3582d2851886fd9127b1229d",
        "request_payment_options.csv": "4922c56f10c06698d24b86b8a43580cbc6bc6ee44c95936c3037878005980c40",
        "exchange_rates.csv": "ff56e9feb482f909837dc309f52f8de5b167d9d6685a2ee8e8fd807639658a04",
        "messages.csv": "7b9db27a4546a850a76d3475ebf65de80fb9fe374e26d469586f62f537eac9a6",
        "images.csv": "6b5428565ca98e4b71e182f8a8fa3fd3013727399bdea847f3e4a3d2c129dfc9",
        "output.csv": "e6e6f4aae1eed6d1c178fd3daca7b5ad82cc9c1461650969c373b4dedab43baf",
    }
)


class DatasetValidationError(Exception):
    """All validation failures found in one call, never just the first one."""

    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        summary = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"{len(errors)} dataset validation error(s):\n{summary}")


class _Errors:
    """Tiny accumulator so every loader function can keep parsing past a bad
    row instead of raising on the first one, then report everything at once."""

    def __init__(self) -> None:
        self._items: list[str] = []

    def add(self, message: str) -> None:
        self._items.append(message)

    def extend(self, other: "_Errors") -> None:
        self._items.extend(other._items)

    def raise_if_any(self) -> None:
        if self._items:
            raise DatasetValidationError(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    @property
    def items(self) -> list[str]:
        return list(self._items)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _parse_bool_strict(raw: str, *, context: str, errors: _Errors) -> bool | None:
    text = raw.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    errors.add(f"{context}: allows_partial_payment must be 'true' or 'false', got {raw!r}")
    return None


def _parse_pipe_set(raw: str, enum_cls, *, context: str, field_name: str, errors: _Errors) -> frozenset:
    text = raw.strip()
    if text == "":
        return frozenset()
    out = set()
    for token in text.split("|"):
        token = token.strip()
        try:
            out.add(enum_cls(token))
        except ValueError:
            errors.add(f"{context}: unrecognized {field_name} token {token!r}")
    return frozenset(out)


# ---------------------------------------------------------------------------
# Per-file loaders. Each returns (records, errors); callers combine errors
# across every file before deciding whether to raise.
# ---------------------------------------------------------------------------


def load_profiles(path: Path) -> tuple[tuple[Profile, ...], _Errors]:
    errors = _Errors()
    out: list[Profile] = []
    for row in _read_rows(path):
        ctx = f"financial_profiles.csv user_id={row.get('user_id')!r}"
        try:
            max_inst_raw = row["max_installment_months"].strip()
            max_inst = int(max_inst_raw) if max_inst_raw else None
            if max_inst is not None and max_inst <= 0:
                errors.add(f"{ctx}: max_installment_months must be positive, got {max_inst_raw!r}")
                continue
            out.append(
                Profile(
                    user_id=row["user_id"],
                    home_currency=Currency(row["home_currency"]),
                    current_available_balance=parse_decimal(
                        row["current_available_balance"], field="current_available_balance", context=ctx
                    ),
                    minimum_balance_to_keep=parse_decimal(
                        row["minimum_balance_to_keep"], field="minimum_balance_to_keep", context=ctx
                    ),
                    financial_priorities=_parse_pipe_set(
                        row["financial_priorities"], PriorityCategory,
                        context=ctx, field_name="financial_priorities", errors=errors,
                    ),
                    expense_categories_to_protect=_parse_pipe_set(
                        row["expense_categories_to_protect"], ExpenseCategory,
                        context=ctx, field_name="expense_categories_to_protect", errors=errors,
                    ),
                    expense_categories_user_is_willing_to_reduce=_parse_pipe_set(
                        row["expense_categories_user_is_willing_to_reduce"], ExpenseCategory,
                        context=ctx, field_name="expense_categories_user_is_willing_to_reduce", errors=errors,
                    ),
                    expense_categories_user_is_willing_to_stop=_parse_pipe_set(
                        row["expense_categories_user_is_willing_to_stop"], ExpenseCategory,
                        context=ctx, field_name="expense_categories_user_is_willing_to_stop", errors=errors,
                    ),
                    payment_methods_user_will_consider=_parse_pipe_set(
                        row["payment_methods_user_will_consider"], PaymentPreference,
                        context=ctx, field_name="payment_methods_user_will_consider", errors=errors,
                    ),
                    max_installment_months=max_inst,
                    raw=freeze_row(row),
                )
            )
        except (DecimalParseError, ValueError) as exc:
            errors.add(f"{ctx}: {exc}")
    return tuple(out), errors


def load_events(path: Path) -> tuple[tuple[Event, ...], _Errors]:
    errors = _Errors()
    out: list[Event] = []
    for row in _read_rows(path):
        ctx = f"financial_events.csv event_id={row.get('event_id')!r}"
        try:
            settlement_raw = row["settlement_date"].strip()
            linked_raw = row["linked_event_id"].strip()
            out.append(
                Event(
                    event_id=row["event_id"],
                    user_id=row["user_id"],
                    event_type=EventType(row["event_type"]),
                    description=row["description"],
                    category=ExpenseCategory(row["category"]),
                    direction=Direction(row["direction"]),
                    amount=parse_optional_decimal(row["amount"], field="amount", context=ctx),
                    currency=Currency(row["currency"]),
                    event_date=date.fromisoformat(row["event_date"]),
                    settlement_date=date.fromisoformat(settlement_raw) if settlement_raw else None,
                    status=EventStatus(row["status"]),
                    linked_event_id=linked_raw or None,
                    flexibility=Flexibility(row["flexibility"]),
                    minimum_allowed_amount=parse_optional_decimal(
                        row["minimum_allowed_amount"], field="minimum_allowed_amount", context=ctx
                    ),
                    raw=freeze_row(row),
                )
            )
        except (DecimalParseError, ValueError) as exc:
            errors.add(f"{ctx}: {exc}")
    return tuple(out), errors


def load_exchange_rates(path: Path) -> tuple[tuple[ExchangeRate, ...], _Errors]:
    errors = _Errors()
    out: list[ExchangeRate] = []
    for i, row in enumerate(_read_rows(path)):
        ctx = f"exchange_rates.csv row={i}"
        try:
            out.append(
                ExchangeRate(
                    rate_date=date.fromisoformat(row["rate_date"]),
                    from_currency=Currency(row["from_currency"]),
                    to_currency=Currency(row["to_currency"]),
                    rate=parse_decimal(row["rate"], field="rate", context=ctx),
                    raw=freeze_row(row),
                )
            )
        except (DecimalParseError, ValueError) as exc:
            errors.add(f"{ctx}: {exc}")
    return tuple(out), errors


_REQUEST_INPUT_FIELDS = (
    "request_id",
    "user_id",
    "request_date",
    "request_type",
    "requested_amount",
    "desired_completion_date",
    "allows_partial_payment",
    "request_text",
)


def _parse_request_row(row: dict[str, str], errors: _Errors) -> Request | None:
    ctx = f"request_id={row.get('request_id')!r}"
    try:
        allows_partial = _parse_bool_strict(row["allows_partial_payment"], context=ctx, errors=errors)
        if allows_partial is None:
            return None
        return Request(
            request_id=row["request_id"],
            user_id=row["user_id"],
            request_date=date.fromisoformat(row["request_date"]),
            request_type=RequestType(row["request_type"]),
            requested_amount=parse_decimal(row["requested_amount"], field="requested_amount", context=ctx),
            desired_completion_date=date.fromisoformat(row["desired_completion_date"]),
            allows_partial_payment=allows_partial,
            request_text=row["request_text"],
            raw=freeze_row({k: row[k] for k in _REQUEST_INPUT_FIELDS}),
        )
    except (DecimalParseError, ValueError) as exc:
        errors.add(f"{ctx}: {exc}")
        return None


def load_requests(path: Path) -> tuple[tuple[Request, ...], _Errors]:
    errors = _Errors()
    out = []
    for row in _read_rows(path):
        r = _parse_request_row(row, errors)
        if r is not None:
            out.append(r)
    return tuple(out), errors


def load_sample_requests(path: Path) -> tuple[tuple[Request, ...], tuple[SampleLabel, ...], _Errors]:
    """Split every sample_requests.csv row into an input-only `Request` (the
    first 8 columns, byte-for-byte the same shape as requests.csv) and a
    separate `SampleLabel` (the join key plus the 7 output columns). Neither
    object can be reconstructed into the other -- this is the enforcement of
    "create input-only sample request objects that exclude every expected
    output field" and "keep public sample output fields outside prediction
    inputs" at the type level, not just by convention.
    """
    errors = _Errors()
    requests_out: list[Request] = []
    labels_out: list[SampleLabel] = []
    for row in _read_rows(path):
        req = _parse_request_row(row, errors)
        if req is not None:
            requests_out.append(req)

        ctx = f"sample_requests.csv request_id={row.get('request_id')!r}"
        try:
            earliest_raw = row["earliest_date_for_full_payment"].strip()
            labels_out.append(
                SampleLabel(
                    request_id=row["request_id"],
                    amount_safe_to_pay=parse_decimal(
                        row["amount_safe_to_pay"], field="amount_safe_to_pay", context=ctx
                    ),
                    affordability_status=AffordabilityStatus(row["affordability_status"]),
                    recommended_payment_method=RecommendedPaymentMethod(row["recommended_payment_method"]),
                    payment_plan_raw=row["payment_plan"],
                    earliest_date_for_full_payment=date.fromisoformat(earliest_raw) if earliest_raw else None,
                    spending_changes_needed_raw=row["spending_changes_needed"],
                    decision_explanation=row["decision_explanation"],
                    raw=freeze_row(row),
                )
            )
        except (DecimalParseError, ValueError) as exc:
            errors.add(f"{ctx}: {exc}")
    return tuple(requests_out), tuple(labels_out), errors


def load_payment_options(path: Path) -> tuple[tuple[PaymentOption, ...], _Errors]:
    errors = _Errors()
    out: list[PaymentOption] = []
    for row in _read_rows(path):
        ctx = f"request_payment_options.csv payment_option_id={row.get('payment_option_id')!r}"
        try:
            freq_raw = row["payment_frequency_days"].strip()
            out.append(
                PaymentOption(
                    payment_option_id=row["payment_option_id"],
                    request_id=row["request_id"],
                    payment_method=PaymentOptionMethod(row["payment_method"]),
                    payment_amount=parse_decimal(row["payment_amount"], field="payment_amount", context=ctx),
                    number_of_payments=int(row["number_of_payments"]),
                    first_payment_date=date.fromisoformat(row["first_payment_date"]),
                    payment_frequency_days=int(freq_raw) if freq_raw else None,
                    financing_fee=parse_decimal(row["financing_fee"], field="financing_fee", context=ctx),
                    total_payable_amount=parse_decimal(
                        row["total_payable_amount"], field="total_payable_amount", context=ctx
                    ),
                    raw=freeze_row(row),
                )
            )
        except (DecimalParseError, ValueError) as exc:
            errors.add(f"{ctx}: {exc}")
    return tuple(out), errors


def load_messages(path: Path) -> tuple[tuple[Message, ...], _Errors]:
    errors = _Errors()
    out: list[Message] = []
    for row in _read_rows(path):
        ctx = f"messages.csv message_id={row.get('message_id')!r}"
        try:
            sent_at_raw = row["sent_at"].strip().replace("Z", "+00:00")
            out.append(
                Message(
                    message_id=row["message_id"],
                    user_id=row["user_id"],
                    request_id=row["request_id"].strip() or None,
                    related_event_id=row["related_event_id"].strip() or None,
                    sent_at=datetime.fromisoformat(sent_at_raw),
                    source_type=MessageSourceType(row["source_type"]),
                    message_text=row["message_text"],
                    raw=freeze_row(row),
                )
            )
        except ValueError as exc:
            errors.add(f"{ctx}: {exc}")
    return tuple(out), errors


def load_images(path: Path) -> tuple[tuple[Image, ...], _Errors]:
    errors = _Errors()
    out: list[Image] = []
    for row in _read_rows(path):
        ctx = f"images.csv image_id={row.get('image_id')!r}"
        request_id = row["request_id"].strip()
        related_event_id = row["related_event_id"].strip()
        if not request_id or not related_event_id:
            errors.add(f"{ctx}: request_id and related_event_id must both be populated (inventory.md S8)")
            continue
        out.append(
            Image(
                image_id=row["image_id"],
                user_id=row["user_id"],
                request_id=request_id,
                related_event_id=related_event_id,
                raw=freeze_row(row),
            )
        )
    return tuple(out), errors


# ---------------------------------------------------------------------------
# Cross-file structural validation.
# ---------------------------------------------------------------------------


def _check_unique(items: tuple, key, label: str, errors: _Errors) -> None:
    seen: dict = {}
    for item in items:
        k = key(item)
        seen.setdefault(k, 0)
        seen[k] += 1
    for k, count in seen.items():
        if count > 1:
            errors.add(f"duplicate {label} id: {k!r} appears {count} times")


def _validate_structure(
    *,
    profiles: tuple[Profile, ...],
    events: tuple[Event, ...],
    all_requests: tuple[Request, ...],
    options: tuple[PaymentOption, ...],
    messages: tuple[Message, ...],
    images: tuple[Image, ...],
) -> _Errors:
    errors = _Errors()

    _check_unique(profiles, lambda p: p.user_id, "user", errors)
    _check_unique(all_requests, lambda r: r.request_id, "request", errors)
    _check_unique(events, lambda e: e.event_id, "event", errors)
    _check_unique(options, lambda o: o.payment_option_id, "payment_option", errors)
    _check_unique(messages, lambda m: m.message_id, "message", errors)
    _check_unique(images, lambda i: i.image_id, "image", errors)

    profiles_by_user = {p.user_id: p for p in profiles}
    requests_by_id = {r.request_id: r for r in all_requests}
    events_by_id = {e.event_id: e for e in events}

    for r in all_requests:
        if r.user_id not in profiles_by_user:
            errors.add(f"request {r.request_id!r} references unknown user_id {r.user_id!r}")

    for e in events:
        if e.user_id not in profiles_by_user:
            errors.add(f"event {e.event_id!r} references unknown user_id {e.user_id!r}")
        if e.linked_event_id is not None:
            target = events_by_id.get(e.linked_event_id)
            if target is None:
                errors.add(f"event {e.event_id!r} linked_event_id {e.linked_event_id!r} does not exist")
            elif target.user_id != e.user_id:
                errors.add(
                    f"event {e.event_id!r} linked_event_id {e.linked_event_id!r} "
                    f"belongs to a different user ({target.user_id!r} vs {e.user_id!r})"
                )
        if e.amount is None:
            # S-21 prerequisite: a blank amount must be resolvable via an image.
            has_image = any(i.related_event_id == e.event_id for i in images)
            if not has_image:
                errors.add(f"event {e.event_id!r} has a blank amount but no image resolves it (violates S-21)")

    for m in messages:
        if m.user_id not in profiles_by_user:
            errors.add(f"message {m.message_id!r} references unknown user_id {m.user_id!r}")
        if m.request_id is not None:
            req = requests_by_id.get(m.request_id)
            if req is None:
                errors.add(f"message {m.message_id!r} references unknown request_id {m.request_id!r}")
            elif req.user_id != m.user_id:
                errors.add(
                    f"message {m.message_id!r} request_id {m.request_id!r} belongs to a "
                    f"different user ({req.user_id!r} vs {m.user_id!r})"
                )
        if m.related_event_id is not None:
            ev = events_by_id.get(m.related_event_id)
            if ev is None:
                errors.add(f"message {m.message_id!r} references unknown related_event_id {m.related_event_id!r}")
            elif ev.user_id != m.user_id:
                errors.add(
                    f"message {m.message_id!r} related_event_id {m.related_event_id!r} belongs to a "
                    f"different user ({ev.user_id!r} vs {m.user_id!r})"
                )

    for img in images:
        if img.user_id not in profiles_by_user:
            errors.add(f"image {img.image_id!r} references unknown user_id {img.user_id!r}")
        req = requests_by_id.get(img.request_id)
        if req is None:
            errors.add(f"image {img.image_id!r} references unknown request_id {img.request_id!r}")
        elif req.user_id != img.user_id:
            errors.add(
                f"image {img.image_id!r} request_id {img.request_id!r} belongs to a "
                f"different user ({req.user_id!r} vs {img.user_id!r})"
            )
        ev = events_by_id.get(img.related_event_id)
        if ev is None:
            errors.add(f"image {img.image_id!r} references unknown related_event_id {img.related_event_id!r}")
        elif ev.user_id != img.user_id:
            errors.add(
                f"image {img.image_id!r} related_event_id {img.related_event_id!r} belongs to a "
                f"different user ({ev.user_id!r} vs {img.user_id!r})"
            )

    for o in options:
        if o.request_id not in requests_by_id:
            errors.add(f"payment_option {o.payment_option_id!r} references unknown request_id {o.request_id!r}")

    return errors


_MONEY_TOLERANCE = Decimal("0.02")  # matches the tolerance Stage 1's inventory used


def _soft_warnings(
    *,
    all_requests: tuple[Request, ...],
    options: tuple[PaymentOption, ...],
) -> tuple[str, ...]:
    """Dataset-shape observations (O-* in assumptions.md), not spec rules.
    Collected, never raised."""
    warnings: list[str] = []
    requests_by_id = {r.request_id: r for r in all_requests}
    options_by_request: dict[str, list[PaymentOption]] = {}
    for o in options:
        options_by_request.setdefault(o.request_id, []).append(o)

    for req in all_requests:
        if req.desired_completion_date < req.request_date:
            warnings.append(
                f"O-check: request {req.request_id!r} desired_completion_date "
                f"{req.desired_completion_date} is before request_date {req.request_date}"
            )
        opts = options_by_request.get(req.request_id, [])
        if not (2 <= len(opts) <= 4):
            warnings.append(f"O-check: request {req.request_id!r} has {len(opts)} payment options (expected 2-4)")
        full_opts = [o for o in opts if o.payment_method == PaymentOptionMethod.FULL_PAYMENT]
        if len(full_opts) != 1:
            warnings.append(
                f"O-check: request {req.request_id!r} has {len(full_opts)} full_payment options (expected 1)"
            )
        else:
            fo = full_opts[0]
            if fo.payment_amount != req.requested_amount:
                warnings.append(
                    f"O-check: request {req.request_id!r} full_payment amount "
                    f"{fo.payment_amount} != requested_amount {req.requested_amount}"
                )
            if fo.number_of_payments != 1:
                warnings.append(f"O-check: request {req.request_id!r} full_payment option has n != 1")
            if fo.first_payment_date != req.request_date:
                warnings.append(
                    f"O-check: request {req.request_id!r} full_payment first_payment_date "
                    f"{fo.first_payment_date} != request_date {req.request_date}"
                )

    for o in options:
        expected_total = o.payment_amount * o.number_of_payments
        if abs(expected_total - o.total_payable_amount) > _MONEY_TOLERANCE:
            warnings.append(
                f"O-check: option {o.payment_option_id!r} payment_amount*n={expected_total} "
                f"!= total_payable_amount={o.total_payable_amount}"
            )
        req = requests_by_id.get(o.request_id)
        if req is not None:
            expected_total2 = req.requested_amount + o.financing_fee
            if abs(expected_total2 - o.total_payable_amount) > _MONEY_TOLERANCE:
                warnings.append(
                    f"O-check: option {o.payment_option_id!r} requested_amount+fee={expected_total2} "
                    f"!= total_payable_amount={o.total_payable_amount}"
                )

    return tuple(warnings)


# ---------------------------------------------------------------------------
# Top-level entry point.
# ---------------------------------------------------------------------------


def verify_csv_hashes(dataset_dir: Path, expected: Mapping[str, str] = EXPECTED_CSV_HASHES) -> tuple[str, ...]:
    """Return a tuple of mismatch descriptions (empty when every file matches
    its Stage-1-recorded hash). Never raises by itself -- `build_dataset`
    decides whether a mismatch is fatal."""
    mismatches = []
    for name, expected_hash in expected.items():
        actual = sha256_file(dataset_dir / name)
        if actual != expected_hash:
            mismatches.append(f"{name}: expected sha256 {expected_hash}, got {actual}")
    return tuple(mismatches)


def build_dataset(
    dataset_dir: str | Path,
    *,
    verify_hashes: bool = True,
    expected_hashes: Mapping[str, str] = EXPECTED_CSV_HASHES,
) -> Dataset:
    """Load, validate, and index every participant-facing file under
    `dataset_dir`. Raises `DatasetValidationError` (parse errors, broken
    references, or -- when `verify_hashes` is True -- a hash mismatch against
    the Stage-1 recorded values) rather than returning a partially-valid
    `Dataset`. Soft, non-fatal pattern observations are returned on
    `Dataset.warnings` instead of raised.
    """
    dataset_dir = Path(dataset_dir)
    errors = _Errors()

    if verify_hashes:
        mismatches = verify_csv_hashes(dataset_dir, expected_hashes)
        for m in mismatches:
            errors.add(f"source hash mismatch: {m}")
        # A hash mismatch means every downstream assumption in this project's
        # evaluation/ documents may be describing a different file. Fail before
        # even attempting to parse rows on top of it.
        errors.raise_if_any()

    profiles, e1 = load_profiles(dataset_dir / "financial_profiles.csv")
    events, e2 = load_events(dataset_dir / "financial_events.csv")
    rates, e3 = load_exchange_rates(dataset_dir / "exchange_rates.csv")
    requests, e4 = load_requests(dataset_dir / "requests.csv")
    sample_requests, sample_labels, e5 = load_sample_requests(dataset_dir / "sample_requests.csv")
    options, e6 = load_payment_options(dataset_dir / "request_payment_options.csv")
    messages, e7 = load_messages(dataset_dir / "messages.csv")
    images, e8 = load_images(dataset_dir / "images.csv")

    for e in (e1, e2, e3, e4, e5, e6, e7, e8):
        errors.extend(e)
    errors.raise_if_any()  # stop before cross-file checks if any row failed to parse

    all_requests = requests + sample_requests
    struct_errors = _validate_structure(
        profiles=profiles,
        events=events,
        all_requests=all_requests,
        options=options,
        messages=messages,
        images=images,
    )
    struct_errors.raise_if_any()

    warnings = _soft_warnings(all_requests=all_requests, options=options)

    profiles_by_user = MappingProxyType({p.user_id: p for p in profiles})
    all_requests_by_id = MappingProxyType({r.request_id: r for r in all_requests})
    sample_labels_by_id = MappingProxyType({s.request_id: s for s in sample_labels})
    events_by_id = MappingProxyType({e.event_id: e for e in events})

    events_by_user_mut: dict[str, list[Event]] = {}
    for e in events:
        events_by_user_mut.setdefault(e.user_id, []).append(e)
    events_by_user = MappingProxyType(
        {u: tuple(sorted(v, key=lambda e: e.effective_date())) for u, v in events_by_user_mut.items()}
    )

    options_by_id = MappingProxyType({o.payment_option_id: o for o in options})
    options_by_request_mut: dict[str, list[PaymentOption]] = {}
    for o in options:
        options_by_request_mut.setdefault(o.request_id, []).append(o)
    options_by_request = MappingProxyType({k: tuple(v) for k, v in options_by_request_mut.items()})

    messages_by_id = MappingProxyType({m.message_id: m for m in messages})
    messages_by_user_mut: dict[str, list[Message]] = {}
    messages_by_request_mut: dict[str, list[Message]] = {}
    messages_by_event_mut: dict[str, list[Message]] = {}
    for m in messages:
        messages_by_user_mut.setdefault(m.user_id, []).append(m)
        if m.request_id is not None:
            messages_by_request_mut.setdefault(m.request_id, []).append(m)
        if m.related_event_id is not None:
            messages_by_event_mut.setdefault(m.related_event_id, []).append(m)
    messages_by_user = MappingProxyType({k: tuple(v) for k, v in messages_by_user_mut.items()})
    messages_by_request = MappingProxyType({k: tuple(v) for k, v in messages_by_request_mut.items()})
    messages_by_event = MappingProxyType({k: tuple(v) for k, v in messages_by_event_mut.items()})

    images_by_id = MappingProxyType({i.image_id: i for i in images})
    images_by_request_mut: dict[str, list[Image]] = {}
    images_by_event_mut: dict[str, list[Image]] = {}
    for i in images:
        images_by_request_mut.setdefault(i.request_id, []).append(i)
        images_by_event_mut.setdefault(i.related_event_id, []).append(i)
    images_by_request = MappingProxyType({k: tuple(v) for k, v in images_by_request_mut.items()})
    images_by_event = MappingProxyType({k: tuple(v) for k, v in images_by_event_mut.items()})

    fx_rates = MappingProxyType(dict(build_fx_index(rates)))

    source_hashes = MappingProxyType(
        {name: sha256_file(dataset_dir / name) for name in EXPECTED_CSV_HASHES}
    )

    return Dataset(
        requests=requests,
        sample_requests=sample_requests,
        sample_labels=sample_labels,
        profiles=profiles,
        events=events,
        exchange_rates=rates,
        payment_options=options,
        messages=messages,
        images=images,
        profiles_by_user=profiles_by_user,
        all_requests_by_id=all_requests_by_id,
        sample_labels_by_id=sample_labels_by_id,
        events_by_id=events_by_id,
        events_by_user=events_by_user,
        options_by_id=options_by_id,
        options_by_request=options_by_request,
        messages_by_id=messages_by_id,
        messages_by_user=messages_by_user,
        messages_by_request=messages_by_request,
        messages_by_event=messages_by_event,
        images_by_id=images_by_id,
        images_by_request=images_by_request,
        images_by_event=images_by_event,
        fx_rates=fx_rates,
        source_hashes=source_hashes,
        warnings=warnings,
    )
