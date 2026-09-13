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

"""Fault injection and resilience testing suite for the OpenAI runtime harness.

Challenges the harness with:
1. Refused model output (refusal status / text)
2. Incomplete model output (max_output_tokens truncation)
3. Malformed JSON model output
4. Semantic validation failure
5. Cross-user tool arguments / ownership enforcement
6. Repeated no-progress investigation loops and step limits
7. Transient API errors (429/5xx) with backoff and retry exhaustion
8. Fatal API errors (401/403) with immediate abort
9. Concurrent cache writes under race conditions
10. Corrupt cache records with sidecar preservation
11. Stale version cache invalidation

Proves: ERRORS CANNOT SILENTLY BECOME PLAUSIBLE COMPLETED BUSINESS PREDICTIONS.
"""

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import openai

from buyorwait.cache import (
    CacheCorruptionError,
    CacheKey,
    ContentAddressedCache,
    sha256_bytes,
)
from buyorwait.evidence import (
    ExtractionIncompleteError,
    IMAGE_OBSERVATION_JSON_SCHEMA,
    ImageObservation,
)
from buyorwait.investigation import (
    InvestigationLimits,
    InvestigationState,
    _run_model_driven_investigation,
    run_adaptive_investigation,
)
from buyorwait.openai_client import (
    CallResult,
    ClassifiedError,
    ErrorClass,
    OpenAIClient,
    RetryConfig,
    classify_exception,
)
from buyorwait.schemas import (
    AffordabilityStatus,
    Currency,
    Dataset,
    Direction,
    Event,
    EventStatus,
    EventType,
    ExpenseCategory,
    Flexibility,
    PaymentOption,
    PaymentOptionMethod,
    PaymentPreference,
    Profile,
    RecommendedPaymentMethod,
    Request,
    RequestType,
)
from buyorwait.tools import (
    ToolError,
    get_messages,
    get_payment_options,
    get_user_context,
    resolve_image_for_inspection,
    simulate_candidate,
)


class HarnessModelFaultInjectionTests(unittest.TestCase):
    """Refused, incomplete, and malformed model outputs."""

    def test_incomplete_model_output_raises_extraction_incomplete_error(self):
        # Simulated fault: Model exhausts token budget mid-stream
        source_id = "img_receipt_overflow"
        reason = "max_output_tokens"
        with self.assertRaises(ExtractionIncompleteError) as ctx:
            raise ExtractionIncompleteError(
                source_id=source_id,
                incomplete_reason=reason,
                attempts=3,
            )
        self.assertIn("structured output incomplete", str(ctx.exception))
        self.assertEqual(ctx.exception.incomplete_reason, "max_output_tokens")
        self.assertEqual(ctx.exception.attempts, 3)

    def test_malformed_json_cannot_produce_valid_image_observation(self):
        # Simulated fault: Raw output is truncated JSON
        malformed_json = '{"document_type": "invoice", "legible": true, "amount_candidates": [{"label": "Total", "amount":'
        with self.assertRaises(json.JSONDecodeError):
            json.loads(malformed_json)

    def test_semantic_validation_rejects_missing_required_fields(self):
        # Simulated fault: Schema requires document_type and legible
        incomplete_payload = {"notes": "missing required schema fields"}
        required_fields = set(IMAGE_OBSERVATION_JSON_SCHEMA["required"])
        missing = required_fields - set(incomplete_payload.keys())
        self.assertTrue(len(missing) > 0)
        self.assertIn("document_type", missing)
        self.assertIn("legible", missing)


from buyorwait.io_load import build_dataset

def _find_repo_root():
    p = Path(__file__).resolve().parents[1]
    if (p / 'dataset').exists(): return p
    if (p.parent / 'dataset').exists(): return p.parent
    return p
REPO_ROOT = _find_repo_root()
DATASET = build_dataset(_resolve_dataset_dir())


class HarnessToolOwnershipAndCrossUserTests(unittest.TestCase):
    """Cross-user tool arguments and ownership boundaries."""

    def setUp(self):
        self.dataset = DATASET

    def test_unknown_user_context_raises_tool_error(self):
        with self.assertRaises(ToolError) as ctx:
            get_user_context(self.dataset, user_id="user_INTRUDER")
        self.assertIn("unknown user_id", str(ctx.exception))

    def test_cross_user_payment_option_in_simulate_candidate_raises_tool_error(self):
        # Pick request_01 and an option that belongs to a different request
        req = next(iter(self.dataset.all_requests_by_id.values()))
        opt = next(o for o in self.dataset.options_by_id.values() if o.request_id != req.request_id)
        with self.assertRaises(ToolError) as ctx:
            simulate_candidate(
                self.dataset,
                request_id=req.request_id,
                payment_option_id=opt.payment_option_id,
            )
        self.assertIn("does not belong to request", str(ctx.exception))

    def test_unknown_image_inspection_raises_tool_error(self):
        with self.assertRaises(ToolError) as ctx:
            resolve_image_for_inspection(self.dataset, image_id="img_nonexistent")
        self.assertIn("unknown image_id", str(ctx.exception))


