import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Verifies every fixture's hand-derived numbers against the SAME rules
engine production code will eventually use -- `simulator.simulate` and
`independent_verifier.replay_plan` -- not a re-implementation of the
arithmetic. This is the check that the fixtures themselves are internally
consistent (the numbers really do work out the way each docstring claims)
before they are trusted as regression fixtures for a future planner.

Each fixture's `events` are converted into `CashFlow` objects by hand in
this file (there is no forecast.py yet to do that conversion) -- exactly the
same conversion a human would do by reading the event's direction and
amount, which is deliberate: this test is checking arithmetic, not
delegating to unbuilt production code.
"""

import unittest
from decimal import Decimal

from buyorwait.independent_verifier import replay_plan
from buyorwait.simulator import CashFlow, FlowKind
from evaluation.fixtures import ALL_FIXTURES, ALL_RULE_CHECK_FIXTURES
from evaluation.fixtures.scenarios import FIX_01, FIX_02, FIX_03A, FIX_03B, FIX_04, FIX_05, FIX_06, FIX_07
from evaluation.metrics import _action_is_well_formed
from buyorwait.csv_format import ReduceChange


def _flows_from_events(fixture) -> tuple[CashFlow, ...]:
    """Convert a fixture's `events` (all dated ON OR AFTER the request date
    in every fixture here) into signed CashFlow objects for the simulator."""
    anchor = fixture.request.request_date
    out = []
    for e in fixture.events:
        eff = e.effective_date()
        if eff < anchor:
            continue  # historical event, already reflected in current_available_balance
        amount = e.amount if e.direction.value == "credit" else -e.amount
        out.append(CashFlow(eff, amount, FlowKind.OTHER, e.description))
    return tuple(out)


class FixtureIndexTests(unittest.TestCase):
    def test_seven_plan_fixtures_and_one_rule_check_fixture(self):
        self.assertEqual(len(ALL_FIXTURES), 7)
        self.assertEqual(len(ALL_RULE_CHECK_FIXTURES), 1)

    def test_every_fixture_id_and_user_id_and_request_id_are_synthetic_and_unique(self):
        ids = [f.fixture_id for f in ALL_FIXTURES] + [f.fixture_id for f in ALL_RULE_CHECK_FIXTURES]
        self.assertEqual(len(ids), len(set(ids)))
        for f in ALL_FIXTURES:
            self.assertTrue(f.profile.user_id.startswith("synthetic_"))
            self.assertTrue(f.request.request_id.startswith("synthetic_"))


class Fix01Tests(unittest.TestCase):
    """Full capacity exists, but full_payment isn't accepted -- installments used."""

    def test_capacity_covers_the_full_request(self):
        headroom = FIX_01.profile.current_available_balance - FIX_01.profile.minimum_balance_to_keep
        self.assertEqual(headroom, Decimal("19000"))
        self.assertGreaterEqual(headroom, FIX_01.request.requested_amount)
        self.assertEqual(FIX_01.expected.amount_safe_to_pay, FIX_01.request.requested_amount)

    def test_chosen_installment_option_replays_safely_and_matches_the_deadline(self):
        option = next(o for o in FIX_01.options if o.payment_option_id == FIX_01.expected.chosen_payment_option_id)
        plan = _installment_plan_entries(option)
        result = replay_plan(
            opening_balance=FIX_01.profile.current_available_balance,
            minimum_balance_to_keep=FIX_01.profile.minimum_balance_to_keep,
            anchor_date=FIX_01.request.request_date,
            flows=(),
            plan_entries=plan,
            requested_amount=FIX_01.request.requested_amount,
            deadline=FIX_01.request.desired_completion_date,
        )
        self.assertTrue(result.is_fully_valid)
        self.assertEqual(sum(e.amount for e in plan), FIX_01.expected.plan_total)
        self.assertEqual(plan[-1].entry_date, FIX_01.request.desired_completion_date)  # exactly on the deadline

    def test_full_payment_method_is_ineligible_full_payment_not_accepted(self):
        self.assertNotIn("full_payment", {m.value for m in FIX_01.profile.payment_methods_user_will_consider})


