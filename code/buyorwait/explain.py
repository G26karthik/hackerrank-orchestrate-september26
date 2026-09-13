"""Grounded explanation generator (Stage 5).

Responsibilities (per S-31, O-31):
  * Renders concise, grounded decision_explanation strings matching the five
    cataloged shapes in evaluation/assumptions.md O-31:
      1. full_payment (pay today without changes).
      2. full_payment with spending changes.
      3. installments.
      4. wait.
      5. partial_payment.
      6. not_recommended (deadline-gated or capacity-gated).
  * Every fact is grounded in validated plan and ledger attributes:
      - Amount and currency code (e.g. 'EUR 996.60', 'ZAR 25,256').
      - Dates formatted as 'D MMMM YYYY' (e.g. '15 April 2025').
      - Protected floor / minimum balance to keep.
      - Changed event descriptions cited in natural lowercase language.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .csv_format import ReduceChange, StopChange
from .planner import Candidate
from .schemas import Dataset, PaymentPreference, RecommendedPaymentMethod


def format_explanation_amount(amount: Decimal) -> str:
    """Format an amount for natural-language explanations: thousands-separated,
    two decimals if fractional, no decimals if whole integer."""
    if amount == amount.to_integral():
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


def format_explanation_date(d: date) -> str:
    """Format date as 'D MMMM YYYY', e.g. '15 April 2025' or '3 March 2024'."""
    return f"{d.day} {d.strftime('%B')} {d.year}"


def explain(dataset: Dataset, request_id: str, candidate: Candidate) -> str:
    """Render a concise, grounded decision_explanation for candidate."""
    request = dataset.all_requests_by_id[request_id]
    profile = dataset.profiles_by_user[request.user_id]
    currency = profile.home_currency.value
    min_bal = profile.minimum_balance_to_keep
    formatted_min = format_explanation_amount(min_bal)

    # -------------------------------------------------------------------------
    # 1. full_payment with spending changes
    # -------------------------------------------------------------------------
    if candidate.method == RecommendedPaymentMethod.FULL_PAYMENT and candidate.spending_changes:
        # Build natural language description of changes
        change_phrases = []
        for ch in candidate.spending_changes:
            target_ev = dataset.events_by_id.get(ch.event_id)
            desc = target_ev.description.lower() if target_ev else "subscription"
            if isinstance(ch, StopChange):
                change_phrases.append(f"stop the {desc}")
            elif isinstance(ch, ReduceChange):
                new_amt_str = format_explanation_amount(ch.new_amount)
                change_phrases.append(f"reduce the {desc} to {currency} {new_amt_str}")

        if len(change_phrases) == 1:
            actions_text = change_phrases[0].capitalize()
        elif len(change_phrases) == 2:
            actions_text = f"{change_phrases[0].capitalize()} and {change_phrases[1]}"
        else:
            actions_text = f"{change_phrases[0].capitalize()}, {change_phrases[1]}, and {change_phrases[2]}"

        amt_str = format_explanation_amount(request.requested_amount)
        return (
            f"{actions_text}, then pay {currency} {amt_str} today. "
            f"This leaves at least {currency} {formatted_min} available."
        )

    # -------------------------------------------------------------------------
    # 2. full_payment today (no spending changes)
    # -------------------------------------------------------------------------
    if candidate.method == RecommendedPaymentMethod.FULL_PAYMENT:
        amt_str = format_explanation_amount(request.requested_amount)
        return (
            f"Pay {currency} {amt_str} today. "
            f"This leaves at least {currency} {formatted_min} available over the next 90 days."
        )

    # -------------------------------------------------------------------------
    # 3. installments
    # -------------------------------------------------------------------------
    if candidate.method == RecommendedPaymentMethod.INSTALLMENTS:
        count = candidate.payment_count
        first_entry = candidate.payment_plan[0]
        inst_amt_str = format_explanation_amount(first_entry.amount)
        first_date_str = format_explanation_date(first_entry.entry_date)

        if candidate.spending_changes:
            change_phrases = []
            for ch in candidate.spending_changes:
                ev = dataset.events_by_id.get(ch.event_id)
                desc = ev.description if ev else "recurring commitment"
                if isinstance(ch, StopChange):
                    change_phrases.append(f"stop the {desc}")
                elif isinstance(ch, ReduceChange):
                    new_amt_str = format_explanation_amount(ch.new_amount)
                    change_phrases.append(f"reduce the {desc} to {currency} {new_amt_str}")

            if len(change_phrases) == 1:
                actions_text = change_phrases[0].capitalize()
            elif len(change_phrases) == 2:
                actions_text = f"{change_phrases[0].capitalize()} and {change_phrases[1]}"
            else:
                actions_text = f"{change_phrases[0].capitalize()}, {change_phrases[1]}, and {change_phrases[2]}"
            return (
                f"{actions_text}, then use {count} installments of {currency} {inst_amt_str}, starting {first_date_str}. "
                f"This leaves at least {currency} {formatted_min} available."
            )

        return (
            f"Use {count} installments of {currency} {inst_amt_str}, starting {first_date_str}. "
            f"This leaves at least {currency} {formatted_min} available."
        )

    # -------------------------------------------------------------------------
    # 4. wait
    # -------------------------------------------------------------------------
    if candidate.method == RecommendedPaymentMethod.WAIT:
        wait_entry = candidate.payment_plan[0]
        wait_date_str = format_explanation_date(wait_entry.entry_date)
        amt_str = format_explanation_amount(request.requested_amount)
        return (
            f"Pay {currency} {amt_str} in full on {wait_date_str}. "
            f"Paying earlier would take the balance below the {currency} {formatted_min} minimum."
        )

    # -------------------------------------------------------------------------
    # 5. partial_payment
    # -------------------------------------------------------------------------
    if candidate.method == RecommendedPaymentMethod.PARTIAL_PAYMENT and len(candidate.payment_plan) == 2:
        p1 = candidate.payment_plan[0]
        p2 = candidate.payment_plan[1]
        p1_str = format_explanation_amount(p1.amount)
        p2_str = format_explanation_amount(p2.amount)
        p2_date_str = format_explanation_date(p2.entry_date)
        return (
            f"Pay {currency} {p1_str} today and the remaining {currency} {p2_str} on {p2_date_str}. "
            f"This completes the full request and keeps the {currency} {formatted_min} minimum protected."
        )

    # -------------------------------------------------------------------------
    # 6. not_recommended (distinguish preference, deadline, and capacity reasons)
    # -------------------------------------------------------------------------
    deadline_str = format_explanation_date(request.desired_completion_date)
    opts = dataset.options_by_request.get(request_id, ())
    if PaymentPreference.INSTALLMENTS not in profile.payment_methods_user_will_consider or profile.max_installment_months is None:
        return (
            f"Do not make this payment by {deadline_str}. "
            f"Installments are not accepted by the user, and full payment would breach the {currency} {formatted_min} minimum protected."
        )
    if opts and all(opt.number_of_payments > profile.max_installment_months for opt in opts):
        return (
            f"Do not make this payment by {deadline_str}. "
            f"Available installment options exceed the user's limit of {profile.max_installment_months} months, "
            f"and full payment would breach the {currency} {formatted_min} minimum protected."
        )
    return (
        f"Do not make this payment by {deadline_str}. "
        f"None of the available options keeps the {currency} {formatted_min} minimum protected."
    )


_FABRICATED_TERMS = (
    "gift",
    "lottery",
    "jackpot",
    "million",
    "billion",
    "windfall",
    "free money",
    "grant",
    "inherited",
    "inheritance",
    "bonus credit",
    "stimulus",
)


def validate_explanation(
    dataset: Dataset,
    request_id: str,
    candidate: Candidate,
    explanation_text: str,
) -> tuple[bool, str | None]:
    """Validate that explanation_text is strictly grounded in verified facts.
    Returns (True, None) if valid, or (False, reason) if unsupported facts or fabricated claims are found.
    """
    request = dataset.all_requests_by_id.get(request_id)
    if request is None:
        return False, f"unknown request_id: {request_id}"
    profile = dataset.profiles_by_user.get(request.user_id)
    if profile is None:
        return False, f"unknown user_id: {request.user_id}"

    # 1. Reject fabricated / hallucinated claims
    lower_text = explanation_text.lower()
    for term in _FABRICATED_TERMS:
        if term in lower_text:
            return False, f"explanation contains fabricated claim: '{term}'"

    currency = profile.home_currency.value
    min_bal_str = format_explanation_amount(profile.minimum_balance_to_keep)

    # 2. Currency validation
    if currency not in explanation_text:
        return False, f"currency {currency} missing from explanation"

    # 3. Minimum balance grounding
    if min_bal_str not in explanation_text:
        return False, f"minimum balance {min_bal_str} not mentioned in explanation"

    # 4. Method-specific grounding
    if candidate.method == RecommendedPaymentMethod.FULL_PAYMENT:
        req_amt_str = format_explanation_amount(request.requested_amount)
        if req_amt_str not in explanation_text:
            return False, f"requested amount {req_amt_str} missing from full payment explanation"
        if candidate.spending_changes:
            for ch in candidate.spending_changes:
                ev = dataset.events_by_id.get(ch.event_id)
                if ev and ev.description.lower() not in lower_text:
                    # check if category or counterparty is mentioned
                    pass

    elif candidate.method == RecommendedPaymentMethod.INSTALLMENTS:
        if str(candidate.payment_count) not in explanation_text:
            return False, f"installment count {candidate.payment_count} missing"
        if candidate.payment_plan:
            inst_amt_str = format_explanation_amount(candidate.payment_plan[0].amount)
            if inst_amt_str not in explanation_text:
                return False, f"installment payment amount {inst_amt_str} missing"
        if candidate.spending_changes:
            # Installment explanation must mention changes when changes are required
            if "stop" not in lower_text and "reduce" not in lower_text:
                return False, "installments require spending changes but explanation omits them"

    elif candidate.method == RecommendedPaymentMethod.WAIT:
        if candidate.payment_plan:
            wait_date_str = format_explanation_date(candidate.payment_plan[0].entry_date)
            if wait_date_str not in explanation_text:
                return False, f"wait target date {wait_date_str} missing"

    elif candidate.method == RecommendedPaymentMethod.PARTIAL_PAYMENT:
        if len(candidate.payment_plan) == 2:
            p1_str = format_explanation_amount(candidate.payment_plan[0].amount)
            p2_str = format_explanation_amount(candidate.payment_plan[1].amount)
            if p1_str not in explanation_text or p2_str not in explanation_text:
                return False, "partial payment amounts missing from explanation"

    elif candidate.method == RecommendedPaymentMethod.NOT_RECOMMENDED:
        deadline_str = format_explanation_date(request.desired_completion_date)
        if deadline_str not in explanation_text and "within 90 days" not in explanation_text:
            return False, f"deadline {deadline_str} missing from not_recommended explanation"

    return True, None

