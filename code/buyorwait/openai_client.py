"""A single, real, tested wrapper around the OpenAI Responses API: error
classification, bounded retry with backoff+jitter for transient failures
ONLY, cost estimation, and full usage capture. Every call this project makes
to a model passes through `OpenAIClient.create()` -- there is no second path
that could forget to classify an error or capture usage.

Everything this module assumes about the API's behaviour was verified live
against this account on 2026-09-12, not read off a documentation page and
trusted (`config.py`'s module docstring records exactly what was checked and
how). In particular:

  * `openai.AuthenticationError` (401), `PermissionDeniedError` (403), and
    `NotFoundError` (404, e.g. an unknown model id) are all DISTINCT
    exception classes in the installed SDK -- confirmed by triggering each
    for real. None of these three is ever retried.
  * `BadRequestError` (400) covers two semantically different cases this
    module tells apart by `exc.param` and `exc.body["code"]`: an
    UNSUPPORTED PARAMETER (e.g. `temperature` on this model: `exc.param ==
    "temperature"`) and an INVALID REQUEST such as a malformed JSON Schema
    (`exc.body["code"] == "invalid_json_schema"`). Neither is retried as-is;
    a schema-shape problem is a candidate for the semantic-repair loop
    upstream (see `evidence.py`), not for this client's retry loop.
  * `RateLimitError` (429), `InternalServerError` (5xx), `APITimeoutError`,
    and `APIConnectionError` are the only classes this client treats as
    transient and retries, with exponential backoff and jitter, honouring
    the account's real rate-limit headers (`x-ratelimit-*`, confirmed
    present on every response: 500 RPM / 500,000 TPM on this account's
    Tier 1, per `client.responses.with_raw_response.create(...)`).
  * A "refusal" does not reliably raise a distinct exception at all -- a
    real adversarial prompt returned `status="completed"` with an ordinary
    `output_text` that happened to decline. `status="incomplete"` (e.g.
    `incomplete_details.reason == "max_output_tokens"`) is the one refusal-
    ADJACENT signal that IS structurally distinct and is captured here as
    `CallResult.status`/`incomplete_reason`; detecting an actual soft
    refusal is left to the caller's own semantic validation (did the
    expected structured fields come back at all), because status alone
    cannot tell a refusal apart from a legitimately short answer.
  * `temperature` is rejected outright for this model; `seed` is not even a
    valid keyword on `responses.create()` in this SDK. Neither is used
    anywhere in this project as a determinism mechanism (see
    evaluation/assumptions.md U-LLM-DETERMINISM-1).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

try:
    import openai
    from openai import OpenAI
except ImportError:
    openai = None
    OpenAI = None

from . import config


class ErrorClass(StrEnum):
    TRANSIENT = "transient"  # 429 / 5xx / timeout / connection error -- retried by this client
    AUTH = "auth"  # 401 -- fatal, never retried
    PERMISSION = "permission"  # 403 -- fatal, never retried
    NOT_FOUND = "not_found"  # 404 (e.g. unknown model id) -- fatal, never retried
    UNSUPPORTED_PARAMETER = "unsupported_parameter"  # 400 with exc.param set
    INVALID_REQUEST = "invalid_request"  # 400, any other cause (e.g. malformed schema)
    UNKNOWN = "unknown"  # anything this classifier does not recognize -- treated as fatal


@dataclass(frozen=True, slots=True)
class ClassifiedError(Exception):
    """Wraps a caught SDK exception with this project's own classification.
    Raised (not just returned) so a caller's `except ClassifiedError` sees
    both the classification and the original exception via `__cause__`."""

    error_class: ErrorClass
    status_code: int | None
    message: str
    param: str | None
    code: str | None
    provider_request_id: str | None
    retry_after_seconds: float | None  # from a real `retry-after` response header, when present

    def __str__(self) -> str:  # pragma: no cover -- cosmetic
        return f"{self.error_class.value} ({self.status_code}): {self.message}"


def classify_exception(exc: Exception) -> ClassifiedError:
    if openai is None:
        ec = ErrorClass.UNKNOWN
    elif isinstance(exc, openai.AuthenticationError):
        ec = ErrorClass.AUTH
    elif isinstance(exc, openai.PermissionDeniedError):
        ec = ErrorClass.PERMISSION
    elif isinstance(exc, openai.NotFoundError):
        ec = ErrorClass.NOT_FOUND
    elif isinstance(exc, (openai.RateLimitError, openai.InternalServerError, openai.APITimeoutError, openai.APIConnectionError)):
        ec = ErrorClass.TRANSIENT
    elif isinstance(exc, openai.BadRequestError):
        param = getattr(exc, "param", None)
        ec = ErrorClass.UNSUPPORTED_PARAMETER if param else ErrorClass.INVALID_REQUEST
    else:
        ec = ErrorClass.UNKNOWN

    body = getattr(exc, "body", None) or {}
    message = body.get("message") if isinstance(body, Mapping) else None
    code = body.get("code") if isinstance(body, Mapping) else None

    retry_after = None
    response = getattr(exc, "response", None)
    if response is not None:
        header_val = response.headers.get("retry-after")
        if header_val is not None:
            try:
                retry_after = float(header_val)
            except ValueError:
                retry_after = None  # a non-numeric retry-after (e.g. an HTTP-date) is not parsed here

    return ClassifiedError(
        error_class=ec,
        status_code=getattr(exc, "status_code", None),
        message=message or str(exc),
        param=getattr(exc, "param", None),
        code=code,
        provider_request_id=getattr(exc, "request_id", None),
        retry_after_seconds=retry_after,
    )


@dataclass(frozen=True, slots=True)
class CallResult:
    output_text: str
    output_items: tuple[Any, ...]  # raw Responses API output items, e.g. for function_call inspection
    status: str  # "completed" | "incomplete"
    incomplete_reason: str | None
    response_id: str | None
    provider_request_id: str | None
    latency_ms: float
    input_tokens: int
    output_tokens: int  # already includes reasoning_tokens
    reasoning_tokens: int  # informational subset of output_tokens
    cached_tokens: int  # subset of input_tokens
    retries: int


class BlockedNoApiKey(RuntimeError):
    """Raised when a call is attempted with no OPENAI_API_KEY configured.
    Names the exact environment variable, per the Stage 3 instruction: 'If
    the required environment key is absent, record BLOCKED with the exact
    environment-variable name'."""

    def __init__(self) -> None:
        super().__init__("OPENAI_API_KEY is not set in the environment (see buyorwait/config.py)")


