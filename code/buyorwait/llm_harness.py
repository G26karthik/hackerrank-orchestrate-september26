"""Runtime LLM harness: adapter, validation/repair loop, cache, usage capture.

Responsibility (per the Stage 2 module table and Stage 3 prompt):
  SDK adapter, tool loop, validation/repair, usage, retries, cache, resume.

Features:
  * Content-addressed caching: avoids redundant calls for identical inputs.
  * Validation & repair: on JSON/schema mismatch, retries with a repair prompt
    quoting the exact validation error up to `max_repairs` times.
  * Usage recording: captures tokens, cost, latency, retries into `UsageLedger`.
  * Safe error handling: classifies exceptions and does not swallow fatal errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from . import config
from .cache import CacheKey, ContentAddressedCache
from .metering import UsageLedger, UsageRecord
from .openai_client import (
    CallResult,
    ClassifiedError,
    ErrorClass,
    OpenAIClient,
    estimate_cost_usd,
)


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    content: Any


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    purpose: str  # e.g. "evidence_extraction:message", "evidence_extraction:image"
    prompt: str
    schema: Mapping[str, Any]  # JSON Schema the response must satisfy
    cache_key: str  # e.g. f"{source_id}:{sha256}:{schema_version}"
    reasoning_effort: str = config.DEFAULT_REASONING_EFFORT
    source_bytes_sha256: str = ""
    source_id: str = ""


@dataclass(frozen=True, slots=True)
class ExtractionResponse:
    parsed: Any
    raw_response_id: str
    from_cache: bool


class SchemaValidationError(Exception):
    """Raised when structured output fails schema validation."""


def validate_json_schema(data: Any, schema: Mapping[str, Any]) -> None:
    """Basic validation for required fields and types according to schema."""
    if not isinstance(data, dict):
        raise SchemaValidationError(f"Expected JSON object (dict), got {type(data).__name__}")

    required = schema.get("required", [])
    for field_name in required:
        if field_name not in data:
            raise SchemaValidationError(f"Missing required field: {field_name!r}")

    properties = schema.get("properties", {})
    for k, v in data.items():
        if k in properties:
            prop_def = properties[k]
            expected_type = prop_def.get("type")
            if expected_type == "string" and not isinstance(v, (str, type(None))):
                raise SchemaValidationError(f"Field {k!r} expected string, got {type(v).__name__}")
            elif expected_type == "number" and not isinstance(v, (int, float, type(None))):
                raise SchemaValidationError(f"Field {k!r} expected number, got {type(v).__name__}")
            elif expected_type == "boolean" and not isinstance(v, (bool, type(None))):
                raise SchemaValidationError(f"Field {k!r} expected boolean, got {type(v).__name__}")
            elif expected_type == "array" and not isinstance(v, (list, tuple)):
                raise SchemaValidationError(f"Field {k!r} expected list, got {type(v).__name__}")


class LLMHarness:
    """Central harness managing model calls, disk cache, repair loops, and metering."""

    def __init__(
        self,
        *,
        client: OpenAIClient | None = None,
        cache: ContentAddressedCache | None = None,
        ledger: UsageLedger | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._ledger = ledger if ledger is not None else UsageLedger()

    @property
    def ledger(self) -> UsageLedger:
        return self._ledger

    def extract(
        self,
        request: ExtractionRequest,
        *,
        max_repairs: int = 2,
        run_id: str = "run",
        evaluation_request_id: str | None = None,
    ) -> ExtractionResponse:
        """Executes a structured extraction request with cache lookup and repair loop."""
        # 1. Check Cache
        ck = None
        if self._cache is not None:
            ck = CacheKey(
                source_id=request.source_id or request.cache_key,
                source_sha256=request.source_bytes_sha256 or "none",
                model=self._client.model if self._client else config.RUNTIME_MODEL,
                prompt_version="v1",
                schema_version="v1",
                decoding_config=f"effort={request.reasoning_effort}",
                tool_contract_version="v1",
            )
            cached = self._cache.get(ck)
            if cached is not None:
                return ExtractionResponse(
                    parsed=cached["parsed"],
                    raw_response_id=cached.get("provider_response_id", "cached"),
                    from_cache=True,
                )

        if self._client is None:
            self._client = OpenAIClient(model=config.RUNTIME_MODEL)

        # 2. Live Call & Repair Loop
        current_prompt = request.prompt
        repairs = 0
        last_call_result: CallResult | None = None

        while True:
            call_res = self._client.create(
                input=[{"role": "user", "content": [{"type": "input_text", "text": current_prompt}]}],
                text={"format": {"type": "json_schema", "name": "structured_output", "schema": dict(request.schema), "strict": True}},
                reasoning={"effort": request.reasoning_effort},
                max_output_tokens=2000,
            )
            last_call_result = call_res

            # Record usage
            cost = estimate_cost_usd(
                input_tokens=call_res.input_tokens,
                output_tokens=call_res.output_tokens,
                cached_tokens=call_res.cached_tokens,
            )
            self._ledger.record(
                UsageRecord(
                    provider="openai",
                    model=self._client.model,
                    purpose=request.purpose,
                    run_id=run_id,
                    evaluation_request_id=evaluation_request_id,
                    input_tokens=call_res.input_tokens,
                    output_tokens=call_res.output_tokens,
                    reasoning_tokens=call_res.reasoning_tokens,
                    cached_tokens=call_res.cached_tokens,
                    cost_usd=cost,
                    pricing_version=config.PRICING_VERSION,
                    provider_response_id=call_res.response_id,
                    provider_request_id=call_res.provider_request_id,
                    latency_ms=call_res.latency_ms,
                    retries=call_res.retries,
                    repair_attempts=repairs,
                    cache_hit=False,
                )
            )

            try:
                parsed = json.loads(call_res.output_text)
                validate_json_schema(parsed, request.schema)
                break
            except (json.JSONDecodeError, SchemaValidationError) as err:
                if repairs >= max_repairs:
                    raise ClassifiedError(
                        error_class=ErrorClass.INVALID_REQUEST,
                        status_code=400,
                        message=f"Extraction repair budget exceeded: {err}",
                        param=None,
                        code="schema_validation_failed",
                        provider_request_id=call_res.provider_request_id,
                        retry_after_seconds=None,
                    ) from err

                repairs += 1
                current_prompt = (
                    f"{request.prompt}\n\n"
                    f"PREVIOUS RESPONSE FAILED VALIDATION:\n"
                    f"{err}\n"
                    f"Please repair the response so it satisfies the required JSON schema strictly."
                )

        # 3. Store in cache
        if self._cache is not None and ck is not None:
            self._cache.set(
                ck,
                {
                    "parsed": parsed,
                    "model": self._client.model,
                    "reasoning_effort": request.reasoning_effort,
                    "provider_response_id": last_call_result.response_id if last_call_result else None,
                },
            )

        return ExtractionResponse(
            parsed=parsed,
            raw_response_id=last_call_result.response_id if last_call_result else "unknown",
            from_cache=False,
        )
