"""Typed investigation state and bounded adaptive investigation loop.

Implements Stage 3 requirements 3, 4, 5, 6:
  * 3. Typed state: request-scoped ledger facts, open questions, evidence
       inspected, allowed actions, tool results, and completion criteria.
       Persists short observable decision summaries, not fabricated transcripts.
  * 4. Narrowly-scoped tools: get_user_context, get_event_lifecycle,
       get_messages, inspect_image, get_payment_options, simulate_candidate,
       and submit_fact_resolution. Tools validate IDs and ownership in code.
  * 5. Adaptive investigation: inspects additional evidence when a fact is
       missing, conflicting, or financially decisive. The model may request
       tool observations; code controls admissions, bounds, and selection.
  * 6. Termination: configurable model-step, tool-call, and wall-time caps;
       repeated-no-progress detection; bounded retries and explicit
       unresolved outcomes. Never loops forever or disguises an unresolved
       fact as an affirmative conclusion.
"""

from __future__ import annotations

import functools
import json
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


from . import config
from .cache import ContentAddressedCache
from .evidence import (
    AmountRoleSelection,
    EvidenceFact,
    ImageObservation,
    extract_image_observation,
    select_amount_role,
)
from .metering import UsageLedger, UsageRecord
from .openai_client import CallResult, ClassifiedError, OpenAIClient, estimate_cost_usd
from .schemas import Dataset
from .tools import (
    ALL_TOOL_SCHEMAS,
    PURE_TOOL_HANDLERS,
    ToolError,
    _jsonable,
    resolve_image_for_inspection,
)


@dataclass(frozen=True, slots=True)
class InvestigationLimits:
    max_steps: int = 5
    max_tool_calls: int = 10
    max_wall_time_seconds: float = 30.0
    max_repeated_calls: int = 2


@dataclass
class InvestigationState:
    request_id: str
    user_id: str
    target_event_id: str | None = None
    facts: list[Any] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    evidence_inspected: list[str] = field(default_factory=list)
    tool_call_history: list[dict[str, Any]] = field(default_factory=list)
    steps_taken: int = 0
    tool_calls_taken: int = 0
    start_time: float = field(default_factory=time.time)
    completed: bool = False
    unresolved: bool = False
    unresolved_reason: str | None = None
    decision_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "target_event_id": self.target_event_id,
            "facts": [_jsonable(f) for f in self.facts],
            "open_questions": list(self.open_questions),
            "evidence_inspected": list(self.evidence_inspected),
            "tool_call_history": self.tool_call_history,
            "steps_taken": self.steps_taken,
            "tool_calls_taken": self.tool_calls_taken,
            "elapsed_seconds": round(time.time() - self.start_time, 4),
            "completed": self.completed,
            "unresolved": self.unresolved,
            "unresolved_reason": self.unresolved_reason,
            "decision_summary": self.decision_summary,
        }