class Fix02Tests(unittest.TestCase):
    """A shortfall closed exactly by stopping one event; earliest_date is
    genuinely empty without the change."""

    def test_amount_safe_to_pay_without_the_stop_is_200(self):
        flows = _flows_from_events(FIX_02)
        # Binding at exactly 200: paying 200 must be safe...
        ok = replay_plan(
            opening_balance=FIX_02.profile.current_available_balance,
            minimum_balance_to_keep=FIX_02.profile.minimum_balance_to_keep,
            anchor_date=FIX_02.request.request_date,
            flows=flows,
            plan_entries=(_entry(FIX_02.request.request_date, Decimal("200")),),
            requested_amount=Decimal("200"),
            deadline=FIX_02.request.desired_completion_date,
        )
        self.assertTrue(ok.simulation.is_safe)
        # ...and paying 201 must NOT be safe (the day-40 constraint binds at exactly 200).
        breach = replay_plan(
            opening_balance=FIX_02.profile.current_available_balance,
            minimum_balance_to_keep=FIX_02.profile.minimum_balance_to_keep,
            anchor_date=FIX_02.request.request_date,
            flows=flows,
            plan_entries=(_entry(FIX_02.request.request_date, Decimal("201")),),
            requested_amount=Decimal("201"),
            deadline=FIX_02.request.desired_completion_date,
        )
        self.assertFalse(breach.simulation.is_safe)
        self.assertEqual(FIX_02.expected.amount_safe_to_pay, Decimal("200"))

    def test_full_amount_is_safe_today_WITH_the_stop(self):
        # flows=() -- the subscription is stopped, so it never enters the ledger at all.
        result = replay_plan(
            opening_balance=FIX_02.profile.current_available_balance,
            minimum_balance_to_keep=FIX_02.profile.minimum_balance_to_keep,
            anchor_date=FIX_02.request.request_date,
            flows=(),
            plan_entries=(_entry(FIX_02.request.request_date, FIX_02.request.requested_amount),),
            requested_amount=FIX_02.request.requested_amount,
            deadline=FIX_02.request.desired_completion_date,
        )
        self.assertTrue(result.is_fully_valid)

    def test_full_amount_is_never_safe_unaided_anywhere_in_the_90_day_window(self):
        flows = _flows_from_events(FIX_02)
        anchor = FIX_02.request.request_date
        for offset in range(0, 91):
            day = anchor + __import__("datetime").timedelta(days=offset)
            result = replay_plan(
                opening_balance=FIX_02.profile.current_available_balance,
                minimum_balance_to_keep=FIX_02.profile.minimum_balance_to_keep,
                anchor_date=anchor,
                flows=flows,
                plan_entries=(_entry(day, FIX_02.request.requested_amount),),
                requested_amount=FIX_02.request.requested_amount,
                deadline=day,
            )
            self.assertFalse(
                result.simulation.is_safe,
                f"expected day {day} to be unsafe for the unaided full payment, but it was safe",
            )
        self.assertIsNone(FIX_02.expected.earliest_date_for_full_payment)


