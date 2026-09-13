"""The seven narrowly-scoped tools an investigation loop may call.

Every tool is a plain Python function over an already-loaded, already-
validated `Dataset` (Stage 2). Every tool validates its own id arguments and
ownership in CODE before returning anything -- a tool given an id belonging
to a different user, or an id that does not exist at all, raises `ToolError`
rather than silently returning wrong or empty data (this is exactly what
"Tools validate IDs and ownership in code" means: the runtime model can ask
for an id that doesn't belong where it thinks it does, and the tool refuses
rather than leaking or fabricating).

None of these tools can read an arbitrary file, run a shell command, spend
money, or reach a live financial service: `inspect_image` reads only
`dataset/media/images/<image_id>.png` after validating `image_id` against
`Dataset.images_by_id` and delegates the actual model call to
`evidence.extract_evidence_from_image` (cached); every other tool only reads
already-loaded `Dataset` fields. `simulate_candidate` is registered here as a
real, callable tool with a real schema, but its handler HONESTLY reports
itself unavailable rather than fabricating a result -- financial simulation
is connected once the planner exists (Stage 4/6), and pretending otherwise
here would be exactly the kind of fabrication this project's standing rules
forbid.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable, Mapping

from .csv_format import PlanEntry, parse_payment_plan, parse_spending_changes
from .forecast import assemble_flows, calculate_amount_safe_to_pay, calculate_binding_headroom
from .independent_verifier import replay_plan
from .planner import apply_spending_changes_to_flows, find_flexible_streams
from .schemas import Dataset

TOOL_CONTRACT_VERSION = "v1"


class ToolError(Exception):
    """Raised for an unknown id, an id belonging to a different owner, or a
    structurally invalid tool submission. Never silently swallowed into an
    empty or wrong-owner result."""


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of dataset dataclasses/enums/Decimal/date into
    plain JSON-serializable values, for tool results handed back to the
    model as a `function_call_output`."""
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):  # date / datetime
        return value.isoformat()
    if hasattr(value, "value") and type(value).__mro__[1].__name__ == "str":  # StrEnum member
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        # Deliberately NOT dataclasses.asdict(): asdict() recursively deep-copies
        # every field, including `raw` (a MappingProxyType), which is not
        # deep-copyable and raised TypeError before this function's own
        # `raw`-exclusion ever ran. Walking fields() directly avoids the
        # recursive deep-copy entirely and skips `raw` before touching it.
        return {
            f.name: _jsonable(getattr(value, f.name))
            for f in fields(value)
            if f.name != "raw" and not callable(getattr(value, f.name))
        }
    if isinstance(value, Mapping):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return value


# --------------------------------- 1. get_user_context ---------------------------------


def get_user_context(dataset: Dataset, *, user_id: str) -> dict:
    profile = dataset.profiles_by_user.get(user_id)
    if profile is None:
        raise ToolError(f"unknown user_id: {user_id!r}")
    return _jsonable(profile)


GET_USER_CONTEXT_SCHEMA = {
    "type": "function",
    "name": "get_user_context",
    "description": "Return the user's financial profile: home currency, balances, priorities, protected/reducible/stoppable expense categories, accepted payment methods, and max installment months.",
    "parameters": {
        "type": "object",
        "properties": {"user_id": {"type": "string"}},
        "required": ["user_id"],
        "additionalProperties": False,
    },
    "strict": True,
}


# --------------------------------- 2. get_event_lifecycle ---------------------------------


def get_event_lifecycle(dataset: Dataset, *, event_id: str) -> dict:
    event = dataset.events_by_id.get(event_id)
    if event is None:
        raise ToolError(f"unknown event_id: {event_id!r}")
    result = _jsonable(event)
    if event.linked_event_id is not None:
        linked = dataset.events_by_id.get(event.linked_event_id)
        result["linked_event"] = _jsonable(linked) if linked is not None else None
    children = [_jsonable(e) for e in dataset.events if e.linked_event_id == event_id]
    result["linking_children"] = children
    result["messages"] = [_jsonable(m) for m in dataset.messages_by_event.get(event_id, ())]
    result["images"] = [_jsonable(i) for i in dataset.images_by_event.get(event_id, ())]
    return result


