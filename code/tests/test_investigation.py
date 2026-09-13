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

"""Tests for code/buyorwait/investigation.py.

Covers:
  * InvestigationState initialization and serialization.
  * build_tool_handlers binding all seven tools.
  * Offline/deterministic investigation path against real dataset.
  * Bounded termination: step cap, tool-call cap, repeated no-progress detection, wall time cap.
  * Successful tool round trip and fact resolution via submit_fact_resolution.
"""

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from buyorwait.investigation import (
    InvestigationLimits,
    InvestigationState,
    build_tool_handlers,
    run_adaptive_investigation,
)
from buyorwait.io_load import build_dataset
from buyorwait.openai_client import CallResult
from buyorwait.tools import ToolError

def _find_repo_root():
    p = Path(__file__).resolve().parents[1]
    if (p / 'dataset').exists(): return p
    if (p.parent / 'dataset').exists(): return p.parent
    return p
REPO_ROOT = _find_repo_root()
DATASET = build_dataset(_resolve_dataset_dir())


class InvestigationStateTests(unittest.TestCase):
    def test_state_initialization_and_serialization(self):
        state = InvestigationState(request_id="request_01", user_id="user_01")
        self.assertEqual(state.request_id, "request_01")
        self.assertEqual(state.user_id, "user_01")
        self.assertFalse(state.completed)
        self.assertFalse(state.unresolved)

        d = state.to_dict()
        self.assertEqual(d["request_id"], "request_01")
        self.assertEqual(d["user_id"], "user_01")
        self.assertIn("elapsed_seconds", d)
        self.assertEqual(d["steps_taken"], 0)


class BuildToolHandlersTests(unittest.TestCase):
    def test_all_seven_tools_bound(self):
        handlers = build_tool_handlers(DATASET)
        expected = {
            "get_user_context",
            "get_event_lifecycle",
            "get_messages",
            "inspect_image",
            "get_payment_options",
            "simulate_candidate",
            "submit_fact_resolution",
        }
        self.assertEqual(set(handlers.keys()), expected)

    def test_inspect_image_bound_handler(self):
        handlers = build_tool_handlers(DATASET)
        res = handlers["inspect_image"](image_id="image_01")
        self.assertEqual(res["image_id"], "image_01")
        self.assertIn("user_03", res.get("user_id", ""))


class OfflineInvestigationTests(unittest.TestCase):
    def test_offline_investigation_success(self):
        state = run_adaptive_investigation(
            dataset=DATASET,
            request_id="request_01",
            client=None,
        )
        self.assertTrue(state.completed)
        self.assertFalse(state.unresolved)
        self.assertGreater(state.tool_calls_taken, 0)
        self.assertIn("profile:user_01", state.evidence_inspected)
        self.assertIn("options:request_01", state.evidence_inspected)

    def test_offline_unknown_request_raises(self):
        with self.assertRaises(ToolError):
            run_adaptive_investigation(
                dataset=DATASET,
                request_id="request_nonexistent",
                client=None,
            )


class ModelDrivenInvestigationTests(unittest.TestCase):
    def _make_mock_client(self, responses: list[CallResult]):
        client = MagicMock()
        client.model = "gpt-6-astra"
        client.create.side_effect = responses
        return client

    def test_submit_fact_resolution_completes_investigation(self):
        tool_call_obj = {
            "type": "function_call",
            "call_id": "call_1",
            "name": "submit_fact_resolution",
            "arguments": {
                "resolution": {
                    "source_type": "event",
                    "source_id": "event_01",
                    "field_name": "amount",
                    "value": 100,
                    "confidence": 0.95,
                    "justification": "Checked event ledger",
                }
            },
        }
        mock_result = CallResult(
            output_text="",
            output_items=(tool_call_obj,),
            status="completed",
            incomplete_reason=None,
            response_id="resp_1",
            provider_request_id="req_1",
            latency_ms=100.0,
            input_tokens=50,
            output_tokens=20,
            reasoning_tokens=0,
            cached_tokens=0,
            retries=0,
        )
        client = self._make_mock_client([mock_result])

        state = run_adaptive_investigation(
            dataset=DATASET,
            request_id="request_01",
            client=client,
        )
        self.assertTrue(state.completed)
        self.assertFalse(state.unresolved)
        self.assertEqual(len(state.facts), 1)
        self.assertIn("Resolved amount = 100", state.decision_summary)

    def test_max_steps_cap_terminates_as_unresolved(self):
        # A tool call that doesn't resolve
        tool_call_obj = {
            "type": "function_call",
            "call_id": "call_1",
            "name": "get_user_context",
            "arguments": {"user_id": "user_01"},
        }
        mock_result = CallResult(
            output_text="",
            output_items=(tool_call_obj,),
            status="completed",
            incomplete_reason=None,
            response_id="resp_loop",
            provider_request_id="req_loop",
            latency_ms=10.0,
            input_tokens=50,
            output_tokens=20,
            reasoning_tokens=0,
            cached_tokens=0,
            retries=0,
        )
        client = self._make_mock_client([mock_result] * 10)

        limits = InvestigationLimits(max_steps=2, max_repeated_calls=10)
        state = run_adaptive_investigation(
            dataset=DATASET,
            request_id="request_01",
            client=client,
            limits=limits,
        )
        self.assertFalse(state.completed)
        self.assertTrue(state.unresolved)
        self.assertIn("step cap", state.unresolved_reason or "")

    def test_repeated_no_progress_tool_calls_terminates(self):
        tool_call_obj = {
            "type": "function_call",
            "call_id": "call_1",
            "name": "get_user_context",
            "arguments": {"user_id": "user_01"},
        }
        mock_result = CallResult(
            output_text="",
            output_items=(tool_call_obj,),
            status="completed",
            incomplete_reason=None,
            response_id="resp_rep",
            provider_request_id="req_rep",
            latency_ms=10.0,
            input_tokens=50,
            output_tokens=20,
            reasoning_tokens=0,
            cached_tokens=0,
            retries=0,
        )
        # Calling the exact same tool with exact same arguments repeatedly
        client = self._make_mock_client([mock_result] * 5)

        limits = InvestigationLimits(max_steps=5, max_repeated_calls=1)
        state = run_adaptive_investigation(
            dataset=DATASET,
            request_id="request_01",
            client=client,
            limits=limits,
        )
        self.assertFalse(state.completed)
        self.assertTrue(state.unresolved)
        self.assertIn("repeated no-progress", state.unresolved_reason or "")

    def test_wall_time_cap_terminates(self):
        # A mock client that sleeps longer than wall time limit
        def _slow_create(**kwargs):
            time.sleep(0.05)
            return CallResult(
                output_text="",
                output_items=({"type": "function_call", "call_id": "c1", "name": "get_user_context", "arguments": {"user_id": "user_01"}},),
                status="completed",
                incomplete_reason=None,
                response_id="r1",
                provider_request_id="p1",
                latency_ms=50.0,
                input_tokens=10,
                output_tokens=10,
                reasoning_tokens=0,
                cached_tokens=0,
                retries=0,
            )

        client = MagicMock()
        client.model = "gpt-6-astra"
        client.create.side_effect = _slow_create

        limits = InvestigationLimits(max_steps=5, max_wall_time_seconds=0.02)
        state = run_adaptive_investigation(
            dataset=DATASET,
            request_id="request_01",
            client=client,
            limits=limits,
        )
        self.assertTrue(state.unresolved)
        self.assertIn("wall time cap", state.unresolved_reason or "")


if __name__ == "__main__":
    unittest.main()