class Fix03Tests(unittest.TestCase):
    def test_fix03a_partial_plan_is_fully_valid_and_completes_before_deadline(self):
        flows = _flows_from_events(FIX_03A)
        plan = (
            _entry(FIX_03A.request.request_date, FIX_03A.expected.amount_safe_to_pay),
            _entry(
                FIX_03A.expected.earliest_date_for_full_payment,
                FIX_03A.request.requested_amount - FIX_03A.expected.amount_safe_to_pay,
            ),
        )
        result = replay_plan(
            opening_balance=FIX_03A.profile.current_available_balance,
            minimum_balance_to_keep=FIX_03A.profile.minimum_balance_to_keep,
            anchor_date=FIX_03A.request.request_date,
            flows=flows,
            plan_entries=plan,
            requested_amount=FIX_03A.request.requested_amount,
            deadline=FIX_03A.request.desired_completion_date,
        )
        self.assertTrue(result.is_fully_valid)

    def test_fix03b_same_plan_fails_the_deadline_check(self):
        flows = _flows_from_events(FIX_03B)
        plan = (
            _entry(FIX_03B.request.request_date, FIX_03B.expected.amount_safe_to_pay),
            _entry(
                FIX_03B.expected.earliest_date_for_full_payment,
                FIX_03B.request.requested_amount - FIX_03B.expected.amount_safe_to_pay,
            ),
        )
        result = replay_plan(
            opening_balance=FIX_03B.profile.current_available_balance,
            minimum_balance_to_keep=FIX_03B.profile.minimum_balance_to_keep,
            anchor_date=FIX_03B.request.request_date,
            flows=flows,
            plan_entries=plan,
            requested_amount=FIX_03B.request.requested_amount,
            deadline=FIX_03B.request.desired_completion_date,
        )
        self.assertTrue(result.simulation.is_safe)  # arithmetically still safe...
        self.assertFalse(result.completes_by_deadline)  # ...but too late for this deadline
        self.assertFalse(result.is_fully_valid)

    def test_fix03b_partial_payment_is_ineligible_because_it_is_not_the_accepted_method_reasoning_holds(self):
        # Sanity check on the fixture's own eligibility story: full_payment is
        # not accepted, so `wait` (which needs full_payment acceptance) is
        # also ineligible -- the fixture's not_recommended fallback is forced,
        # not a modeling choice.
        methods = {m.value for m in FIX_03B.profile.payment_methods_user_will_consider}
        self.assertNotIn("full_payment", methods)


class Fix04Fix05RankingTests(unittest.TestCase):
    def test_fix04_cheaper_option_is_the_only_one_matching_expected(self):
        cheap = next(o for o in FIX_04.options if o.payment_option_id == FIX_04.expected.chosen_payment_option_id)
        expensive = next(o for o in FIX_04.options if o.payment_option_id != FIX_04.expected.chosen_payment_option_id)
        self.assertLess(cheap.total_payable_amount, expensive.total_payable_amount)
        # both otherwise identical (same n, same dates) so cost is the only discriminator
        self.assertEqual(cheap.number_of_payments, expensive.number_of_payments)
        self.assertEqual(cheap.first_payment_date, expensive.first_payment_date)

    def test_fix05_options_are_tied_on_cost_but_differ_on_payment_count(self):
        a = next(o for o in FIX_05.options if o.payment_option_id == "synthetic_payment_option_05a")
        b = next(o for o in FIX_05.options if o.payment_option_id == "synthetic_payment_option_05b")
        self.assertEqual(a.total_payable_amount, b.total_payable_amount)
        self.assertNotEqual(a.number_of_payments, b.number_of_payments)
        # the winner (05b) has FEWER payments but a HIGHER id -- confirms the
        # fixture actually discriminates rule 5 from rule 6, per its own rationale.
        self.assertEqual(FIX_05.expected.chosen_payment_option_id, "synthetic_payment_option_05b")
        self.assertLess(b.number_of_payments, a.number_of_payments)
        self.assertGreater(b.payment_option_id, a.payment_option_id)


class Fix06RuleCheckTests(unittest.TestCase):
    def test_protected_category_overrides_the_reduce_list(self):
        action = ReduceChange(event_id=FIX_06.event.event_id, new_amount=Decimal("30"))
        dataset = _FakeDatasetForFix06(FIX_06)
        violation = _action_is_well_formed(action, dataset, FIX_06.profile.user_id)
        self.assertIsNotNone(violation)
        self.assertIn("protected", violation)
        self.assertEqual(FIX_06.expect_violation, True)