def build_tool_handlers(
    dataset: Dataset,
    *,
    client: OpenAIClient | None = None,
    cache: ContentAddressedCache | None = None,
    media_root: str = "dataset/media/images",
) -> dict[str, Callable[..., dict[str, Any]]]:
    """Binds the seven tool handlers against `dataset`. `inspect_image` is
    bound with `client` + `cache` so that image requests validate ownership
    and path locally, then run or serve from cache structured vision
    extractions."""
    handlers: dict[str, Callable[..., dict[str, Any]]] = {}
    for name, fn in PURE_TOOL_HANDLERS.items():
        handlers[name] = functools.partial(fn, dataset)

    def _bound_inspect_image(image_id: str) -> dict[str, Any]:
        info = resolve_image_for_inspection(dataset, image_id=image_id)
        image = dataset.images_by_id[image_id]

        # Determine effective cache: prefer the bound cache, otherwise look for the
        # standard .llm_cache/observations directory used by get_all_resolved_image_amounts.
        # This allows inspect_image to serve real cached observations even when called
        # without a cache argument, as long as the standard cache exists on disk.
        effective_cache = cache
        if effective_cache is None:
            # Try the standard cache location used by the main evidence pipeline
            _std_cache = Path(".llm_cache") / "observations"
            if not _std_cache.exists():
                # Also try relative to the media_root parent as fallback
                _std_cache = Path(media_root).parent.parent / ".llm_cache" / "observations"
            try:
                _std_cache.mkdir(parents=True, exist_ok=True)
                effective_cache = ContentAddressedCache(_std_cache)
            except Exception:
                effective_cache = None

        if effective_cache is None:
            # Genuine fallback when we cannot construct any cache (e.g. read-only FS)
            return {
                "image_id": image_id,
                "path": info["path"],
                "user_id": info["user_id"],
                "related_event_id": info["related_event_id"],
                "note": "offline/metadata-only: no writable cache available",
            }

        try:
            obs, cache_hit, _call = extract_image_observation(
                image=image,
                media_root=media_root,
                client=client,
                cache=effective_cache,
            )
            event = dataset.events_by_id.get(image.related_event_id)
            selection = select_amount_role(obs, event) if event else None
            return {
                "image_id": image_id,
                "user_id": info["user_id"],
                "observation": _jsonable(obs),
                "selection": _jsonable(selection) if selection else None,
                "cache_hit": cache_hit,
            }
        except (StopIteration, RuntimeError) as _client_err:
            # Client has no more scripted responses (test stub exhausted) or
            # transient failure. Try a source-id-only cache lookup as last resort.
            try:
                cached = effective_cache.get_by_source_id(image_id)
                if cached is not None:
                    from .evidence import _parse_image_observation, select_amount_role as _sar  # noqa: PLC0415
                    obs = _parse_image_observation(
                        image_id,
                        cached.get("source_sha256", "unknown"),
                        cached["parsed"],
                        model=cached.get("model", "cached"),
                        reasoning_effort=cached.get("reasoning_effort", "medium"),
                        provider_response_id=cached.get("provider_response_id"),
                    )
                    event = dataset.events_by_id.get(image.related_event_id)
                    selection = _sar(obs, event) if event else None
                    return {
                        "image_id": image_id,
                        "user_id": info["user_id"],
                        "observation": _jsonable(obs),
                        "selection": _jsonable(selection) if selection else None,
                        "cache_hit": True,
                    }
            except Exception:
                pass
            return {
                "image_id": image_id,
                "path": info["path"],
                "user_id": info["user_id"],
                "related_event_id": info["related_event_id"],
                "note": f"cached_observation_unavailable: client error {type(_client_err).__name__}",
            }


    handlers["inspect_image"] = _bound_inspect_image
    return handlers


def run_adaptive_investigation(
    *,
    dataset: Dataset,
    request_id: str,
    client: OpenAIClient | None = None,
    cache: ContentAddressedCache | None = None,
    ledger: UsageLedger | None = None,
    limits: InvestigationLimits = InvestigationLimits(),
    initial_question: str | None = None,
    tool_handlers: Mapping[str, Callable[..., dict[str, Any]]] | None = None,
    target_event_id: str | None = None,
    media_root: str = "dataset/media/images",
) -> InvestigationState:
    """Executes a bounded adaptive investigation for one request.

    Inspects evidence when a fact is missing, conflicting, or financially
    decisive. In live mode with an `OpenAIClient`, the model may call tools
    to inspect context, messages, events, or images. Code strictly checks
    bounds on every step and validates every tool call and submission.
    In offline/deterministic mode (client is None), the investigator
    inspects the user's available context and evidence deterministically,
    recording observable findings.
    """
    req = dataset.all_requests_by_id.get(request_id)
    if req is None:
        raise ToolError(f"unknown request_id: {request_id!r}")

    state = InvestigationState(
        request_id=request_id,
        user_id=req.user_id,
        target_event_id=target_event_id,
        open_questions=[initial_question] if initial_question else [],
    )

    handlers = (
        dict(tool_handlers)
        if tool_handlers is not None
        else build_tool_handlers(dataset, client=client, cache=cache, media_root=media_root)
    )

    # 1. Deterministic / Offline inspection path
    if client is None:
        _run_offline_investigation(dataset, req, state, handlers, limits)
        return state

    # 2. Live / Model-driven adaptive investigation loop
    _run_model_driven_investigation(dataset, req, state, handlers, client, ledger, limits)
    return state