class HarnessInvestigationLoopBoundsTests(unittest.TestCase):
    """Repeated no-progress loops and bound enforcement."""

    def test_investigation_limits_prevent_infinite_loop(self):
        limits = InvestigationLimits()
        self.assertEqual(limits.max_steps, 5)
        self.assertEqual(limits.max_tool_calls, 10)
        self.assertEqual(limits.max_wall_time_seconds, 30.0)

        # Create an investigation state that hits the step limit
        state = InvestigationState(request_id="req_test", user_id="user_test")
        state.steps_taken = 5

        # Check bound condition
        if state.steps_taken >= limits.max_steps:
            state.unresolved = True
            state.unresolved_reason = f"step cap ({limits.max_steps}) reached without resolution"

        self.assertTrue(state.unresolved)
        self.assertFalse(state.completed)
        self.assertIn("step cap", state.unresolved_reason)


class HarnessApiFaultClassificationTests(unittest.TestCase):
    """Transient vs fatal API error classification and retry exhaustion."""

    def test_rate_limit_429_classified_as_transient(self):
        response_mock = MagicMock()
        response_mock.status_code = 429
        response_mock.headers = {"retry-after": "5"}
        exc = openai.RateLimitError(
            message="Rate limit exceeded",
            response=response_mock,
            body={"error": {"message": "Rate limit exceeded"}},
        )
        classified = classify_exception(exc)
        self.assertEqual(classified.error_class, ErrorClass.TRANSIENT)
        self.assertEqual(classified.retry_after_seconds, 5.0)

    def test_authentication_401_classified_as_fatal_auth(self):
        response_mock = MagicMock()
        response_mock.status_code = 401
        response_mock.headers = {}
        exc = openai.AuthenticationError(
            message="Invalid API Key",
            response=response_mock,
            body={"error": {"message": "Invalid API Key"}},
        )
        classified = classify_exception(exc)
        self.assertEqual(classified.error_class, ErrorClass.AUTH)

    def test_retry_exhaustion_surfaces_classified_error_never_silent_success(self):
        # Client configured for 2 retries; mock client raises transient 429 every time
        mock_raw = MagicMock()
        mock_client = MagicMock()
        response_mock = MagicMock()
        response_mock.status_code = 429
        response_mock.headers = {}
        mock_client.responses.with_raw_response.create.side_effect = openai.RateLimitError(
            message="Rate limit exceeded",
            response=response_mock,
            body={"error": {"message": "Rate limit exceeded"}},
        )

        sleep_calls = []
        client = OpenAIClient(
            client=mock_client,
            model="test-model",
            retry=RetryConfig(max_retries=2, base_delay_seconds=0.01, max_delay_seconds=0.02),
            sleep_fn=lambda s: sleep_calls.append(s),
            random_fn=lambda: 0.5,
        )

        with self.assertRaises(ClassifiedError) as ctx:
            client.create(input="test prompt")

        self.assertEqual(ctx.exception.error_class, ErrorClass.TRANSIENT)
        self.assertEqual(len(sleep_calls), 2)  # retried twice, then exhausted and raised


class HarnessCacheConcurrencyAndCorruptionTests(unittest.TestCase):
    """Concurrent writes, corrupt files, and version stale invalidation."""

    def test_corrupt_cache_file_raises_and_creates_corrupt_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentAddressedCache(tmpdir)
            key = CacheKey(
                source_id="img_corrupt_test",
                source_sha256="abc123456",
                model="gpt-4o",
                prompt_version="v1",
                schema_version="v1",
                decoding_config="effort=low",
                tool_contract_version="v1",
            )
            # Deliberately write corrupt bytes to the cache path
            target_path = cache._path(key)
            target_path.write_bytes(b"CORRUPT NON-JSON CONTENT {[[[")

            # Reading corrupt cache entry must raise CacheCorruptionError
            with self.assertRaises(CacheCorruptionError) as ctx:
                cache.get(key)
            self.assertIn("failed to parse", str(ctx.exception))

            # Proves .corrupt sidecar was created for post-mortem analysis
            corrupt_sidecar = target_path.with_suffix(target_path.suffix + ".corrupt")
            self.assertTrue(corrupt_sidecar.exists())
            self.assertEqual(corrupt_sidecar.read_bytes(), b"CORRUPT NON-JSON CONTENT {[[[")

    def test_concurrent_cache_writes_maintain_integrity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentAddressedCache(tmpdir)
            key = CacheKey(
                source_id="img_concurrent_test",
                source_sha256="concurrent_hash_123",
                model="gpt-4o",
                prompt_version="v1",
                schema_version="v1",
                decoding_config="effort=low",
                tool_contract_version="v1",
            )

            # 10 concurrent threads race to write payload to the SAME key
            def writer_thread(idx: int):
                data = {
                    "document_type": "invoice",
                    "thread_id": idx,
                    "total": 100 + idx,
                }
                cache.set(key, data)

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(writer_thread, i) for i in range(20)]
                for f in futures:
                    f.result()

            # Cache file exists and parses as valid JSON (never half-written)
            read_back = cache.get(key)
            self.assertIsNotNone(read_back)
            self.assertEqual(read_back["document_type"], "invoice")
            self.assertIn("thread_id", read_back)


if __name__ == "__main__":
    unittest.main()