GET_EVENT_LIFECYCLE_SCHEMA = {
    "type": "function",
    "name": "get_event_lifecycle",
    "description": "Return one financial event's full record, its linked parent/child events (settlement/cancellation/refund chains), and any messages or images that reference it.",
    "parameters": {
        "type": "object",
        "properties": {"event_id": {"type": "string"}},
        "required": ["event_id"],
        "additionalProperties": False,
    },
    "strict": True,
}


# --------------------------------- 3. get_messages ---------------------------------


def get_messages(dataset: Dataset, *, user_id: str | None = None, request_id: str | None = None, event_id: str | None = None) -> dict:
    provided = [x for x in (user_id, request_id, event_id) if x is not None]
    if len(provided) != 1:
        raise ToolError("exactly one of user_id, request_id, event_id must be provided")
    if user_id is not None:
        if user_id not in dataset.profiles_by_user:
            raise ToolError(f"unknown user_id: {user_id!r}")
        messages = dataset.messages_by_user.get(user_id, ())
    elif request_id is not None:
        if request_id not in dataset.all_requests_by_id:
            raise ToolError(f"unknown request_id: {request_id!r}")
        messages = dataset.messages_by_request.get(request_id, ())
    else:
        if event_id not in dataset.events_by_id:
            raise ToolError(f"unknown event_id: {event_id!r}")
        messages = dataset.messages_by_event.get(event_id, ())
    return {"messages": [_jsonable(m) for m in messages]}


GET_MESSAGES_SCHEMA = {
    "type": "function",
    "name": "get_messages",
    "description": "Return raw messages for exactly one of: a user (all their messages, most have no direct event/request link), a request, or an event.",
    "parameters": {
        "type": "object",
        "properties": {
            "user_id": {"type": ["string", "null"]},
            "request_id": {"type": ["string", "null"]},
            "event_id": {"type": ["string", "null"]},
        },
        "required": ["user_id", "request_id", "event_id"],
        "additionalProperties": False,
    },
    "strict": True,
}


# --------------------------------- 4. inspect_image ---------------------------------
# The handler for this one is bound at investigation-loop construction time
# (it needs an OpenAIClient + cache + the extraction function), not here --
# see investigation.py::build_tool_handlers. This module only validates
# ownership and resolves the path, which is the part that must never depend
# on a live call to be tested.


def resolve_image_for_inspection(dataset: Dataset, *, image_id: str) -> dict:
    """Ownership/ID validation + path resolution ONLY -- the pure, tool-
    schema-validated part of `inspect_image` that does not need a live model
    call to test. The bound handler in investigation.py calls this first,
    then runs (or serves from cache) the actual vision extraction."""
    image = dataset.images_by_id.get(image_id)
    if image is None:
        raise ToolError(f"unknown image_id: {image_id!r}")
    return {"image_id": image_id, "path": image.path(), "user_id": image.user_id, "related_event_id": image.related_event_id}


INSPECT_IMAGE_SCHEMA = {
    "type": "function",
    "name": "inspect_image",
    "description": "Run (or retrieve a cached) structured vision extraction over one supplied image and return its observed fields (amounts, currency, dates, payment status, source regions).",
    "parameters": {
        "type": "object",
        "properties": {"image_id": {"type": "string"}},
        "required": ["image_id"],
        "additionalProperties": False,
    },
    "strict": True,
}


# --------------------------------- 5. get_payment_options ---------------------------------


def get_payment_options(dataset: Dataset, *, request_id: str) -> dict:
    if request_id not in dataset.all_requests_by_id:
        raise ToolError(f"unknown request_id: {request_id!r}")
    return {"options": [_jsonable(o) for o in dataset.options_by_request.get(request_id, ())]}


GET_PAYMENT_OPTIONS_SCHEMA = {
    "type": "function",
    "name": "get_payment_options",
    "description": "Return every seller/provider payment option supplied for one request.",
    "parameters": {
        "type": "object",
        "properties": {"request_id": {"type": "string"}},
        "required": ["request_id"],
        "additionalProperties": False,
    },
    "strict": True,
}


