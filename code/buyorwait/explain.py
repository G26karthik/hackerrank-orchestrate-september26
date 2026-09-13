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
    opts = [
        opt for opt in dataset.options_by_request.get(request_id, ())
        if (opt.payment_method.value if hasattr(opt.payment_method, "value") else str(opt.payment_method)) == "installments"
        and opt.number_of_payments > 1
    ]
    user_allows_full = PaymentPreference.FULL_PAYMENT in profile.payment_methods_user_will_consider
    user_allows_partial = PaymentPreference.PARTIAL_PAYMENT in profile.payment_methods_user_will_consider and request.allows_partial_payment

    if not user_allows_full and not user_allows_partial:
        amt_str = format_explanation_amount(request.requested_amount)
        if opts and profile.max_installment_months is not None and all(opt.number_of_payments > profile.max_installment_months for opt in opts):
            return (
                f"Do not make this {currency} {amt_str} payment by {deadline_str}. "
                f"Full payment is excluded by the user, partial payment is not permitted, "
                f"and available installment options exceed the limit of {profile.max_installment_months} months."
            )
        elif not opts or PaymentPreference.INSTALLMENTS not in profile.payment_methods_user_will_consider:
            return (
                f"Do not make this {currency} {amt_str} payment by {deadline_str}. "
                f"Full payment is excluded by the user, partial payment is not permitted, "
                f"and no eligible installment options are available."
            )

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
    "guaranteed",
    "extra salary",
    "employer confirmation",
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

    # 2. Reject ungrounded financial figures
    import re
    grounded_numbers = {
        request.requested_amount,
        profile.minimum_balance_to_keep,
        profile.current_available_balance,
    }
    if profile.max_installment_months is not None:
        grounded_numbers.add(Decimal(profile.max_installment_months))
    if candidate.payment_count:
        grounded_numbers.add(Decimal(candidate.payment_count))
    for pe in candidate.payment_plan:
        grounded_numbers.add(pe.amount)
    for ch in candidate.spending_changes:
        if isinstance(ch, ReduceChange):
            grounded_numbers.add(ch.new_amount)
    for opt in dataset.options_by_request.get(request_id, ()):
        if opt.payment_amount is not None:
            grounded_numbers.add(opt.payment_amount)
        if opt.total_payable_amount is not None:
            grounded_numbers.add(opt.total_payable_amount)
        if opt.number_of_payments:
            grounded_numbers.add(Decimal(opt.number_of_payments))

    allowed_ints = {
        90,
        request.request_date.day,
        request.request_date.year,
        request.desired_completion_date.day,
        request.desired_completion_date.year,
    }
    for pe in candidate.payment_plan:
        allowed_ints.add(pe.entry_date.day)
        allowed_ints.add(pe.entry_date.year)

    raw_nums = re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", explanation_text)
    for raw in raw_nums:
        clean = raw.replace(",", "")
        try:
            val = Decimal(clean)
            if int(val) in allowed_ints and val == int(val):
                continue
            if not any(abs(val - g) <= Decimal("0.01") for g in grounded_numbers):
                return False, f"explanation contains ungrounded figure: {raw}"
        except Exception:
            pass

    currency = profile.home_currency.value
    min_bal_str = format_explanation_amount(profile.minimum_balance_to_keep)

    # 3. Currency validation
    if currency not in explanation_text:
        return False, f"currency {currency} missing from explanation"

    # 4. Minimum balance grounding (for methods where minimum balance is referenced)
    if candidate.method != RecommendedPaymentMethod.NOT_RECOMMENDED or "minimum protected" in explanation_text:
        if min_bal_str not in explanation_text and "minimum" in explanation_text:
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

