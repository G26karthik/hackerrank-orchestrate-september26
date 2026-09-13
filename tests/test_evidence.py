import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/buyorwait/evidence.py's DETERMINISTIC parts (amount-role
selection, JSON parsing helpers) using synthetic observations -- no live API
call, no cost, always runnable. The REAL extraction functions
(`extract_image_observation`, `extract_message_facts`) are exercised
separately in the Stage 3 capability pilot and the 16-image audit
(evaluation/llm_capability_pilot.md, evaluation/image_audit.md) because they
require a live call; this file locks down the CODE-CONTROLLED selection
logic that decides which observed field is the answer, independent of
whether the model's observation came from a live call or a cache hit.
"""

import unittest
from decimal import Decimal

from buyorwait.evidence import AmountCandidate, ImageObservation, select_amount_role
from buyorwait.schemas import Direction, Event, EventStatus, EventType, ExpenseCategory, Flexibility, freeze_row
from datetime import date


def _event(**overrides) -> Event:
    defaults = dict(
        event_id="event_test",
        user_id="user_test",
        event_type=EventType.EXPENSE,
        description="test event",
        category=ExpenseCategory.SHOPPING,
        direction=Direction.DEBIT,
        amount=None,
        currency="INR",
        event_date=date(2024, 1, 1),
        settlement_date=date(2024, 1, 1),
        status=EventStatus.SETTLED,
        linked_event_id=None,
        flexibility=Flexibility.FIXED,
        minimum_allowed_amount=None,
        raw=freeze_row({}),
    )
    defaults.update(overrides)
    return Event(**defaults)


def _obs(**overrides) -> ImageObservation:
    defaults = dict(
        image_id="image_test", source_sha256="deadbeef", document_type="invoice", legible=True,
        amount_candidates=(), currency="INR", net_pay=None, gross_pay=None, tax=None, total=None,
        paid_amount=None, balance_due=None, cash_tendered=None, change=None,
        due_date_candidates=(), payment_status=None, source_regions=(), notes="",
        model="gpt-6-astra", reasoning_effort="high", provider_response_id="resp_x",
    )
    defaults.update(overrides)
    return ImageObservation(**defaults)


class NetSalarySelectionTests(unittest.TestCase):
    """image_01 audit case: net vs gross salary."""

    def test_net_pay_selected_when_available(self):
        ev = _event(category=ExpenseCategory.SALARY, event_type=EventType.INCOME, description="August 2019 net salary")
        obs = _obs(net_pay=Decimal("42000"), gross_pay=Decimal("50000"), total=Decimal("50000"))
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "net_pay")
        self.assertEqual(sel.selected_amount, Decimal("42000"))
        self.assertFalse(sel.needs_review)

    def test_falls_back_to_total_when_net_pay_not_observed_and_flags_review(self):
        ev = _event(category=ExpenseCategory.SALARY, event_type=EventType.INCOME, description="August salary")
        obs = _obs(net_pay=None, total=Decimal("50000"))
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "total")
        self.assertTrue(sel.needs_review)


class OutstandingBalanceSelectionTests(unittest.TestCase):
    """image_02 audit case: balance due vs rent total."""

    def test_balance_due_selected_for_outstanding_description(self):
        ev = _event(category=ExpenseCategory.RENT, description="Outstanding rent balance")
        obs = _obs(balance_due=Decimal("8000"), total=Decimal("12000"))
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "balance_due")
        self.assertEqual(sel.selected_amount, Decimal("8000"))

    def test_utility_outstanding_also_uses_balance_due(self):
        ev = _event(category=ExpenseCategory.UTILITIES, description="Outstanding telecom bill")
        obs = _obs(balance_due=Decimal("1500"))
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "balance_due")


class TaxiFareSelectionTests(unittest.TestCase):
    """image_12 audit case: total fare, never cash tendered/change."""

    def test_total_selected_never_cash_tendered(self):
        ev = _event(category=ExpenseCategory.TRANSPORT, description="Taxi fare")
        obs = _obs(total=Decimal("245"), cash_tendered=Decimal("300"), change=Decimal("55"))
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "total")
        self.assertEqual(sel.selected_amount, Decimal("245"))
        self.assertNotEqual(sel.selected_amount, obs.cash_tendered)


class ReceivedPaymentSelectionTests(unittest.TestCase):
    """image_08/image_09 audit cases: received payment vs due amount."""

    def test_paid_amount_selected_when_payment_status_indicates_paid(self):
        ev = _event(category=ExpenseCategory.HOUSING, description="Property maintenance invoice")
        obs = _obs(paid_amount=Decimal("3000"), total=Decimal("3000"), payment_status="paid")
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "paid_amount")

    def test_unpaid_status_does_not_falsely_match_the_paid_substring(self):
        # "paid" is a literal substring of "unpaid" -- this guards the bug
        # a naive `"paid" in status` check would have (and once did, until
        # this test caught it during Stage 3 development).
        ev = _event(category=ExpenseCategory.HOUSING, description="Property maintenance invoice")
        obs = _obs(paid_amount=None, total=Decimal("3000"), payment_status="unpaid")
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "total")  # falls through to the default, not paid_amount


class DefaultTotalSelectionTests(unittest.TestCase):
    """image_06/image_07/image_10/image_13/image_14 audit cases: default to total."""

    def test_generic_invoice_defaults_to_total(self):
        ev = _event(category=ExpenseCategory.GROCERIES, description="Grocery tax invoice")
        obs = _obs(total=Decimal("1995.00"))
        sel = select_amount_role(obs, ev)
        self.assertEqual(sel.selected_field, "total")
        self.assertEqual(sel.selected_amount, Decimal("1995.00"))
        self.assertFalse(sel.needs_review)


class IllegibleAndUnresolvedTests(unittest.TestCase):
    """image_04 audit case: cropped lower content -- must never invent a value."""

    def test_illegible_observation_yields_no_selection_and_needs_review(self):
        ev = _event(category=ExpenseCategory.GROCERIES, description="Delivered grocery order")
        obs = _obs(legible=False, total=None, notes="lower portion of receipt is cropped out of frame")
        sel = select_amount_role(obs, ev)
        self.assertIsNone(sel.selected_amount)
        self.assertIsNone(sel.selected_field)
        self.assertTrue(sel.needs_review)

    def test_no_named_field_at_all_surfaces_raw_candidates_as_alternatives_not_zero(self):
        ev = _event(category=ExpenseCategory.SHOPPING, description="Tote bag order")
        obs = _obs(
            total=None,
            amount_candidates=(AmountCandidate(label="item price", amount=Decimal("299"), region="item row"),
                                AmountCandidate(label="shipping", amount=Decimal("40"), region="footer")),
        )
        sel = select_amount_role(obs, ev)
        self.assertIsNone(sel.selected_amount)  # NEVER silently defaults to 0 or to a random candidate
        self.assertTrue(sel.needs_review)
        self.assertIn(Decimal("299"), sel.alternatives)
        self.assertIn(Decimal("40"), sel.alternatives)


if __name__ == "__main__":
    unittest.main()
