"""Typed, immutable models for every participant-facing dataset row.

Design rules, all deliberate:

  * Every dataclass is `frozen=True, slots=True`. A loaded record cannot be mutated
    after construction ("Keep participant inputs immutable" -- Stage 2 instruction).
  * Money is `Decimal`, never `float`. Dates are `datetime.date` / `datetime.datetime`,
    never strings, once past the loader boundary.
  * Every record keeps `raw: Mapping[str, str]` -- the original CSV row, as an
    immutable mapping -- so any typed field can be traced back to its exact source
    text ("preserve original source rows").
  * Enums are closed sets taken from evaluation/inventory.md, which fully profiled
    this fixed, hash-verified dataset. An unrecognized value is a parsing bug or a
    corrupted file, not legitimate unseen data -- see io_load.py module docstring
    for why that justifies a hard failure instead of a lenient fallback.
  * `Request` (built from requests.csv, and from sample_requests.csv's first 8
    columns only) and `SampleLabel` (built from sample_requests.csv's last 7
    columns only) are deliberately different types with no shared base and no
    field overlap. There is no code path by which an output field can reach a
    `Request` object. This is the type-level enforcement of "create input-only
    sample request objects that exclude every expected output field" and "keep
    public sample output fields outside prediction inputs".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


def freeze_row(row: Mapping[str, str]) -> Mapping[str, str]:
    """Wrap a CSV row in a read-only mapping so it can be attached to a frozen
    dataclass as verifiable provenance without becoming a mutation surface."""
    return MappingProxyType(dict(row))


# ---------------------------------------------------------------------------
# Closed enumerations. Membership counts are cited from evaluation/inventory.md
# so a reviewer can check this file against that one without re-deriving it.
# ---------------------------------------------------------------------------


class Currency(StrEnum):
    """5 values -- inventory.md S2.2 / S4. Spec-confirmed (problem_statement.md)."""

    INR = "INR"
    ZAR = "ZAR"
    IDR = "IDR"
    USD = "USD"
    EUR = "EUR"


class RequestType(StrEnum):
    """9 values -- spec-confirmed verbatim in problem_statement.md "Input schema"."""

    PURCHASE = "purchase"
    TRAVEL = "travel"
    EDUCATION = "education"
    FAMILY_TRANSFER = "family_transfer"
    DEBT_REPAYMENT = "debt_repayment"
    INVESTMENT = "investment"
    HOUSING = "housing"
    EMERGENCY_EXPENSE = "emergency_expense"
    OTHER = "other"


class EventType(StrEnum):
    """8 values -- inventory.md S5.2. Observed only; not named in the spec."""

    EXPENSE = "expense"
    SUBSCRIPTION = "subscription"
    INCOME = "income"
    DEBT_PAYMENT = "debt_payment"
    INVESTMENT_PURCHASE = "investment_purchase"
    REFUND = "refund"
    INVESTMENT_VALUATION = "investment_valuation"
    INVESTMENT_SALE = "investment_sale"


class Direction(StrEnum):
    """3 values -- inventory.md S5.2. The rules speak of "pending debits" and
    "non-cash" investment value directly (AGENTS.md 6.1/6.3), so this is
    treated as spec-anchored even though the literal enum isn't spelled out."""

    DEBIT = "debit"
    CREDIT = "credit"
    NON_CASH = "non_cash"


class EventStatus(StrEnum):
    """6 values -- problem_statement.md "90-Day Safety Check" names all six
    ("Ignore pending credits... failed or cancelled... duplicate... unrealized"),
    so this enum is spec-anchored."""

    SETTLED = "settled"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNREALIZED = "unrealized"


class Flexibility(StrEnum):
    """4 values -- inventory.md S5.2. Observed only; the spec speaks generically
    of "recurring expenses marked as flexible" without naming these four."""

    FIXED = "fixed"
    REDUCIBLE = "reducible"
    STOPPABLE = "stoppable"
    REDUCIBLE_OR_STOPPABLE = "reducible_or_stoppable"