class Fix07Tests(unittest.TestCase):
    def test_actual_two_payment_schedule_is_safe_and_hits_the_floor_exactly_on_day_31(self):
        flows = _flows_from_events(FIX_07)
        plan = (
            _entry(FIX_07.request.request_date, FIX_07.expected.amount_safe_to_pay),
            _entry(
                FIX_07.expected.earliest_date_for_full_payment,
                FIX_07.request.requested_amount - FIX_07.expected.amount_safe_to_pay,
            ),
        )
        result = replay_plan(
            opening_balance=FIX_07.profile.current_available_balance,
            minimum_balance_to_keep=FIX_07.profile.minimum_balance_to_keep,
            anchor_date=FIX_07.request.request_date,
            flows=flows,
            plan_entries=plan,
            requested_amount=FIX_07.request.requested_amount,
            deadline=FIX_07.request.desired_completion_date,
        )
        self.assertTrue(result.is_fully_valid)
        # find the day-31 entry and confirm it hits the floor EXACTLY (not just safely above it)
        from datetime import date

        day31 = next(db for db in result.simulation.daily_balances if db.day == date(2024, 1, 31))
        self.assertEqual(day31.floor_check_balance, FIX_07.profile.minimum_balance_to_keep)

    def test_paying_101_today_instead_of_100_breaches_on_day_31(self):
        flows = _flows_from_events(FIX_07)
        plan = (_entry(FIX_07.request.request_date, Decimal("101")),)
        result = replay_plan(
            opening_balance=FIX_07.profile.current_available_balance,
            minimum_balance_to_keep=FIX_07.profile.minimum_balance_to_keep,
            anchor_date=FIX_07.request.request_date,
            flows=flows,
            plan_entries=plan,
            requested_amount=Decimal("101"),
            deadline=FIX_07.request.desired_completion_date,
        )
        self.assertFalse(result.simulation.is_safe)

    def test_final_balance_looks_healthy_despite_the_mid_window_breach_risk(self):
        # This is the crux of the fixture: with the ACTUAL safe plan (100 then
        # 50), the balance at the end is comfortable -- a check that only
        # looked at the ending balance would learn nothing about why 150
        # could not simply be paid on day 0.
        from buyorwait.simulator import balance_on
        from datetime import date

        flows = _flows_from_events(FIX_07)
        plan = (
            _entry(FIX_07.request.request_date, FIX_07.expected.amount_safe_to_pay),
            _entry(
                FIX_07.expected.earliest_date_for_full_payment,
                FIX_07.request.requested_amount - FIX_07.expected.amount_safe_to_pay,
            ),
        )
        result = replay_plan(
            opening_balance=FIX_07.profile.current_available_balance,
            minimum_balance_to_keep=FIX_07.profile.minimum_balance_to_keep,
            anchor_date=FIX_07.request.request_date,
            flows=flows,
            plan_entries=plan,
            requested_amount=FIX_07.request.requested_amount,
            deadline=FIX_07.request.desired_completion_date,
        )
        final = balance_on(result.simulation, date(2024, 3, 10))
        self.assertGreater(final, FIX_07.profile.minimum_balance_to_keep * 3)  # comfortably healthy


# --------------------------------- helpers ---------------------------------


def _entry(d, amount):
    from buyorwait.csv_format import PlanEntry

    return PlanEntry(entry_date=d, amount=amount)


def _installment_plan_entries(option):
    from buyorwait.csv_format import PlanEntry
    from datetime import timedelta

    return tuple(
        PlanEntry(
            entry_date=option.first_payment_date + timedelta(days=option.payment_frequency_days * i),
            amount=option.payment_amount,
        )
        for i in range(option.number_of_payments)
    )


class _FakeDatasetForFix06:
    """A minimal stand-in exposing just the two attributes
    `_action_is_well_formed` reads, so FIX-06 can be checked without
    constructing a full `Dataset`."""

    def __init__(self, fixture):
        self.events_by_id = {fixture.event.event_id: fixture.event}
        self.profiles_by_user = {fixture.profile.user_id: fixture.profile}


if __name__ == "__main__":
    unittest.main()
