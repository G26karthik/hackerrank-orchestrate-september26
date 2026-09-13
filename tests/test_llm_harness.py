import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/buyorwait/llm_harness.py.

Covers:
  * Cache hit path (serves from ContentAddressedCache without calling model).
  * Fresh call path (invokes client.create, records usage in ledger, writes cache).
  * Repair loop on schema validation failure (recovers after repair attempt).
  * Repair budget exhaustion (raises ClassifiedError when invalid beyond max_repairs).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from buyorwait.cache import ContentAddressedCache
from buyorwait.llm_harness import ExtractionRequest, LLMHarness
from buyorwait.metering import UsageLedger
from buyorwait.openai_client import CallResult, ClassifiedError, ErrorClass


class LLMHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache = ContentAddressedCache(Path(self.temp_dir.name))
        self.ledger = UsageLedger()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_live_call_and_cache_store(self):
        client = MagicMock()
        client.model = "gpt-6-astra"
        client.create.return_value = CallResult(
            output_text=json.dumps({"name": "item1", "price": 45.5}),
            output_items=(),
            status="completed",
            incomplete_reason=None,
            response_id="resp_harness_1",
            provider_request_id="req_harness_1",
            latency_ms=120.0,
            input_tokens=100,
            output_tokens=30,
            reasoning_tokens=0,
            cached_tokens=0,
            retries=0,
        )

        harness = LLMHarness(client=client, cache=self.cache, ledger=self.ledger)
        req = ExtractionRequest(
            purpose="test_extract",
            prompt="Extract price",
            schema={"type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}}, "required": ["name", "price"]},
            cache_key="key_01",
            source_id="item_01",
            source_bytes_sha256="abc123hash",
        )

        res = harness.extract(req)
        self.assertFalse(res.from_cache)
        self.assertEqual(res.parsed["name"], "item1")
        self.assertEqual(res.parsed["price"], 45.5)
        self.assertEqual(len(self.ledger.records), 1)

        # Second call should hit the cache!
        client.create.reset_mock()
        res2 = harness.extract(req)
        self.assertTrue(res2.from_cache)
        self.assertEqual(res2.parsed["name"], "item1")
        client.create.assert_not_called()

    def test_repair_loop_succeeds_on_second_attempt(self):
        client = MagicMock()
        client.model = "gpt-6-astra"

        bad_call = CallResult(
            output_text=json.dumps({"name": "item1"}),  # missing required 'price'
            output_items=(),
            status="completed",
            incomplete_reason=None,
            response_id="resp_bad",
            provider_request_id="req_bad",
            latency_ms=100.0,
            input_tokens=50,
            output_tokens=20,
            reasoning_tokens=0,
            cached_tokens=0,
            retries=0,
        )
        good_call = CallResult(
            output_text=json.dumps({"name": "item1", "price": 99.0}),
            output_items=(),
            status="completed",
            incomplete_reason=None,
            response_id="resp_good",
            provider_request_id="req_good",
            latency_ms=110.0,
            input_tokens=60,
            output_tokens=25,
            reasoning_tokens=0,
            cached_tokens=0,
            retries=0,
        )
        client.create.side_effect = [bad_call, good_call]

        harness = LLMHarness(client=client, cache=self.cache, ledger=self.ledger)
        req = ExtractionRequest(
            purpose="test_repair",
            prompt="Extract name and price",
            schema={"type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}}, "required": ["name", "price"]},
            cache_key="key_repair",
            source_id="repair_01",
            source_bytes_sha256="repairhash",
        )

        res = harness.extract(req, max_repairs=2)
        self.assertFalse(res.from_cache)
        self.assertEqual(res.parsed["price"], 99.0)
        self.assertEqual(client.create.call_count, 2)
        self.assertEqual(len(self.ledger.records), 2)
        self.assertEqual(self.ledger.records[1].repair_attempts, 1)

    def test_repair_budget_exhaustion_raises(self):
        client = MagicMock()
        client.model = "gpt-6-astra"

        bad_call = CallResult(
            output_text="not valid json at all",
            output_items=(),
            status="completed",
            incomplete_reason=None,
            response_id="resp_bad",
            provider_request_id="req_bad",
            latency_ms=100.0,
            input_tokens=50,
            output_tokens=20,
            reasoning_tokens=0,
            cached_tokens=0,
            retries=0,
        )
        client.create.return_value = bad_call

        harness = LLMHarness(client=client, cache=self.cache, ledger=self.ledger)
        req = ExtractionRequest(
            purpose="test_fail",
            prompt="Extract something",
            schema={"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
            cache_key="key_fail",
            source_id="fail_01",
            source_bytes_sha256="failhash",
        )

        with self.assertRaises(ClassifiedError) as ctx:
            harness.extract(req, max_repairs=1)
        self.assertEqual(ctx.exception.error_class, ErrorClass.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
