from __future__ import annotations

import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)


import types
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

import openai

from buyorwait.openai_client import (
    BlockedNoApiKey,
    ClassifiedError,
    ErrorClass,
    OpenAIClient,
    RetryConfig,
    classify_exception,
    estimate_cost_usd,
)


def _fake_http_response(headers: dict[str, str] | None = None):
    resp = MagicMock()
    resp.headers = headers or {}
    return resp


def _make_openai_exc(cls, *, status_code, body, request_id="req_fake", response=None):
    exc = cls.__new__(cls)
    exc.status_code = status_code
    exc.body = body
    exc.request_id = request_id
    exc.param = body.get("param") if isinstance(body, dict) else None
    exc.response = response or _fake_http_response()
    exc.args = (body.get("message", "") if isinstance(body, dict) else "",)
    return exc


class ClassifyExceptionTests(unittest.TestCase):
    def test_auth_error_classified_and_never_retryable(self):
        exc = _make_openai_exc(
            openai.AuthenticationError, status_code=401,
            body={"message": "Incorrect API key provided", "type": "invalid_request_error", "code": None},
        )
        c = classify_exception(exc)
        self.assertEqual(c.error_class, ErrorClass.AUTH)
        self.assertEqual(c.status_code, 401)

    def test_unsupported_parameter_distinguished_from_invalid_request(self):
        # shaped exactly like the real captured temperature rejection
        exc = _make_openai_exc(
            openai.BadRequestError, status_code=400,
            body={"message": "Unsupported parameter: 'temperature' is not supported with this model.",
                  "type": "invalid_request_error", "param": "temperature", "code": None},
        )
        c = classify_exception(exc)
        self.assertEqual(c.error_class, ErrorClass.UNSUPPORTED_PARAMETER)
        self.assertEqual(c.param, "temperature")

    def test_malformed_schema_classified_as_invalid_request_not_unsupported_parameter(self):
        # shaped exactly like the real captured invalid_json_schema error
        exc = _make_openai_exc(
            openai.BadRequestError, status_code=400,
            body={"message": "Invalid schema for response_format 'bad'", "type": "invalid_request_error",
                  "param": None, "code": "invalid_json_schema"},
        )
        c = classify_exception(exc)
        self.assertEqual(c.error_class, ErrorClass.INVALID_REQUEST)
        self.assertEqual(c.code, "invalid_json_schema")

    def test_not_found_classified_for_unknown_model(self):
        exc = _make_openai_exc(
            openai.NotFoundError, status_code=404,
            body={"message": "The model does not exist", "type": "invalid_request_error", "code": "model_not_found"},
        )
        c = classify_exception(exc)
        self.assertEqual(c.error_class, ErrorClass.NOT_FOUND)

    def test_rate_limit_classified_transient_with_retry_after_header(self):
        exc = _make_openai_exc(
            openai.RateLimitError, status_code=429,
            body={"message": "Rate limit exceeded", "type": "requests", "code": "rate_limit_exceeded"},
            response=_fake_http_response({"retry-after": "2.5"}),
        )
        c = classify_exception(exc)
        self.assertEqual(c.error_class, ErrorClass.TRANSIENT)
        self.assertEqual(c.retry_after_seconds, 2.5)

    def test_internal_server_error_classified_transient(self):
        exc = _make_openai_exc(openai.InternalServerError, status_code=500, body={"message": "boom", "type": "server_error", "code": None})
        self.assertEqual(classify_exception(exc).error_class, ErrorClass.TRANSIENT)


class EstimateCostTests(unittest.TestCase):
    def test_matches_hand_calculation(self):
        # By hand: cost = (billed_input * price_input + output * price_output) / 1,000,000
        # price_input=$10/1M, price_output=$50/1M (config.PRICE_USD_PER_MILLION_*).
        # 1000 input @ $10/1M = 1000*10/1e6 = 0.01
        # 500 output @ $50/1M = 500*50/1e6 = 0.025
        # total = 0.01 + 0.025 = 0.035
        # Independently re-verified via a separate Decimal computation before fixing this
        # test (see the session's evaluation/state.md Stage 3 reversal log): this project's
        # OWN test comment initially had the arithmetic wrong by a factor of 1000, not the
        # implementation -- corrected here, not in openai_client.py.
        cost = estimate_cost_usd(input_tokens=1000, output_tokens=500, cached_tokens=0)
        self.assertEqual(cost, Decimal("0.035000"))

    def test_cached_tokens_priced_separately_and_excluded_from_billed_input(self):
        # By hand: 1000 input total, 400 cached -> billed_input=600 @ $10/1M, cached 400 @ $1/1M.
        # cost = (600*10 + 400*1) / 1e6 = (6000+400)/1e6 = 6400/1e6 = 0.0064
        cost = estimate_cost_usd(input_tokens=1000, output_tokens=0, cached_tokens=400)
        self.assertEqual(cost, Decimal("0.006400"))
        self.assertEqual(cost.as_tuple().exponent, -6)  # quantized to 6 decimal places


