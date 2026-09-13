import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

import os
from pathlib import Path

def _resolve_dataset_dir() -> Path:
    if 'DATASET_DIR' in os.environ and Path(os.environ['DATASET_DIR']).exists():
        return Path(os.environ['DATASET_DIR'])
    for cand in [Path('dataset'), Path(__file__).resolve().parents[1] / 'dataset', Path(__file__).resolve().parents[2] / 'dataset']:
        if cand.exists() and (cand / 'requests.csv').exists():
            return cand
    return Path('dataset')

"""Tests for code/buyorwait/tools.py, against the real dataset (loaded once)."""

import unittest
from pathlib import Path

from buyorwait.io_load import build_dataset
from buyorwait.tools import (
    ToolError,
    get_event_lifecycle,
    get_messages,
    get_payment_options,
    get_user_context,
    resolve_image_for_inspection,
    simulate_candidate,
    submit_fact_resolution,
)

def _find_repo_root():
    p = Path(__file__).resolve().parents[1]
    if (p / 'dataset').exists(): return p
    if (p.parent / 'dataset').exists(): return p.parent
    return p
REPO_ROOT = _find_repo_root()
DATASET = build_dataset(_resolve_dataset_dir())


class GetUserContextTests(unittest.TestCase):
    def test_known_user_returns_profile_fields(self):
        ctx = get_user_context(DATASET, user_id="user_01")
        self.assertEqual(ctx["user_id"], "user_01")
        self.assertIn("home_currency", ctx)
        self.assertIn("minimum_balance_to_keep", ctx)
        self.assertNotIn("raw", ctx)  # provenance excluded from the tool-facing result

    def test_unknown_user_raises(self):
        with self.assertRaises(ToolError):
            get_user_context(DATASET, user_id="user_does_not_exist")


class GetEventLifecycleTests(unittest.TestCase):
    def test_known_event_returns_fields_and_empty_linkage_lists_when_none(self):
        ev = get_event_lifecycle(DATASET, event_id="event_01")
        self.assertEqual(ev["event_id"], "event_01")
        self.assertIn("linking_children", ev)
        self.assertIn("messages", ev)
        self.assertIn("images", ev)

    def test_linked_event_chain_resolved(self):
        # event_99 -> event_98 (refund settled linked to a settled expense; inventory.md 5.4)
        ev = get_event_lifecycle(DATASET, event_id="event_99")
        self.assertIsNotNone(ev.get("linked_event"))
        self.assertEqual(ev["linked_event"]["event_id"], "event_98")

    def test_linking_children_found_on_the_parent_side(self):
        ev = get_event_lifecycle(DATASET, event_id="event_98")
        child_ids = [c["event_id"] for c in ev["linking_children"]]
        self.assertIn("event_99", child_ids)

    def test_image_linked_event_surfaces_its_image(self):
        ev = get_event_lifecycle(DATASET, event_id="event_3051")  # image_06's related event
        image_ids = [i["image_id"] for i in ev["images"]]
        self.assertIn("image_06", image_ids)

    def test_unknown_event_raises(self):
        with self.assertRaises(ToolError):
            get_event_lifecycle(DATASET, event_id="event_does_not_exist")


class GetMessagesTests(unittest.TestCase):
    def test_by_user_id(self):
        result = get_messages(DATASET, user_id="user_02")
        self.assertEqual(len(result["messages"]), 1)

    def test_by_request_id(self):
        result = get_messages(DATASET, request_id="request_03")
        self.assertGreaterEqual(len(result["messages"]), 1)

    def test_by_event_id(self):
        result = get_messages(DATASET, event_id="event_1785")
        self.assertGreaterEqual(len(result["messages"]), 1)

    def test_no_filter_raises(self):
        with self.assertRaises(ToolError):
            get_messages(DATASET)

    def test_two_filters_raises(self):
        with self.assertRaises(ToolError):
            get_messages(DATASET, user_id="user_02", request_id="request_03")

    def test_unknown_user_raises(self):
        with self.assertRaises(ToolError):
            get_messages(DATASET, user_id="user_does_not_exist")


class GetPaymentOptionsTests(unittest.TestCase):
    def test_known_request(self):
        result = get_payment_options(DATASET, request_id="request_01")
        self.assertEqual(len(result["options"]), 4)  # inventory.md: request_01 has 4 options

    def test_unknown_request_raises(self):
        with self.assertRaises(ToolError):
            get_payment_options(DATASET, request_id="request_does_not_exist")


class ResolveImageForInspectionTests(unittest.TestCase):
    def test_known_image_resolves_ownership_and_path(self):
        result = resolve_image_for_inspection(DATASET, image_id="image_06")
        self.assertEqual(result["user_id"], "user_33")
        self.assertEqual(result["related_event_id"], "event_3051")
        self.assertTrue(result["path"].endswith("image_06.png"))

    def test_unknown_image_raises(self):
        with self.assertRaises(ToolError):
            resolve_image_for_inspection(DATASET, image_id="image_does_not_exist")


class SimulateCandidateTests(unittest.TestCase):
    def test_simulates_real_candidate_accurately(self):
        result = simulate_candidate(DATASET, request_id="request_01")
        self.assertTrue(result["available"])
        self.assertTrue(result["is_safe"])
        self.assertTrue(result["completes_by_deadline"])
        self.assertEqual(result["request_id"], "request_01")
        self.assertEqual(result["total_paid"], "25256")

    def test_unknown_request_raises(self):
        with self.assertRaises(ToolError):
            simulate_candidate(DATASET, request_id="request_does_not_exist")

    def test_mismatched_option_raises(self):
        with self.assertRaises(ToolError):
            simulate_candidate(DATASET, request_id="request_01", payment_option_id="option_02_3")


class SubmitFactResolutionTests(unittest.TestCase):
    def _valid(self, **overrides):
        base = dict(
            source_type="image", source_id="image_06", field_name="total_amount",
            value=1995.0, confidence=0.9, justification="printed total is clear",
        )
        base.update(overrides)
        return base

    def test_valid_resolution_accepted(self):
        result = submit_fact_resolution(DATASET, resolution=self._valid())
        self.assertTrue(result["accepted"])

    def test_missing_field_rejected(self):
        bad = self._valid()
        del bad["confidence"]
        with self.assertRaises(ToolError):
            submit_fact_resolution(DATASET, resolution=bad)

    def test_unknown_source_id_rejected(self):
        with self.assertRaises(ToolError):
            submit_fact_resolution(DATASET, resolution=self._valid(source_id="image_does_not_exist"))

    def test_wrong_source_type_rejected(self):
        with self.assertRaises(ToolError):
            submit_fact_resolution(DATASET, resolution=self._valid(source_type="receipt"))

    def test_event_and_message_source_types_also_validated(self):
        ok_event = submit_fact_resolution(
            DATASET, resolution=self._valid(source_type="event", source_id="event_01")
        )
        self.assertTrue(ok_event["accepted"])
        ok_message = submit_fact_resolution(
            DATASET, resolution=self._valid(source_type="message", source_id="message_01")
        )
        self.assertTrue(ok_message["accepted"])


if __name__ == "__main__":
    unittest.main()
