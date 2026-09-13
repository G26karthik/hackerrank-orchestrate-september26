"""Builder helpers and the `Fixture` container shared by every scenario in
code/evaluation/fixtures/scenarios.py.

These fixtures are hand-constructed, NOT loaded through `buyorwait.io_load`
-- there is no CSV file behind them. Their `raw` fields are therefore a
best-effort string rendering for provenance/debugging only, not something
that round-trips through the real loader's parsing. Every synthetic id is
prefixed `synthetic_` (`synthetic_user_01`, `synthetic_request_01`, ...) so
it can never collide with a real dataset id and is unmistakable in any
report or log it appears in.

Every fixture's `expected` values are derived by hand from the rules in
evaluation/contract.md, with the arithmetic shown in each scenario's
docstring -- never copied from any production module output (there is no
planner yet to copy from) and never from the 25 public sample labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from buyorwait.schemas import (
    AffordabilityStatus,
    Currency,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExpenseCategory,
    Flexibility,
    PaymentOption,
    PaymentOptionMethod,
    PaymentPreference,
    PriorityCategory,
    Profile,
    RecommendedPaymentMethod,
    Request,
    RequestType,
)


def _raw(**fields: Any) -> MappingProxyType:
    return MappingProxyType({k: str(v) for k, v in fields.items()})


def make_profile(
    *,
    user_id: str,
    home_currency: Currency = Currency.USD,
    current_available_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    financial_priorities: frozenset[PriorityCategory] = frozenset({PriorityCategory.EMERGENCY_SAVINGS}),
    expense_categories_to_protect: frozenset[ExpenseCategory] = frozenset({ExpenseCategory.RENT}),
    expense_categories_user_is_willing_to_reduce: frozenset[ExpenseCategory] = frozenset(),
    expense_categories_user_is_willing_to_stop: frozenset[ExpenseCategory] = frozenset(),
    payment_methods_user_will_consider: frozenset[PaymentPreference],
    max_installment_months: int | None = None,
) -> Profile:
    return Profile(
        user_id=user_id,
        home_currency=home_currency,
        current_available_balance=current_available_balance,
        minimum_balance_to_keep=minimum_balance_to_keep,
        financial_priorities=financial_priorities,
        expense_categories_to_protect=expense_categories_to_protect,
        expense_categories_user_is_willing_to_reduce=expense_categories_user_is_willing_to_reduce,
        expense_categories_user_is_willing_to_stop=expense_categories_user_is_willing_to_stop,
        payment_methods_user_will_consider=payment_methods_user_will_consider,
        max_installment_months=max_installment_months,
        raw=_raw(
            user_id=user_id, home_currency=home_currency.value,
            current_available_balance=current_available_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
        ),
    )


def make_request(
    *,
    request_id: str,
    user_id: str,
    request_date: date,
    request_type: RequestType = RequestType.PURCHASE,
    requested_amount: Decimal,
    desired_completion_date: date,
    allows_partial_payment: bool = False,
    request_text: str = "synthetic fixture request",
) -> Request:
    return Request(
        request_id=request_id,
        user_id=user_id,
        request_date=request_date,
        request_type=request_type,
        requested_amount=requested_amount,
        desired_completion_date=desired_completion_date,
        allows_partial_payment=allows_partial_payment,
        request_text=request_text,
        raw=_raw(request_id=request_id, user_id=user_id, requested_amount=requested_amount),
    )


def make_event(
    *,
    event_id: str,
    user_id: str,
    event_type: EventType = EventType.EXPENSE,
    description: str = "synthetic event",
    category: ExpenseCategory,
    direction: Direction,
    amount: Decimal | None,
    currency: Currency = Currency.USD,
    event_date: date,
    settlement_date: date | None = None,
    status: EventStatus = EventStatus.SETTLED,
    linked_event_id: str | None = None,
    flexibility: Flexibility = Flexibility.FIXED,
    minimum_allowed_amount: Decimal | None = None,
) -> Event:
    return Event(
        event_id=event_id,
        user_id=user_id,
        event_type=event_type,
        description=description,
        category=category,
        direction=direction,
        amount=amount,
        currency=currency,
        event_date=event_date,
        settlement_date=settlement_date if settlement_date is not None else event_date,
        status=status,
        linked_event_id=linked_event_id,
        flexibility=flexibility,
        minimum_allowed_amount=minimum_allowed_amount,
        raw=_raw(event_id=event_id, user_id=user_id, amount=amount if amount is not None else ""),
    )


def make_option(
    *,
    payment_option_id: str,
    request_id: str,
    payment_method: PaymentOptionMethod,
    payment_amount: Decimal,
    number_of_payments: int,
    first_payment_date: date,
    payment_frequency_days: int | None = None,
    financing_fee: Decimal = Decimal("0"),
    total_payable_amount: Decimal,
) -> PaymentOption:
    return PaymentOption(
        payment_option_id=payment_option_id,
        request_id=request_id,
        payment_method=payment_method,
        payment_amount=payment_amount,
        number_of_payments=number_of_payments,
        first_payment_date=first_payment_date,
        payment_frequency_days=payment_frequency_days,
        financing_fee=financing_fee,
        total_payable_amount=total_payable_amount,
        raw=_raw(payment_option_id=payment_option_id, request_id=request_id, payment_amount=payment_amount),
    )


@dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    """The hand-derived expected values for one fixture. `amount_safe_to_pay`
    and `chosen_payment_option_id` are None when the scenario does not need
    to pin them down exactly (e.g. a ranking fixture cares which option wins,
    not the exact capacity number); `earliest_date_for_full_payment` and the
    two enum fields are required of every fixture -- they are always
    derivable from the same reasoning that produces the rest of the row."""

    affordability_status: AffordabilityStatus
    recommended_payment_method: RecommendedPaymentMethod
    earliest_date_for_full_payment: date | None
    amount_safe_to_pay: Decimal | None = None
    chosen_payment_option_id: str | None = None
    plan_total: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Fixture:
    fixture_id: str
    title: str
    rationale: str  # the hand-worked arithmetic and rule citations
    profile: Profile
    request: Request
    events: tuple[Event, ...]
    options: tuple[PaymentOption, ...]
    expected: ExpectedOutcome