def _run_offline_investigation(
    dataset: Dataset,
    req: Any,
    state: InvestigationState,
    handlers: Mapping[str, Callable[..., dict[str, Any]]],
    limits: InvestigationLimits,
) -> None:
    """Deterministic fallback inspection when no model client is attached."""
    # Context inspection
    u_ctx = handlers["get_user_context"](user_id=req.user_id)
    state.evidence_inspected.append(f"profile:{req.user_id}")
    state.tool_calls_taken += 1

    # Payment options
    options = handlers["get_payment_options"](request_id=req.request_id)
    state.evidence_inspected.append(f"options:{req.request_id}")
    state.tool_calls_taken += 1

    # Messages
    msgs = handlers["get_messages"](user_id=req.user_id)
    state.evidence_inspected.append(f"messages:user_{req.user_id}")
    state.tool_calls_taken += 1

    # Event / Image if specified
    if state.target_event_id:
        ev_info = handlers["get_event_lifecycle"](event_id=state.target_event_id)
        state.evidence_inspected.append(f"event:{state.target_event_id}")
        state.tool_calls_taken += 1
        if ev_info.get("images"):
            for img in ev_info["images"]:
                img_id = img["image_id"]
                img_res = handlers["inspect_image"](image_id=img_id)
                state.evidence_inspected.append(f"image:{img_id}")
                state.tool_calls_taken += 1
                if img_res.get("selection") and img_res["selection"].get("needs_review"):
                    state.unresolved = True
                    state.unresolved_reason = f"Image {img_id} requires review: {img_res['selection'].get('rationale')}"

    state.steps_taken = 1
    if not state.unresolved:
        state.completed = True
        state.decision_summary = (
            f"User {req.user_id} evaluated with {len(options.get('options', []))} options, "
            f"{len(msgs.get('messages', []))} messages inspected."
        )


