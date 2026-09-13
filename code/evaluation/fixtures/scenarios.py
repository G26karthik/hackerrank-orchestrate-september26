"""Eight independent, hand-derived scenario fixtures covering every category
named in the Stage 2 instruction. None of these numbers are copied from the
25 public samples or from any production module (there is no planner yet to
copy from) -- every expected value is worked out by hand from
evaluation/contract.md's rules, and every arithmetic claim in a docstring
here is checked against `buyorwait.simulator` / `buyorwait.independent_verifier`
in tests/test_fixtures.py, which runs the SAME rules-engine (not a copy of
one) against these exact numbers.

All synthetic ids are prefixed `synthetic_` so they can never collide with a
real dataset id in any report, cache, or log.

Fixture index:
  FIX-01  full-payment capacity exists, but full_payment is not an accepted
          method -- an eligible installment option must be used instead
          (mirrors the real sample request_12's shape; evaluation/inventory.md O-26)
  FIX-02  a shortfall that ONLY closes if a specific permitted event is
          stopped; amount_safe_to_pay and earliest_date_for_full_payment are
          BOTH measured before that change (S-03, S-06), so earliest_date is
          genuinely empty even though the row is affordable_with_plan
  FIX-03a exact two-payment partial plan, completing before the deadline
  FIX-03b the same shortfall, but the deadline falls before the date full
          capacity arrives -- partial_payment becomes ineligible, and the
          row lands on the U-STATUS-1 boundary (affordable_later + not_recommended)
  FIX-04  two installment options, same schedule shape, different total
          cost -- S-14 rule 3 (minimize total paid) must pick the cheaper one
  FIX-05  two installment options tied on total cost -- S-14 rule 5 (fewer
          payments) must decide, and the fixture's ids are assigned so that
          the WRONG rule (S-14 rule 6, lowest id) would pick the other option
  FIX-06  a reducible expense whose category is ALSO in the user's protected
          list -- S-15 says protection wins; a rule-check fixture, not a
          full plan (see `RuleCheckFixture` below)
  FIX-07  a fixed rent debit that, combined with today's payment, dips the
          balance below the minimum on day 31 even though the final 90-day
          balance (after a day-60 salary) looks comfortable -- the
          "temporary dip hidden by a good final balance" case
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from buyorwait.schemas import (
    AffordabilityStatus,
    Currency,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExpenseCategory,
    Flexibility,
    PaymentOptionMethod,
    PaymentPreference,
    Profile,
    RecommendedPaymentMethod,
)

from .common import Fixture, ExpectedOutcome, make_event, make_option, make_profile, make_request

# ============================================================================
# FIX-01
# ============================================================================
#
# By hand:
#   balance 20000, minimum 1000  -> headroom 19000, comfortably above the
#   6000 request. amount_safe_to_pay = min(19000, 6000) = 6000.
#   full_payment is NOT in payment_methods_user_will_consider, so despite
#   full capacity existing, S-08 blocks affordable_now; S-12 blocks
#   full_payment as a candidate method entirely. The n=3 installment option
#   (2024-01-01, 2024-01-31, 2024-03-01 at 30-day spacing) is the only
#   eligible method and completes exactly ON the 2024-03-01 deadline
#   (S-05's "on or before"). -> affordable_with_plan / installments.

FIX_01 = Fixture(
    fixture_id="FIX-01",
    title="Full-payment capacity exists but full_payment is not accepted",
    rationale=(
        "balance 20000, minimum 1000 -> headroom 19000, comfortably above the 6000 request; "
        "amount_safe_to_pay=min(19000,6000)=6000. full_payment is not accepted, so S-08 blocks "
        "affordable_now and S-12 excludes full_payment as a candidate entirely even though "
        "capacity exists. The n=3 installment option (2024-01-01/01-31/03-01 at 30-day spacing) "
        "is the only eligible method and completes exactly on the 2024-03-01 deadline "
        "(S-05's 'on or before')."
    ),
    profile=make_profile(
        user_id="synthetic_user_01",
        home_currency=Currency.USD,
        current_available_balance=Decimal("20000"),
        minimum_balance_to_keep=Decimal("1000"),
        payment_methods_user_will_consider=frozenset({PaymentPreference.INSTALLMENTS}),
        max_installment_months=6,
    ),
    request=make_request(
        request_id="synthetic_request_01",
        user_id="synthetic_user_01",
        request_date=date(2024, 1, 1),
        requested_amount=Decimal("6000"),
        desired_completion_date=date(2024, 3, 1),
        allows_partial_payment=False,
    ),
    events=(),
    options=(
        make_option(
            payment_option_id="synthetic_payment_option_01f",
            request_id="synthetic_request_01",
            payment_method=PaymentOptionMethod.FULL_PAYMENT,
            payment_amount=Decimal("6000"),
            number_of_payments=1,
            first_payment_date=date(2024, 1, 1),
            total_payable_amount=Decimal("6000"),
        ),
        make_option(
            payment_option_id="synthetic_payment_option_01i",
            request_id="synthetic_request_01",
            payment_method=PaymentOptionMethod.INSTALLMENTS,
            payment_amount=Decimal("2000"),
            number_of_payments=3,
            first_payment_date=date(2024, 1, 1),
            payment_frequency_days=30,
            total_payable_amount=Decimal("6000"),
        ),
    ),
    expected=ExpectedOutcome(
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
        earliest_date_for_full_payment=date(2024, 1, 1),
        amount_safe_to_pay=Decimal("6000"),
        chosen_payment_option_id="synthetic_payment_option_01i",
        plan_total=Decimal("6000"),
    ),
)


# ============================================================================
# FIX-02
# ============================================================================
#
# By hand:
#   opening 1000, minimum 700. A future STREAMING subscription debit of 100
#   lands on 2024-02-10 (day 40) -- stoppable, not protected, permitted in
#   the user's stop list.
#   Paying X today must satisfy BOTH: day 0: 1000-X >= 700 (X<=300), and
#   day 40: (1000-X)-100 >= 700 (X<=200). The day-40 constraint binds:
#   amount_safe_to_pay = min(200, 250) = 200 -- short of the 250 requested.
#   Stopping the subscription removes the day-40 constraint entirely, so the
#   only remaining constraint is day 0's X<=300, comfortably covering the
#   full 250: paying 250 today with the stop is safe (1000-250=750>=700).
#   -> affordable_with_plan / full_payment, spending_changes_needed=stop:<event>.
#   earliest_date_for_full_payment is measured WITHOUT the change (S-06) --
#   and checking every possible date in [anchor, anchor+90] shows paying 250
#   in full is NEVER safe unaided: before day 40 it collides with the
#   subscription (1000-250-100=650<700); on or after day 40 the subscription
#   has already been paid, permanently leaving only 900, and 900-250=650<700
#   still. So earliest_date_for_full_payment is genuinely EMPTY here, even
#   though the row is affordable_with_plan -- a sharper case than any of the
#   three spending-change public samples (evaluation/assumptions.md O-25),
#   which all have some later capacity even without a change.

_FIX_02_SUBSCRIPTION_EVENT_ID = "synthetic_event_02_subscription"

FIX_02 = Fixture(
    fixture_id="FIX-02",
    title="A shortfall closed exactly by stopping one permitted event",
    rationale=(
        "opening 1000, minimum 700; a future 100 STREAMING debit on day 40 forces "
        "amount_safe_to_pay=200 (short of the 250 requested) unless stopped; stopping it "
        "makes the full 250 safe today. earliest_date_for_full_payment is EMPTY because "
        "paying 250 unaided is unsafe on every date in the 90-day window (see module docstring)."
    ),
    profile=make_profile(
        user_id="synthetic_user_02",
        home_currency=Currency.EUR,
        current_available_balance=Decimal("1000"),
        minimum_balance_to_keep=Decimal("700"),
        expense_categories_to_protect=frozenset({ExpenseCategory.RENT}),
        expense_categories_user_is_willing_to_stop=frozenset({ExpenseCategory.STREAMING}),
        payment_methods_user_will_consider=frozenset({PaymentPreference.FULL_PAYMENT}),
    ),
    request=make_request(
        request_id="synthetic_request_02",
        user_id="synthetic_user_02",
        request_date=date(2024, 1, 1),
        requested_amount=Decimal("250"),
        desired_completion_date=date(2024, 1, 20),
        allows_partial_payment=False,
    ),
    events=(
        make_event(
            event_id=_FIX_02_SUBSCRIPTION_EVENT_ID,
            user_id="synthetic_user_02",
            event_type=EventType.SUBSCRIPTION,
            description="synthetic streaming subscription",
            category=ExpenseCategory.STREAMING,
            direction=Direction.DEBIT,
            amount=Decimal("100"),
            currency=Currency.EUR,
            event_date=date(2024, 2, 10),
            status=EventStatus.SCHEDULED,
            flexibility=Flexibility.STOPPABLE,
        ),
    ),
    options=(
        make_option(
            payment_option_id="synthetic_payment_option_02f",
            request_id="synthetic_request_02",
            payment_method=PaymentOptionMethod.FULL_PAYMENT,
            payment_amount=Decimal("250"),
            number_of_payments=1,
            first_payment_date=date(2024, 1, 1),
            total_payable_amount=Decimal("250"),
        ),
    ),
    expected=ExpectedOutcome(
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
        earliest_date_for_full_payment=None,
        amount_safe_to_pay=Decimal("200"),
    ),
)


# ============================================================================
# FIX-03a / FIX-03b
# ============================================================================
#
# By hand (shared setup): opening 3800, minimum 1000, requested 3000.
#   Day 0 constraint: 3800-X >= 1000 -> X<=2800. No other debit exists, so
#   amount_safe_to_pay = min(2800, 3000) = 2800 (0 < 2800 < 3000: S-10's
#   strict-inequality precondition for partial_payment holds).
#   A confirmed +500 salary lands on 2024-01-20. Checking every candidate
#   full-payment date: paying 3000 on or before 2024-01-20 collides with the
#   day-20 debit-before-credit rule (floor_check = 3800-3000=800<1000, or on
#   day 20 itself 3800-3000=800<1000 -- same-day debits are checked before
#   that day's credit posts); paying on 2024-01-21 (the day AFTER the salary
#   has posted) uses the full 4300: 4300-3000=1300>=1000, safe. So
#   earliest_date_for_full_payment = 2024-01-21, and the partial plan's
#   second payment (3000-2800=200) is scheduled on that same date.

_FIX_03_SALARY_DATE = date(2024, 1, 20)
_FIX_03_SECOND_PAYMENT_DATE = date(2024, 1, 21)


def _fix03_profile(user_id: str) -> Profile:
    return make_profile(
        user_id=user_id,
        home_currency=Currency.INR,
        current_available_balance=Decimal("3800"),
        minimum_balance_to_keep=Decimal("1000"),
        payment_methods_user_will_consider=frozenset({PaymentPreference.PARTIAL_PAYMENT}),
    )


def _fix03_salary_event(user_id: str, event_id: str) -> Event:
    return make_event(
        event_id=event_id,
        user_id=user_id,
        event_type=EventType.INCOME,
        description="synthetic confirmed salary",
        category=ExpenseCategory.SALARY,
        direction=Direction.CREDIT,
        amount=Decimal("500"),
        currency=Currency.INR,
        event_date=_FIX_03_SALARY_DATE,
        status=EventStatus.SCHEDULED,
        flexibility=Flexibility.FIXED,
    )


FIX_03A = Fixture(
    fixture_id="FIX-03a",
    title="Exact two-payment partial plan completing before the deadline",
    rationale=(
        "opening 3800, minimum 1000, requested 3000: amount_safe_to_pay=2800 today. "
        "A +500 salary on 2024-01-20 raises full capacity from 2024-01-21 onward "
        "(4300-3000=1300>=1000). Partial plan: 2800 today, 200 on 2024-01-21 -- "
        "well before the generous 2024-02-15 deadline."
    ),
    profile=_fix03_profile("synthetic_user_03a"),
    request=make_request(
        request_id="synthetic_request_03a",
        user_id="synthetic_user_03a",
        request_date=date(2024, 1, 1),
        requested_amount=Decimal("3000"),
        desired_completion_date=date(2024, 2, 15),
        allows_partial_payment=True,
    ),
    events=(_fix03_salary_event("synthetic_user_03a", "synthetic_event_03a_salary"),),
    options=(),
    expected=ExpectedOutcome(
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        recommended_payment_method=RecommendedPaymentMethod.PARTIAL_PAYMENT,
        earliest_date_for_full_payment=_FIX_03_SECOND_PAYMENT_DATE,
        amount_safe_to_pay=Decimal("2800"),
        plan_total=Decimal("3000"),
    ),
)

FIX_03B = Fixture(
    fixture_id="FIX-03b",
    title="Same shortfall, but the deadline falls before full capacity arrives",
    rationale=(
        "Identical to FIX-03a except desired_completion_date=2024-01-10, which is BEFORE "
        "earliest_date_for_full_payment (2024-01-21). S-10 requires earliest_date <= deadline "
        "for partial_payment, so partial_payment is no longer eligible; full_payment and wait "
        "are ineligible (full_payment not accepted). Fallback: not_recommended, while capacity "
        "still genuinely arrives later -- affordable_later (the U-STATUS-1 boundary, "
        "evaluation/assumptions.md)."
    ),
    profile=_fix03_profile("synthetic_user_03b"),
    request=make_request(
        request_id="synthetic_request_03b",
        user_id="synthetic_user_03b",
        request_date=date(2024, 1, 1),
        requested_amount=Decimal("3000"),
        desired_completion_date=date(2024, 1, 10),
        allows_partial_payment=True,
    ),
    events=(_fix03_salary_event("synthetic_user_03b", "synthetic_event_03b_salary"),),
    options=(),
    expected=ExpectedOutcome(
        affordability_status=AffordabilityStatus.AFFORDABLE_LATER,
        recommended_payment_method=RecommendedPaymentMethod.NOT_RECOMMENDED,
        earliest_date_for_full_payment=_FIX_03_SECOND_PAYMENT_DATE,
        amount_safe_to_pay=Decimal("2800"),
    ),
)


# ============================================================================
# FIX-04
# ============================================================================
#
# By hand: balance 100000 (capacity is never the binding constraint here --
# this fixture isolates S-14 rule 3 alone). Two n=3, 30-day installment
# options with identical dates, differing only in total cost: 6000 (no fee)
# vs 6600 (600 fee). Both complete on the same 2024-03-01 date, well before
# the 2024-12-31 deadline. Cheaper wins.

FIX_04 = Fixture(
    fixture_id="FIX-04",
    title="Two installment options differing only in total cost -- cheaper wins",
    rationale=(
        "Both options: n=3, 30-day spacing, same dates. Option 04a totals 6000 (no fee); "
        "option 04b totals 6600 (600 fee). S-14 rule 3 (minimize total amount paid) selects 04a."
    ),
    profile=make_profile(
        user_id="synthetic_user_04",
        home_currency=Currency.USD,
        current_available_balance=Decimal("100000"),
        minimum_balance_to_keep=Decimal("1000"),
        payment_methods_user_will_consider=frozenset({PaymentPreference.INSTALLMENTS}),
        max_installment_months=24,
    ),
    request=make_request(
        request_id="synthetic_request_04",
        user_id="synthetic_user_04",
        request_date=date(2024, 1, 1),
        requested_amount=Decimal("6000"),
        desired_completion_date=date(2024, 12, 31),
        allows_partial_payment=False,
    ),
    events=(),
    options=(
        make_option(
            payment_option_id="synthetic_payment_option_04a",
            request_id="synthetic_request_04",
            payment_method=PaymentOptionMethod.INSTALLMENTS,
            payment_amount=Decimal("2000"),
            number_of_payments=3,
            first_payment_date=date(2024, 1, 1),
            payment_frequency_days=30,
            total_payable_amount=Decimal("6000"),
        ),
        make_option(
            payment_option_id="synthetic_payment_option_04b",
            request_id="synthetic_request_04",
            payment_method=PaymentOptionMethod.INSTALLMENTS,
            payment_amount=Decimal("2200"),
            number_of_payments=3,
            first_payment_date=date(2024, 1, 1),
            payment_frequency_days=30,
            financing_fee=Decimal("600"),
            total_payable_amount=Decimal("6600"),
        ),
    ),
    expected=ExpectedOutcome(
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
        earliest_date_for_full_payment=date(2024, 1, 1),
        chosen_payment_option_id="synthetic_payment_option_04a",
        plan_total=Decimal("6000"),
    ),
)


# ============================================================================
# FIX-05
# ============================================================================
#
# By hand: same capacity setup as FIX-04. Option 05a: n=3, total 6000.
# Option 05b: n=2, total 6000 -- TIED on cost. S-14 rule 5 (fewer payments)
# must pick 05b (n=2 < n=3). Option 05a is deliberately given the LOWER id
# (…05a < …05b alphabetically) so that a wrong implementation which skipped
# straight to rule 6 (lowest payment_option_id) would pick 05a and get this
# fixture wrong -- only correctly applying rule 5 first picks 05b.

FIX_05 = Fixture(
    fixture_id="FIX-05",
    title="Two installment options tied on cost -- fewer payments wins over lowest id",
    rationale=(
        "Option 05a: n=3, total 6000, id 'synthetic_payment_option_05a'. Option 05b: n=2, "
        "total 6000, id 'synthetic_payment_option_05b' (a HIGHER id). Costs are tied, so S-14 "
        "rule 5 (fewer payments) must decide -- 05b (n=2) wins despite its higher id, which "
        "only rule 6 (a lower id) would have preferred."
    ),
    profile=make_profile(
        user_id="synthetic_user_05",
        home_currency=Currency.USD,
        current_available_balance=Decimal("100000"),
        minimum_balance_to_keep=Decimal("1000"),
        payment_methods_user_will_consider=frozenset({PaymentPreference.INSTALLMENTS}),
        max_installment_months=24,
    ),
    request=make_request(
        request_id="synthetic_request_05",
        user_id="synthetic_user_05",
        request_date=date(2024, 1, 1),
        requested_amount=Decimal("6000"),
        desired_completion_date=date(2024, 12, 31),
        allows_partial_payment=False,
    ),
    events=(),
    options=(
        make_option(
            payment_option_id="synthetic_payment_option_05a",
            request_id="synthetic_request_05",
            payment_method=PaymentOptionMethod.INSTALLMENTS,
            payment_amount=Decimal("2000"),
            number_of_payments=3,
            first_payment_date=date(2024, 1, 1),
            payment_frequency_days=30,
            total_payable_amount=Decimal("6000"),
        ),
        make_option(
            payment_option_id="synthetic_payment_option_05b",
            request_id="synthetic_request_05",
            payment_method=PaymentOptionMethod.INSTALLMENTS,
            payment_amount=Decimal("3000"),
            number_of_payments=2,
            first_payment_date=date(2024, 1, 1),
            payment_frequency_days=30,
            total_payable_amount=Decimal("6000"),
        ),
    ),
    expected=ExpectedOutcome(
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
        earliest_date_for_full_payment=date(2024, 1, 1),
        chosen_payment_option_id="synthetic_payment_option_05b",
        plan_total=Decimal("6000"),
    ),
)


# ============================================================================
# FIX-06 (rule-check fixture -- see RuleCheckFixture, not the plan-shaped Fixture)
# ============================================================================


@dataclass(frozen=True, slots=True)
class RuleCheckFixture:
    """A fixture whose only assertion is "this action is / is not a
    well-formed spending change under S-15", checked directly against
    `code/evaluation/metrics.py`'s own rule-checking function -- no full
    request/plan needed."""

    fixture_id: str
    title: str
    rationale: str
    profile: Profile
    event: Event
    expect_violation: bool


FIX_06 = RuleCheckFixture(
    fixture_id="FIX-06",
    title="A reducible expense whose category is also protected",
    rationale=(
        "The event is DINING, flexibility=reducible, and DINING is in the user's "
        "willing-to-reduce list -- naively that looks like a valid reduce_to target. But "
        "DINING is ALSO in expense_categories_to_protect for this (deliberately "
        "contradictory) profile. S-15 ('only non-protected, flexible events... may be "
        "changed') makes protection win: this action must be rejected as not well-formed, "
        "regardless of the reduce list."
    ),
    profile=make_profile(
        user_id="synthetic_user_06",
        home_currency=Currency.USD,
        current_available_balance=Decimal("5000"),
        minimum_balance_to_keep=Decimal("500"),
        expense_categories_to_protect=frozenset({ExpenseCategory.DINING}),
        expense_categories_user_is_willing_to_reduce=frozenset({ExpenseCategory.DINING}),
        payment_methods_user_will_consider=frozenset({PaymentPreference.FULL_PAYMENT}),
    ),
    event=make_event(
        event_id="synthetic_event_06_dining",
        user_id="synthetic_user_06",
        description="synthetic protected-but-reducible dining expense",
        category=ExpenseCategory.DINING,
        direction=Direction.DEBIT,
        amount=Decimal("50"),
        event_date=date(2023, 12, 15),
        flexibility=Flexibility.REDUCIBLE,
        minimum_allowed_amount=Decimal("20"),
    ),
    expect_violation=True,
)


# ============================================================================
# FIX-07
# ============================================================================
#
# By hand: opening 1000, minimum 200. A FIXED rent debit of 700 lands on
# 2024-01-31 (unavoidable, not flexible); a confirmed +1000 salary lands on
# 2024-03-01. Paying X today: day-0 constraint X<=800; day-31 constraint
# (1000-X)-700>=200 -> X<=100 (binding). amount_safe_to_pay = min(100, 150) = 100.
# Checking every candidate date for the FULL 150: before 2024-03-01 the rent
# debit always drags the running balance to 300-150=150<200; on 2024-03-01
# itself the debit-before-credit rule still checks 300-150=150<200; only
# 2024-03-02 (the day AFTER the salary has posted) gives 1300-150=1150>=200.
# -> earliest_date_for_full_payment = 2024-03-02. Partial plan: 100 today,
# remaining 50 on 2024-03-02 (well before the 2024-03-15 deadline). Full
# replay of the actual TWO-PAYMENT schedule (not just the single-payment
# hypothetical above) is checked in tests/test_fixtures.py and lands exactly
# at the 200 floor on day 31 -- a tight, exact-equality boundary case.
# THE POINT: a check that only looked at the healthy final balance (1150)
# would never see the day-31 dip that makes anything above 100 unsafe today.

FIX_07 = Fixture(
    fixture_id="FIX-07",
    title="A mid-window dip caused by today's payment, hidden by a healthy final balance",
    rationale=(
        "opening 1000, minimum 200; a FIXED 700 rent debit on 2024-01-31 and a +1000 salary "
        "on 2024-03-01. Paying more than 100 today breaches the floor on 2024-01-31 even "
        "though the balance recovers to 1150 by 2024-03-02. amount_safe_to_pay=100; "
        "earliest_date_for_full_payment=2024-03-02 (the day AFTER the salary posts)."
    ),
    profile=make_profile(
        user_id="synthetic_user_07",
        home_currency=Currency.USD,
        current_available_balance=Decimal("1000"),
        minimum_balance_to_keep=Decimal("200"),
        payment_methods_user_will_consider=frozenset({PaymentPreference.PARTIAL_PAYMENT}),
    ),
    request=make_request(
        request_id="synthetic_request_07",
        user_id="synthetic_user_07",
        request_date=date(2024, 1, 1),
        requested_amount=Decimal("150"),
        desired_completion_date=date(2024, 3, 15),
        allows_partial_payment=True,
    ),
    events=(
        make_event(
            event_id="synthetic_event_07_rent",
            user_id="synthetic_user_07",
            description="synthetic fixed rent",
            category=ExpenseCategory.RENT,
            direction=Direction.DEBIT,
            amount=Decimal("700"),
            event_date=date(2024, 1, 31),
            status=EventStatus.SCHEDULED,
            flexibility=Flexibility.FIXED,
        ),
        make_event(
            event_id="synthetic_event_07_salary",
            user_id="synthetic_user_07",
            event_type=EventType.INCOME,
            description="synthetic confirmed salary",
            category=ExpenseCategory.SALARY,
            direction=Direction.CREDIT,
            amount=Decimal("1000"),
            event_date=date(2024, 3, 1),
            status=EventStatus.SCHEDULED,
            flexibility=Flexibility.FIXED,
        ),
    ),
    options=(),
    expected=ExpectedOutcome(
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        recommended_payment_method=RecommendedPaymentMethod.PARTIAL_PAYMENT,
        earliest_date_for_full_payment=date(2024, 3, 2),
        amount_safe_to_pay=Decimal("100"),
        plan_total=Decimal("150"),
    ),
)


ALL_FIXTURES: tuple[Fixture, ...] = (FIX_01, FIX_02, FIX_03A, FIX_03B, FIX_04, FIX_05, FIX_07)
ALL_RULE_CHECK_FIXTURES: tuple[RuleCheckFixture, ...] = (FIX_06,)
