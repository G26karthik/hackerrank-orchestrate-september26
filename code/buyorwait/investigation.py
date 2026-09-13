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
from .schemas import Dataset, Direction, ExpenseCategory
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
    user_id: str | None = None,
) -> dict[str, Callable[..., dict[str, Any]]]:
    """Binds the seven tool handlers against `dataset`. `inspect_image` is
    bound with `client` + `cache` so that image requests validate ownership
    and path locally, then run or serve from cache structured vision
    extractions."""
    handlers: dict[str, Callable[..., dict[str, Any]]] = {}
    for name, fn in PURE_TOOL_HANDLERS.items():
        if name == "submit_fact_resolution" and user_id is not None:
            handlers[name] = functools.partial(fn, dataset, user_id=user_id)
        else:
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
                "cache_hit": False,
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
        except Exception as _client_err:
            # Extraction failure (transport, runtime error, or exhausted client).
            # Do NOT resurrect stale observations from old bytes.
            return {
                "image_id": image_id,
                "path": info["path"],
                "user_id": info["user_id"],
                "related_event_id": info["related_event_id"],
                "cache_hit": False,
                "note": f"extraction_failed: {type(_client_err).__name__}: {_client_err}",
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
        else build_tool_handlers(dataset, client=client, cache=cache, media_root=media_root, user_id=req.user_id)
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
        except (ClassifiedError, StopIteration, Exception) as exc:
            state.unresolved = True
            state.unresolved_reason = f"model call failed: {type(exc).__name__}: {exc}"
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

            if fn_name == "submit_fact_resolution":
                raw_res = args.get("resolution", {}) if isinstance(args, dict) else {}
                src_type = raw_res.get("source_type")
                src_id = raw_res.get("source_id")
                src_owner = None
                if src_type == "event" and src_id in dataset.events_by_id:
                    src_owner = dataset.events_by_id[src_id].user_id
                elif src_type == "message" and src_id in dataset.messages_by_id:
                    src_owner = dataset.messages_by_id[src_id].user_id
                elif src_type == "image" and src_id in dataset.images_by_id:
                    src_owner = dataset.images_by_id[src_id].user_id

                if src_owner is not None and src_owner != req.user_id:
                    tool_result_content = {
                        "accepted": False,
                        "error": f"source {src_id} belongs to user {src_owner}, not target user {req.user_id}",
                    }

            if fn_name == "submit_fact_resolution" and tool_result_content.get("accepted"):
                raw_resolution = tool_result_content.get("resolution", {})
                from .evidence import EvidenceFact, FactKind, TemporalScope
                from decimal import Decimal as _D

                src_type = raw_resolution.get("source_type", "event")
                src_id = raw_resolution.get("source_id", "")
                field_name = raw_resolution.get("field_name", "")
                val = raw_resolution.get("value")
                justification = raw_resolution.get("justification", "")

                admitted_amt = None
                if val is not None:
                    try:
                        admitted_amt = _D(str(val))
                    except Exception:
                        admitted_amt = None

                admitted_curr = None
                admitted_obs_time = ""
                admitted_eff_time = None
                admitted_eff_from = None
                rel_event_id = None
                fact_kind = FactKind.RECEIPT_CONFIRMS_AMOUNT

                if src_type == "event":
                    evt = dataset.events_by_id.get(src_id)
                    if evt:
                        rel_event_id = evt.event_id
                        admitted_curr = evt.currency
                        evt_dt = evt.settlement_date or evt.event_date
                        admitted_obs_time = f"{evt_dt.isoformat()}T00:00:00+00:00"
                        admitted_eff_time = evt_dt.isoformat()
                        admitted_eff_from = evt_dt
                        if admitted_amt is None and evt.amount is not None:
                            admitted_amt = evt.amount
                        if evt.category == ExpenseCategory.SALARY:
                            fact_kind = FactKind.INCOME_AMOUNT_CHANGE
                        elif evt.direction == Direction.CREDIT:
                            fact_kind = FactKind.INCOME_CONFIRMED_ONE_OFF
                        else:
                            fact_kind = FactKind.RECEIPT_CONFIRMS_AMOUNT
                elif src_type == "message":
                    msg = dataset.messages_by_id.get(src_id)
                    if msg:
                        rel_event_id = msg.related_event_id
                        admitted_obs_time = msg.sent_at.isoformat()
                        admitted_eff_from = msg.sent_at.date()
                        admitted_eff_time = msg.sent_at.date().isoformat()
                        prof = dataset.profiles_by_user.get(msg.user_id)
                        admitted_curr = prof.home_currency if prof else None
                        fact_kind = FactKind.RECEIPT_CONFIRMS_AMOUNT
                elif src_type == "image":
                    img = dataset.images_by_id.get(src_id)
                    if img:
                        rel_event_id = img.related_event_id
                        evt = dataset.events_by_id.get(img.related_event_id) if img.related_event_id else None
                        if evt:
                            admitted_curr = evt.currency
                            evt_dt = evt.settlement_date or evt.event_date
                            admitted_obs_time = f"{evt_dt.isoformat()}T00:00:00+00:00"
                            admitted_eff_time = evt_dt.isoformat()
                            admitted_eff_from = evt_dt
                        else:
                            admitted_obs_time = f"{req.request_date.isoformat()}T00:00:00+00:00"
                            admitted_eff_from = req.request_date
                            admitted_eff_time = req.request_date.isoformat()
                        fact_kind = FactKind.IMAGE_AMOUNT

                typed_fact = EvidenceFact(
                    source_type=src_type,
                    source_id=src_id,
                    user_id=req.user_id,
                    related_event_id=rel_event_id,
                    related_request_id=state.request_id,
                    fact_kind=fact_kind,
                    amount=admitted_amt,
                    currency=admitted_curr,
                    temporal_scope=TemporalScope(effective_from=admitted_eff_from, effective_until=None),
                    ambiguous=False,
                    ambiguity_note="",
                    raw_excerpt=justification,
                    observed_time=admitted_obs_time,
                    effective_time=admitted_eff_time,
                )
                state.facts.append(typed_fact)
                state.completed = True
                state.decision_summary = (
                    f"Resolved {field_name} = {val} from {src_type}:{src_id}"
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
        # Per OpenAI Responses protocol with manual history:
        # 1. Preserve initial user request (in conversation_input)
        # 2. Append all model output items (reasoning, function_call, message)
        # 3. Append corresponding function_call_output items
        for item in call_res.output_items:
            if isinstance(item, dict):
                conversation_input.append(dict(item))
            else:
                item_dict: dict[str, Any] = {}
                for k in ("type", "id", "summary", "call_id", "name", "arguments", "role", "content", "status"):
                    v = getattr(item, k, None)
                    if v is not None:
                        item_dict[k] = v
                if not item_dict:
                    item_dict = {"type": getattr(item, "type", "function_call")}
                conversation_input.append(item_dict)

        conversation_input.extend(tool_outputs)