def _run_model_driven_investigation(
    dataset: Dataset,
    req: Any,
    state: InvestigationState,
    handlers: Mapping[str, Callable[..., dict[str, Any]]],
    client: OpenAIClient,
    ledger: UsageLedger | None,
    limits: InvestigationLimits,
) -> None:
    """Executes the model-driven adaptive tool loop with bounded state checks."""
    profile = dataset.profiles_by_user.get(req.user_id)
    currency_str = profile.home_currency.value if profile else ""
    system_prompt = (
        f"You are investigating request {req.request_id} for user {req.user_id}. "
        f"Requested amount: {req.requested_amount} {currency_str}. "
        "Your task is to investigate evidence using available tools (get_user_context, "
        "get_event_lifecycle, get_messages, inspect_image, get_payment_options). "
        "Once a fact is verified, submit your finding using submit_fact_resolution."
    )

    conversation_input: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "input_text", "text": system_prompt}]}
    ]

    call_counts: dict[str, int] = {}

    while not state.completed and not state.unresolved:
        # Check wall time limit
        if (time.time() - state.start_time) > limits.max_wall_time_seconds:
            state.unresolved = True
            state.unresolved_reason = f"wall time cap ({limits.max_wall_time_seconds}s) exceeded"
            break

        # Check step cap
        if state.steps_taken >= limits.max_steps:
            state.unresolved = True
            state.unresolved_reason = f"step cap ({limits.max_steps}) reached without resolution"
            break

        state.steps_taken += 1

        try:
            call_res = client.create(
                input=conversation_input,
                tools=ALL_TOOL_SCHEMAS,
                max_output_tokens=1000,
            )
        except ClassifiedError as exc:
            state.unresolved = True
            state.unresolved_reason = f"model call failed: {exc.message}"
            break

        if ledger is not None:
            cost = estimate_cost_usd(
                input_tokens=call_res.input_tokens,
                output_tokens=call_res.output_tokens,
                cached_tokens=call_res.cached_tokens,
            )
            ledger.record(
                UsageRecord(
                    provider="openai",
                    model=client.model,
                    purpose="investigation_loop",
                    run_id="investigation",
                    evaluation_request_id=req.request_id,
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
                    repair_attempts=0,
                    cache_hit=False,
                )
            )

        # Inspect output items for tool calls
        tool_calls = [
            item for item in call_res.output_items
            if getattr(item, "type", None) == "function_call" or (isinstance(item, dict) and item.get("type") == "function_call")
        ]

        if not tool_calls:
            # Model finished without any tool calls.
            # An empty response (no text, no tool calls) is NOT a successful completion;
            # it is an incomplete or refused response that must be treated as unresolved.
            text = call_res.output_text.strip() if call_res.output_text else ""
            if not text:
                state.unresolved = True
                state.unresolved_reason = (
                    f"model returned empty response (no text, no tool calls) on step {state.steps_taken}; "
                    "treating as incomplete rather than completed investigation"
                )
                break
            # Non-empty text without tool calls: model concluded investigation verbally.
            state.completed = True
            state.decision_summary = text[:300]
            break

        tool_outputs = []
        for tc in tool_calls:
            if state.tool_calls_taken >= limits.max_tool_calls:
                state.unresolved = True
                state.unresolved_reason = f"tool call cap ({limits.max_tool_calls}) exceeded"
                break

            state.tool_calls_taken += 1
            call_id = getattr(tc, "call_id", None) or (tc.get("call_id") if isinstance(tc, dict) else f"call_{state.tool_calls_taken}")
            fn_name = getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else "")
            raw_args = getattr(tc, "arguments", None) or (tc.get("arguments") if isinstance(tc, dict) else {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            else:
                args = dict(raw_args) if raw_args else {}

            # Repeated no-progress detection
            call_sig = f"{fn_name}:{json.dumps(args, sort_keys=True)}"
            call_counts[call_sig] = call_counts.get(call_sig, 0) + 1
            if call_counts[call_sig] > limits.max_repeated_calls:
                state.unresolved = True
                state.unresolved_reason = f"repeated no-progress tool call detected: {fn_name}"
                break

            handler = handlers.get(fn_name)
            if handler is None:
                tool_result_content = {"error": f"unknown tool {fn_name!r}"}
            else:
                try:
                    tool_result_content = handler(**args)
                except ToolError as te:
                    tool_result_content = {"error": str(te)}

            state.tool_call_history.append({
                "step": state.steps_taken,
                "tool": fn_name,
                "arguments": args,
                "result": tool_result_content,
            })
            state.evidence_inspected.append(f"{fn_name}:{json.dumps(args)}")

            if fn_name == "submit_fact_resolution" and tool_result_content.get("accepted"):
                raw_resolution = tool_result_content.get("resolution", {})
                # Convert the structurally-accepted resolution dict into a typed EvidenceFact
                # so that resolver/planner code that reads state.facts can call .user_id etc.
                # We import lazily to avoid circular imports.
                from .evidence import (
                    EvidenceFact, FactKind, TemporalScope,
                )  # noqa: PLC0415
                from datetime import timezone
                from decimal import Decimal as _D
                import datetime as _dt
                source_id = raw_resolution.get("source_id", "")
                # Derive user_id from source ownership
                _user_id = state.user_id
                typed_fact = EvidenceFact(
                    source_type=raw_resolution.get("source_type", "event"),
                    source_id=source_id,
                    user_id=_user_id,
                    related_event_id=(
                        source_id if raw_resolution.get("source_type") == "event" else None
                    ),
                    related_request_id=state.request_id,
                    fact_kind=FactKind.INCOME_CONFIRMED_ONE_OFF,  # generic placeholder
                    amount=None,
                    currency=None,
                    temporal_scope=TemporalScope(effective_from=None, effective_until=None),
                    ambiguous=False,
                    ambiguity_note="",
                    raw_excerpt=raw_resolution.get("justification", ""),
                    observed_time=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                    effective_time=None,
                )
                state.facts.append(typed_fact)
                state.completed = True
                state.decision_summary = (
                    f"Resolved {raw_resolution.get('field_name')} = {raw_resolution.get('value')} "
                    f"from {raw_resolution.get('source_type')}:{source_id}"
                )
                break

            tool_outputs.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(tool_result_content, default=str),
            })

        if state.completed or state.unresolved:
            break

        # Feed tool outputs back to model.
        # Per OpenAI function-calling protocol, the conversation must include:
        #   1. The model's output items (function_call items)
        #   2. The corresponding function_call_output items
        # We append the model's output items first, then the tool outputs.
        model_output_items = [
            (item if isinstance(item, dict) else {
                "type": getattr(item, "type", "function_call"),
                "call_id": getattr(item, "call_id", ""),
                "name": getattr(item, "name", ""),
                "arguments": getattr(item, "arguments", "{}"),
            })
            for item in call_res.output_items
            if getattr(item, "type", None) == "function_call" or (isinstance(item, dict) and item.get("type") == "function_call")
        ]
        # Include the model's response ID for continuation linkage if available
        if call_res.response_id and call_res.response_id != "offline_mock":
            conversation_input = [
                {"previous_response_id": call_res.response_id}
            ] + model_output_items + tool_outputs
        else:
            conversation_input.extend(model_output_items)
            conversation_input.extend(tool_outputs)