class FakeClientBuilder:
    """Builds a fake `openai.OpenAI`-shaped object whose
    `.responses.with_raw_response.create(...)` either raises a sequence of
    prepared exceptions or returns a prepared fake response. Used ONLY for
    this project's own fault-injection tests -- never presented as real
    provider behaviour."""

    def __init__(self, script: list):
        self._script = list(script)
        self.call_count = 0
        client = MagicMock()

        def _create(**_kwargs):
            self.call_count += 1
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        client.responses.with_raw_response.create.side_effect = _create
        self.client = client


def _fake_raw_response(*, output_text="ok", status="completed", incomplete_reason=None,
                        input_tokens=10, output_tokens=5, reasoning_tokens=0, cached_tokens=0,
                        response_id="resp_fake", request_id_header="req_fake", output_items=()):
    parsed = MagicMock()
    parsed.output_text = output_text
    parsed.status = status
    parsed.incomplete_details = types.SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None
    parsed.id = response_id
    parsed.output = list(output_items)
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.output_tokens_details = types.SimpleNamespace(reasoning_tokens=reasoning_tokens)
    usage.input_tokens_details = types.SimpleNamespace(cached_tokens=cached_tokens)
    parsed.usage = usage

    raw = MagicMock()
    raw.headers = {"x-request-id": request_id_header}
    raw.parse.return_value = parsed
    return raw


class TransientRetryFaultInjectionTests(unittest.TestCase):
    """[FAULT INJECTION] Simulated 429/5xx failures followed by success --
    the live API's actual real transient-failure rate was not measured
    (none occurred during this stage's real capability pilot); this
    validates the retry PATH this project's own code takes, not a claim
    about the provider's real reliability."""

    def test_retries_transient_error_then_succeeds(self):
        exc = _make_openai_exc(openai.RateLimitError, status_code=429, body={"message": "rate limited", "type": "requests", "code": "rate_limit_exceeded"})
        builder = FakeClientBuilder([exc, _fake_raw_response(output_text="recovered")])
        client = OpenAIClient(client=builder.client, sleep_fn=lambda _s: None, random_fn=lambda: 0.5)
        result = client.create(input="hi")
        self.assertEqual(result.output_text, "recovered")
        self.assertEqual(result.retries, 1)
        self.assertEqual(builder.call_count, 2)

    def test_exhausts_retries_and_raises_classified_error(self):
        exc = _make_openai_exc(openai.InternalServerError, status_code=500, body={"message": "boom", "type": "server_error", "code": None})
        builder = FakeClientBuilder([exc, exc, exc])
        client = OpenAIClient(client=builder.client, retry=RetryConfig(max_retries=2), sleep_fn=lambda _s: None, random_fn=lambda: 0.5)
        with self.assertRaises(ClassifiedError) as ctx:
            client.create(input="hi")
        self.assertEqual(ctx.exception.error_class, ErrorClass.TRANSIENT)
        self.assertEqual(builder.call_count, 3)  # initial + 2 retries

    def test_fatal_auth_error_is_never_retried(self):
        exc = _make_openai_exc(openai.AuthenticationError, status_code=401, body={"message": "bad key", "type": "invalid_request_error", "code": None})
        builder = FakeClientBuilder([exc])
        client = OpenAIClient(client=builder.client, retry=RetryConfig(max_retries=5), sleep_fn=lambda _s: None)
        with self.assertRaises(ClassifiedError) as ctx:
            client.create(input="hi")
        self.assertEqual(ctx.exception.error_class, ErrorClass.AUTH)
        self.assertEqual(builder.call_count, 1)  # no retry attempted


class IncompleteOutputTests(unittest.TestCase):
    def test_incomplete_status_and_reason_surfaced(self):
        builder = FakeClientBuilder([_fake_raw_response(output_text="", status="incomplete", incomplete_reason="max_output_tokens")])
        client = OpenAIClient(client=builder.client)
        result = client.create(input="write an essay", max_output_tokens=16)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.incomplete_reason, "max_output_tokens")


class UsageCaptureTests(unittest.TestCase):
    def test_reasoning_tokens_reported_as_subset_not_added(self):
        builder = FakeClientBuilder([_fake_raw_response(output_tokens=17, reasoning_tokens=10, input_tokens=20)])
        client = OpenAIClient(client=builder.client)
        result = client.create(input="hi")
        self.assertEqual(result.output_tokens, 17)
        self.assertEqual(result.reasoning_tokens, 10)

    def test_response_id_and_provider_request_id_both_captured_and_distinct(self):
        builder = FakeClientBuilder([_fake_raw_response(response_id="resp_A", request_id_header="req_B")])
        client = OpenAIClient(client=builder.client)
        result = client.create(input="hi")
        self.assertEqual(result.response_id, "resp_A")
        self.assertEqual(result.provider_request_id, "req_B")
        self.assertNotEqual(result.response_id, result.provider_request_id)


class BlockedNoApiKeyTests(unittest.TestCase):
    def test_missing_key_raises_blocked_with_exact_env_var_name(self):
        import buyorwait.config as config_module

        original = config_module.get_openai_api_key
        config_module.get_openai_api_key = lambda: None
        try:
            with self.assertRaises(BlockedNoApiKey) as ctx:
                OpenAIClient()
            self.assertIn("OPENAI_API_KEY", str(ctx.exception))
        finally:
            config_module.get_openai_api_key = original


if __name__ == "__main__":
    unittest.main()