class ExpenseCategory(StrEnum):
    """22 values -- inventory.md S5.2 category counts. Shared vocabulary between
    `financial_events.category` and the profile's protect/reduce/stop lists."""

    GROCERIES = "groceries"
    TRANSPORT = "transport"
    DINING = "dining"
    SALARY = "salary"
    UTILITIES = "utilities"
    RENT = "rent"
    CLOUD_STORAGE = "cloud_storage"
    SHOPPING = "shopping"
    STREAMING = "streaming"
    DEBT_REPAYMENT = "debt_repayment"
    ENTERTAINMENT = "entertainment"
    INSURANCE = "insurance"
    MUSIC_SUBSCRIPTION = "music_subscription"
    HEALTHCARE = "healthcare"
    DELIVERY_MEMBERSHIP = "delivery_membership"
    EDUCATION = "education"
    HOUSING = "housing"
    GYM = "gym"
    FAMILY_SUPPORT = "family_support"
    INVESTMENT = "investment"
    WORK_EXPENSE = "work_expense"
    WINDFALL = "windfall"


class PriorityCategory(StrEnum):
    """8 values -- inventory.md S4. A DIFFERENT vocabulary from ExpenseCategory:
    it includes retirement_investment / emergency_savings / travel, which are
    never `financial_events.category` values, and excludes most expense
    categories. Conflating the two would be a real bug, not a style choice."""

    EDUCATION = "education"
    DEBT_REPAYMENT = "debt_repayment"
    FAMILY_SUPPORT = "family_support"
    RETIREMENT_INVESTMENT = "retirement_investment"
    EMERGENCY_SAVINGS = "emergency_savings"
    HEALTHCARE = "healthcare"
    TRAVEL = "travel"
    HOUSING = "housing"


class PaymentPreference(StrEnum):
    """3 values -- `financial_profiles.payment_methods_user_will_consider`."""

    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"


class PaymentOptionMethod(StrEnum):
    """2 values only -- `request_payment_options.payment_method`. There are no
    `partial_payment` rows in this file (inventory.md S6); partial payment is
    always constructed directly from the rules (S-10), never from an option."""

    FULL_PAYMENT = "full_payment"
    INSTALLMENTS = "installments"


class AffordabilityStatus(StrEnum):
    """4 values -- the required output enum (problem_statement.md)."""

    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class RecommendedPaymentMethod(StrEnum):
    """5 values -- the required output enum (problem_statement.md)."""

    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class MessageSourceType(StrEnum):
    """5 values -- `messages.source_type` (inventory.md S9)."""

    EMPLOYER = "employer"
    SERVICE_PROVIDER = "service_provider"
    BANK = "bank"
    MERCHANT = "merchant"
    FINANCIAL_SERVICE = "financial_service"