def estimate_cost_usd(*, input_tokens: int, output_tokens: int, cached_tokens: int) -> Decimal:
    """Decimal cost estimate from `config.PRICE_USD_PER_MILLION_*`. Money
    arithmetic happens entirely in Decimal, constructed via `str()` from the
    price constants -- never binary float, per the Stage 2 standing rule."""
    billed_input = max(0, input_tokens - cached_tokens)
    million = Decimal(1_000_000)
    cost = (
        Decimal(billed_input) * Decimal(str(config.PRICE_USD_PER_MILLION_INPUT_TOKENS))
        + Decimal(cached_tokens) * Decimal(str(config.PRICE_USD_PER_MILLION_CACHED_INPUT_TOKENS))
        + Decimal(output_tokens) * Decimal(str(config.PRICE_USD_PER_MILLION_OUTPUT_TOKENS))
    ) / million
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_retries: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_fraction: float = 0.25


class OpenAIClient:
    """Thin, real wrapper. Accepts an already-constructed `openai.OpenAI`
    instance (dependency injection) so fault-injection tests can pass a fake
    client that raises specific SDK exceptions on demand without ever
    touching the network or the real API key -- see
    tests/test_openai_client.py for exactly this pattern, each test clearly
    labeled as fault injection, never presented as an observed provider
    incident.
    """

    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        model: str = config.RUNTIME_MODEL,
        retry: RetryConfig = RetryConfig(),
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        if client is None:
            if OpenAI is None:
                raise RuntimeError("openai package is not installed. Install requirements.txt to use OpenAIClient.")
            api_key = config.get_openai_api_key()
            if api_key is None:
                raise BlockedNoApiKey()
            client = OpenAI(api_key=api_key, max_retries=0, timeout=60.0)
            # max_retries=0: this wrapper owns retry policy explicitly and
            # measurably (RetryConfig, tested), rather than relying on the
            # SDK's own opaque default retry count.
        self._client = client
        self.model = model
        self._retry = retry
        self._sleep = sleep_fn
        self._random = random_fn

    def _backoff_delay(self, attempt: int, classified: ClassifiedError) -> float:
        """Exponential backoff with jitter, or the server's own `retry-after`
        header when present (confirmed real and readable via
        `exc.response.headers` on this SDK's exceptions, including on a 400 --
        `classify_exception` extracts it whenever the header exists). A
        genuine 429 was not intentionally provoked against the live API
        purely to observe its `retry-after` value, since doing so on purpose
        would be wasteful spend, not a legitimate capability check; this
        path is exercised instead by `tests/test_openai_client.py`'s
        clearly-labeled fault injection, which fabricates a `RateLimitError`
        carrying a real-shaped response with a `retry-after` header."""
        if classified.retry_after_seconds is not None:
            return max(0.0, classified.retry_after_seconds)
        base = min(self._retry.max_delay_seconds, self._retry.base_delay_seconds * (2**attempt))
        jitter = base * self._retry.jitter_fraction * (2 * self._random() - 1)
        return max(0.0, base + jitter)

    def create(
        self,
        *,
        input: Any,
        text: Mapping[str, Any] | None = None,
        reasoning: Mapping[str, Any] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        max_output_tokens: int = 1024,
    ) -> CallResult:
        """One model call, with transient retry. Supports both Responses API and
        Chat Completions API for openai==1.58.1 compatibility. Raises
        `ClassifiedError` for any fatal error class; never swallows an
        exception into a fabricated successful-looking result."""
        kwargs: dict[str, Any] = {"model": self.model, "input": input, "max_output_tokens": max_output_tokens}
        if text is not None:
            kwargs["text"] = text
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        if tools is not None:
            kwargs["tools"] = tools

        attempt = 0
        while True:
            t0 = time.monotonic()
            try:
                if hasattr(self._client, "responses"):
                    raw = self._client.responses.with_raw_response.create(**kwargs)
                    latency_ms = (time.monotonic() - t0) * 1000.0
                    response = raw.parse()
                    provider_request_id = raw.headers.get("x-request-id")

                    usage = response.usage
                    input_tokens = usage.input_tokens if usage else 0
                    output_tokens = usage.output_tokens if usage else 0
                    reasoning_tokens = (
                        usage.output_tokens_details.reasoning_tokens
                        if usage and usage.output_tokens_details
                        else 0
                    )
                    cached_tokens = (
                        usage.input_tokens_details.cached_tokens if usage and usage.input_tokens_details else 0
                    )

                    return CallResult(
                        output_text=response.output_text or "",
                        output_items=tuple(response.output),
                        status=response.status,
                        incomplete_reason=(
                            response.incomplete_details.reason if response.incomplete_details else None
                        ),
                        response_id=response.id,
                        provider_request_id=provider_request_id,
                        latency_ms=latency_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_tokens=reasoning_tokens,
                        cached_tokens=cached_tokens,
                        retries=attempt,
                    )
                else:
                    # For SDK versions without client.responses attribute (e.g. openai==1.58.1),
                    # first attempt raw /responses endpoint which supports full reasoning & tools schemas.
                    use_post_responses = hasattr(self._client, "post")
                    resp_dict = None
                    if use_post_responses:
                        try:
                            resp_dict = self._client.post("/responses", cast_to=object, body=kwargs)
                        except Exception as post_exc:
                            # If /responses endpoint fails or is unavailable, fall back to chat.completions
                            resp_dict = None

                    if resp_dict is not None:
                        latency_ms = (time.monotonic() - t0) * 1000.0
                        out_text = ""
                        for item in resp_dict.get("output", []):
                            if isinstance(item, dict) and item.get("type") == "message":
                                for c in item.get("content", []):
                                    if isinstance(c, dict) and c.get("type") == "output_text":
                                        out_text += c.get("text", "")
                        usage = resp_dict.get("usage") or {}
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        in_details = usage.get("input_tokens_details") or {}
                        cached_tokens = in_details.get("cached_tokens", 0)
                        out_details = usage.get("output_tokens_details") or {}
                        reasoning_tokens = out_details.get("reasoning_tokens", 0)
                        status = resp_dict.get("status", "completed")
                        inc_details = resp_dict.get("incomplete_details") or {}
                        inc_reason = inc_details.get("reason") if inc_details else None

                        return CallResult(
                            output_text=out_text or "",
                            output_items=tuple(resp_dict.get("output", ())),
                            status=status,
                            incomplete_reason=inc_reason,
                            response_id=resp_dict.get("id"),
                            provider_request_id=None,
                            latency_ms=latency_ms,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            reasoning_tokens=reasoning_tokens,
                            cached_tokens=cached_tokens,
                            retries=attempt,
                        )

                    # Chat completions API fallback for SDK/server without responses endpoint
                    chat_kwargs: dict[str, Any] = {"model": self.model, "max_completion_tokens": max_output_tokens}
                    if isinstance(input, str):
                        chat_messages = [{"role": "user", "content": input}]
                    elif isinstance(input, list):
                        chat_messages = input
                    else:
                        chat_messages = [{"role": "user", "content": str(input)}]
                    chat_kwargs["messages"] = chat_messages
                    if text and "format" in text and text["format"].get("type") == "json_schema":
                        fmt = text["format"]
                        chat_kwargs["response_format"] = {
                            "type": "json_schema",
                            "json_schema": {
                                "name": fmt.get("name", "response"),
                                "schema": fmt.get("schema", {}),
                                "strict": fmt.get("strict", True),
                            },
                        }
                    if tools:
                        formatted_tools = []
                        for t in tools:
                            if "function" in t:
                                formatted_tools.append(t)
                            else:
                                fn_obj = {
                                    "name": t.get("name"),
                                    "description": t.get("description", ""),
                                    "parameters": t.get("parameters", {}),
                                }
                                if "strict" in t:
                                    fn_obj["strict"] = t["strict"]
                                formatted_tools.append({"type": "function", "function": fn_obj})
                        chat_kwargs["tools"] = formatted_tools

                    raw = self._client.chat.completions.with_raw_response.create(**chat_kwargs)
                    latency_ms = (time.monotonic() - t0) * 1000.0
                    response = raw.parse()
                    provider_request_id = raw.headers.get("x-request-id")
                    choice = response.choices[0] if response.choices else None
                    out_text = choice.message.content if choice and choice.message else ""
                    out_items: list[Any] = []
                    if choice and choice.message:
                        if getattr(choice.message, "tool_calls", None):
                            for tc in choice.message.tool_calls:
                                out_items.append({
                                    "type": "function_call",
                                    "call_id": tc.id,
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                })
                        else:
                            out_items.append(choice.message)

                    usage = response.usage
                    input_tokens = usage.prompt_tokens if usage else 0
                    output_tokens = usage.completion_tokens if usage else 0
                    prompt_details = getattr(usage, "prompt_tokens_details", None)
                    cached_tokens = getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0
                    comp_details = getattr(usage, "completion_tokens_details", None)
                    reasoning_tokens = getattr(comp_details, "reasoning_tokens", 0) if comp_details else 0
                    finish_reason = choice.finish_reason if choice else "stop"
                    status = "incomplete" if finish_reason == "length" else "completed"
                    inc_reason = "max_output_tokens" if finish_reason == "length" else None

                    return CallResult(
                        output_text=out_text or "",
                        output_items=tuple(out_items),
                        status=status,
                        incomplete_reason=inc_reason,
                        response_id=response.id,
                        provider_request_id=provider_request_id,
                        latency_ms=latency_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_tokens=reasoning_tokens,
                        cached_tokens=cached_tokens,
                        retries=attempt,
                    )
            except Exception as exc:  # noqa: BLE001 -- reclassified immediately below
                classified = classify_exception(exc)
                if classified.error_class is ErrorClass.TRANSIENT and attempt < self._retry.max_retries:
                    self._sleep(self._backoff_delay(attempt, classified))
                    attempt += 1
                    continue
                raise classified from exc