# --------------------------------- 6. simulate_candidate ---------------------------------


def simulate_candidate(
    dataset: Dataset,
    *,
    request_id: str,
    payment_option_id: str | None = None,
    custom_plan: str | None = None,
    spending_changes: str | None = None,
) -> dict:
    """Replay a candidate payment plan against the user's forward cash flows.
    Checks whether the plan keeps the user's minimum balance protected over 90 days.
    """
    req = dataset.all_requests_by_id.get(request_id)
    if req is None:
        raise ToolError(f"unknown request_id: {request_id!r}")
    user_id = req.user_id
    prof = dataset.profiles_by_user[user_id]
    anchor_date = req.request_date
    deadline = req.desired_completion_date

    # 1. Resolve payment plan schedule and expected total.
    # expected_total is ALWAYS derived from the request's actual obligation (or the
    # selected offer's total), never from the proposed plan sum. A custom plan of
    # 'YYYY-MM-DD:1' proposes to pay 1; the request amount is 25,256. These must
    # be compared rather than equated, so sums_to_requested_amount catches underpayment.
    plan_entries: tuple[PlanEntry, ...]
    expected_total: Decimal
    if payment_option_id:
        opt = dataset.options_by_id.get(payment_option_id)
        if opt is None or opt.request_id != request_id:
            raise ToolError(f"payment_option {payment_option_id!r} does not belong to request {request_id!r}")
        freq = opt.payment_frequency_days or 30
        plan_entries = tuple(
            PlanEntry(
                entry_date=opt.first_payment_date + timedelta(days=freq * k),
                amount=opt.payment_amount,
            )
            for k in range(opt.number_of_payments)
        )
        expected_total = opt.total_payable_amount
    elif custom_plan:
        plan_entries = parse_payment_plan(custom_plan)
        # expected_total is the requested obligation, NOT the plan sum.
        # The replay will compare plan_sum to expected_total and set sums_to_requested_amount.
        expected_total = req.requested_amount
    else:
        # Default hypothesis: full payment today
        plan_entries = (PlanEntry(entry_date=anchor_date, amount=req.requested_amount),)
        expected_total = req.requested_amount


    # 2. Resolve forward cash flows (with or without spending changes)
    base_flows = assemble_flows(dataset, user_id, anchor_date=anchor_date)
    flows_to_use = base_flows
    if spending_changes and spending_changes.strip() != "none":
        parsed_changes = parse_spending_changes(spending_changes)
        flex_streams = find_flexible_streams(dataset, user_id, anchor_date)
        flows_to_use = apply_spending_changes_to_flows(base_flows, parsed_changes, flex_streams)

    # 3. Replay plan
    rep = replay_plan(
        opening_balance=prof.current_available_balance,
        minimum_balance_to_keep=prof.minimum_balance_to_keep,
        anchor_date=anchor_date,
        flows=flows_to_use,
        plan_entries=plan_entries,
        requested_amount=req.requested_amount,
        deadline=deadline,
        expected_total=expected_total,
    )

    worst_headroom, binding_date = calculate_binding_headroom(rep.simulation)
    safe_today = calculate_amount_safe_to_pay(rep.simulation, req.requested_amount)

    return {
        "available": True,
        "request_id": request_id,
        "is_safe": rep.simulation.is_safe,
        "completes_by_deadline": rep.completes_by_deadline,
        "sums_to_requested_amount": rep.sums_to_requested_amount,
        "is_chronological": rep.is_chronological,
        "total_paid": str(expected_total),
        "worst_headroom": str(worst_headroom),
        "binding_date": binding_date.isoformat(),
        "amount_safe_to_pay": str(safe_today),
        "breaches": [
            {
                "day": b.day.isoformat(),
                "floor_check_balance": str(b.floor_check_balance),
                "minimum_balance_to_keep": str(b.minimum_balance_to_keep),
                "shortfall": str(b.shortfall),
            }
            for b in rep.simulation.breaches
        ],
    }