# ---------------------------------------------------------------------------
# Records. One dataclass per dataset row shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Profile:
    user_id: str
    home_currency: Currency
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: frozenset[PriorityCategory]
    expense_categories_to_protect: frozenset[ExpenseCategory]
    expense_categories_user_is_willing_to_reduce: frozenset[ExpenseCategory]
    expense_categories_user_is_willing_to_stop: frozenset[ExpenseCategory]
    payment_methods_user_will_consider: frozenset[PaymentPreference]
    max_installment_months: int | None
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    user_id: str
    event_type: EventType
    description: str
    category: ExpenseCategory
    direction: Direction
    amount: Decimal | None  # None only for the 16 rows resolved via an image (S-21)
    currency: Currency
    event_date: date
    settlement_date: date | None  # None only for non_cash / unrealized rows
    status: EventStatus
    linked_event_id: str | None
    flexibility: Flexibility
    minimum_allowed_amount: Decimal | None  # populated only when reducible(-or-stoppable)
    raw: Mapping[str, str]

    def effective_date(self) -> date:
        """The date this event's cash effect lands: settlement_date when the
        event has one, else event_date. Matches AGENTS.md 6.1's join guidance
        and every timing measurement in evaluation/inventory.md section 5.3."""
        return self.settlement_date if self.settlement_date is not None else self.event_date


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    rate_date: date
    from_currency: Currency
    to_currency: Currency
    rate: Decimal
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Request:
    """Built ONLY from the 8 documented input columns of requests.csv (and, for
    the 25 public samples, only the first 8 columns of sample_requests.csv). No
    output field can reach this type -- see the module docstring."""

    request_id: str
    user_id: str
    request_date: date
    request_type: RequestType
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SampleLabel:
    """Built ONLY from the 7 output columns of sample_requests.csv, plus the
    join key. Used exclusively by the evaluator (code/evaluation) -- never
    passed to any prediction code path. This is the type-level enforcement of
    "keep public sample output fields outside prediction inputs".

    `payment_plan_raw` and `spending_changes_needed_raw` are kept as the exact
    source strings; code/buyorwait/csv_format.py owns parsing them into typed
    structures, shared with the writer that produces the same strings."""

    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: AffordabilityStatus
    recommended_payment_method: RecommendedPaymentMethod
    payment_plan_raw: str
    earliest_date_for_full_payment: date | None
    spending_changes_needed_raw: str
    decision_explanation: str
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: PaymentOptionMethod
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None  # None only for full_payment rows
    financing_fee: Decimal
    total_payable_amount: Decimal
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: datetime
    source_type: MessageSourceType
    message_text: str
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Image:
    image_id: str
    user_id: str
    request_id: str
    related_event_id: str
    raw: Mapping[str, str]

    def path(self, media_root: str = "dataset/media/images") -> str:
        """Resolve the on-disk path per AGENTS.md 6.1 / problem_statement.md
        "Files provided": `<image_id>` -> `<media_root>/<image_id>.png`."""
        return f"{media_root}/{self.image_id}.png"


# ---------------------------------------------------------------------------
# Indexes and the top-level Dataset container.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Dataset:
    """Everything the deterministic pipeline needs, fully loaded, validated, and
    indexed. Every collection is a tuple or a MappingProxyType: read-only end to
    end, so no later stage can accidentally mutate a participant input.

    `requests` and `sample_requests` are BOTH `Request` objects (input-only, 8
    fields) -- their `request_id`s are disjoint (verified in io_load.py), so they
    may safely be looked up through the single `all_requests_by_id` index without
    ever exposing which file a given request came from to prediction code. Only
    `evaluation` code should ever touch `sample_labels_by_id`.
    """

    requests: tuple[Request, ...]
    sample_requests: tuple[Request, ...]
    sample_labels: tuple[SampleLabel, ...]
    profiles: tuple[Profile, ...]
    events: tuple[Event, ...]
    exchange_rates: tuple[ExchangeRate, ...]
    payment_options: tuple[PaymentOption, ...]
    messages: tuple[Message, ...]
    images: tuple[Image, ...]

    # indexes -- all MappingProxyType, all built once in io_load.py
    profiles_by_user: Mapping[str, Profile]
    all_requests_by_id: Mapping[str, Request]  # requests.csv UNION sample_requests.csv input columns
    sample_labels_by_id: Mapping[str, SampleLabel]  # evaluator-only; see class docstring
    events_by_id: Mapping[str, Event]
    events_by_user: Mapping[str, tuple[Event, ...]]  # sorted by effective_date
    options_by_id: Mapping[str, PaymentOption]
    options_by_request: Mapping[str, tuple[PaymentOption, ...]]
    messages_by_id: Mapping[str, Message]
    messages_by_user: Mapping[str, tuple[Message, ...]]
    messages_by_request: Mapping[str, tuple[Message, ...]]
    messages_by_event: Mapping[str, tuple[Message, ...]]
    images_by_id: Mapping[str, Image]
    images_by_request: Mapping[str, tuple[Image, ...]]
    images_by_event: Mapping[str, tuple[Image, ...]]
    fx_rates: Mapping[tuple[date, Currency, Currency], Decimal]

    source_hashes: Mapping[str, str]  # relative path -> sha256 hex digest
    warnings: tuple[str, ...]  # soft, non-fatal pattern-deviation notices