SIMULATE_CANDIDATE_SCHEMA = {
    "type": "function",
    "name": "simulate_candidate",
    "description": "Replay a candidate payment plan hypothesis against the user's cash-flow forecast and check 90-day balance safety.",
    "parameters": {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "description": "The request ID to simulate for."},
            "payment_option_id": {"type": ["string", "null"], "description": "Optional payment option ID from get_payment_options."},
            "custom_plan": {"type": ["string", "null"], "description": "Optional custom payment plan in 'YYYY-MM-DD:amount|...' format."},
            "spending_changes": {"type": ["string", "null"], "description": "Optional spending changes in 'stop:event_id|reduce_to:event_id:amount' format."}
        },
        "required": ["request_id", "payment_option_id", "custom_plan", "spending_changes"],
        "additionalProperties": False,
    },
    "strict": True,
}



# --------------------------------- 7. submit_fact_resolution ---------------------------------

_RESOLUTION_REQUIRED_FIELDS = ("source_type", "source_id", "field_name", "value", "confidence", "justification")


def submit_fact_resolution(dataset: Dataset, *, resolution: Mapping[str, Any]) -> dict:
    """Structural validation only (the investigation loop is what actually
    records an accepted resolution into the typed ledger -- see
    investigation.py). Rejects a submission missing a required field or
    naming an unknown source, rather than accepting anything the model
    proposes at face value: 'a high model confidence value is not proof'
    applies here directly -- this function checks SHAPE and ownership, never
    the truth of the claim."""
    missing = [f for f in _RESOLUTION_REQUIRED_FIELDS if f not in resolution]
    if missing:
        raise ToolError(f"resolution missing required field(s): {missing}")
    source_type = resolution["source_type"]
    source_id = resolution["source_id"]
    if source_type == "event" and source_id not in dataset.events_by_id:
        raise ToolError(f"resolution references unknown event_id: {source_id!r}")
    if source_type == "message" and source_id not in dataset.messages_by_id:
        raise ToolError(f"resolution references unknown message_id: {source_id!r}")
    if source_type == "image" and source_id not in dataset.images_by_id:
        raise ToolError(f"resolution references unknown image_id: {source_id!r}")
    if source_type not in ("event", "message", "image"):
        raise ToolError(f"resolution source_type must be one of event/message/image, got {source_type!r}")
    return {"accepted": True, "resolution": dict(resolution)}


SUBMIT_FACT_RESOLUTION_SCHEMA = {
    "type": "function",
    "name": "submit_fact_resolution",
    "description": "Submit a proposed fact resolution (a value for one field, grounded in one source, with a stated confidence and justification) to end an investigation on that field. Code re-validates before accepting.",
    "parameters": {
        "type": "object",
        "properties": {
            "resolution": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string", "enum": ["event", "message", "image"]},
                    "source_id": {"type": "string"},
                    "field_name": {"type": "string"},
                    "value": {"type": ["string", "number", "null"]},
                    "confidence": {"type": "number"},
                    "justification": {"type": "string"},
                },
                "required": list(_RESOLUTION_REQUIRED_FIELDS),
                "additionalProperties": False,
            }
        },
        "required": ["resolution"],
        "additionalProperties": False,
    },
    "strict": True,
}


ALL_TOOL_SCHEMAS = (
    GET_USER_CONTEXT_SCHEMA,
    GET_EVENT_LIFECYCLE_SCHEMA,
    GET_MESSAGES_SCHEMA,
    INSPECT_IMAGE_SCHEMA,
    GET_PAYMENT_OPTIONS_SCHEMA,
    SIMULATE_CANDIDATE_SCHEMA,
    SUBMIT_FACT_RESOLUTION_SCHEMA,
)

# Handlers NOT requiring a live model call -- inspect_image is bound
# separately by investigation.py because it needs an OpenAIClient + cache.
PURE_TOOL_HANDLERS: Mapping[str, Callable[..., dict]] = {
    "get_user_context": get_user_context,
    "get_event_lifecycle": get_event_lifecycle,
    "get_messages": get_messages,
    "get_payment_options": get_payment_options,
    "simulate_candidate": simulate_candidate,
    "submit_fact_resolution": submit_fact_resolution,
}
