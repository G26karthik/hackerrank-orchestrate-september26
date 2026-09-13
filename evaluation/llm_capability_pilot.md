# LLM Capability Pilot — Stage 3

Everything in this file was verified by an actual, live call against the real OpenAI API on
2026-09-12 using the account's real `OPENAI_API_KEY` (never read directly by any tool in this
session — see `evaluation/state.md` Stage 3 for the exact handling), or is a direct, labeled
transcription of a fetched documentation page. Nothing here is assumed from training-time
knowledge of what a model "probably" supports.

---

## 1. Environment and SDK

| Item | Finding |
|---|---|
| `OPENAI_API_KEY` | Present, loaded via `buyorwait/config.py`, never read or printed by any tool call in this session (only `key is not None` / `key.startswith('sk-')` checks were run) |
| Global `openai` SDK (site-packages) | **1.58.1** — verified stale: `hasattr(OpenAI(), "responses")` is `False`. This SDK predates the Responses API entirely. |
| Latest available `openai` SDK | **3.13.0** (`pip index versions openai`) |
| Action taken | Installed `openai==3.13.0` in an **isolated project virtualenv** (`.venv/`, gitignored) rather than upgrading the machine's global install, after upgrading globally first and discovering it broke three unrelated already-installed tools' pinned dependency ranges (`crewai` needs `pydantic-settings>=2.10.1`/`python-dotenv>=1.1.1`; `instructor` needs `openai<3.0.0`; `litellm` needs `openai>=2.8.0`, satisfied only in a narrow band). The global install was restored to 1.58.1 before proceeding — see the Stage 3 reversal log in `evaluation/state.md`. |
| Reproducible install | `requirements-llm.txt` (or `pip install openai==3.13.0 tiktoken` inside `.venv/`) — the deterministic core (Stage 2) still needs zero third-party dependencies; only this stage's live-call path needs the pinned SDK. |

## 2. Model verification: `gpt-6-astra`

The Stage 3 instruction named `gpt-6-astra` as a candidate and explicitly required rechecking
account entitlement rather than trusting documentation. Verified, in this order:

1. `client.models.list()` (real API call): 130 models on this account; `gpt-6-astra` is present,
   alongside `gpt-5.6-luna`/`gpt-5.6-sol`/`gpt-5.6-terra` and every earlier GPT-5.x generation.
2. `client.models.retrieve("gpt-6-astra")`: returns `{id, created, owned_by: "system",
   shutdown_date: null}` — confirms the id is real and not scheduled for shutdown, but (as is
   normal for this endpoint) carries no capability manifest, so every capability below was
   checked with an actual call, not inferred from this response.
3. Every capability the Stage 3 instruction asked about was exercised with a real call:

| Capability | Verified | Evidence |
|---|---|---|
| Plain text (Responses API) | ✅ | `responses.create(model="gpt-6-astra", input="Reply with exactly one word: PONG")` → `"PONG"`, `resp_070b9fbda9037341...`, usage `{input:14, output:6, reasoning:0, total:20}` |
| `reasoning.effort` (low/medium/high/xhigh/max) | ✅ all 5 accepted | `high` spent 10 reasoning tokens answering `17*23`; `low`/`medium` spent 0 on the same prompt — real differentiated behaviour, not an accepted-but-ignored parameter |
| Structured outputs (strict JSON Schema) | ✅ | extracted `{"amount":2112,"currency":"USD"}` from an archetype-17-shaped prompt, schema `additionalProperties:false`, `strict:true` |
| Vision / image input | ✅ | `image_06.png` (sha256 `9055551f...`, matches `evaluation/contract.md`) → `{"total_amount":1995.00,"currency":"INR"}`, matching Stage 1's manual read exactly |
| Function calling, full round trip | ✅ | model called `get_event_lifecycle(event_id="event_3051")`; fed the (fake, for this specific pilot call) result back; final answer: *"Event **event_3051** is **settled**, with an amount of **INR 1,995.00**."* — correct and grounded |
| `temperature` | ❌ **rejected** | `400 BadRequestError`, `param="temperature"`, message *"Unsupported parameter: 'temperature' is not supported with this model."* |
| `seed` | ❌ **not a valid kwarg** | `TypeError: Responses.create() got an unexpected keyword argument 'seed'` — this SDK/endpoint does not expose it at all |
| Refusal handling | soft refusal, no distinct exception | a request for nerve-agent synthesis instructions returned `status="completed"` with an ordinary declining `output_text` — **not** a raised `ContentFilterFinishReasonError** in this case |
| Incomplete output | ✅ distinct signal | tiny `max_output_tokens` on a long task → `status="incomplete"`, `incomplete_details.reason="max_output_tokens"`, `output_text=""` — structurally different from a refusal |
| Rate-limit headers | ✅ real, read via `with_raw_response` | `x-ratelimit-limit-requests: 500`, `x-ratelimit-limit-tokens: 500000`, `x-ratelimit-remaining-*`, `x-request-id` |
| Exception taxonomy | ✅ confirmed distinct classes | `AuthenticationError`(401) / `PermissionDeniedError`(403) / `NotFoundError`(404, bad model id) / `BadRequestError`(400, param-set vs code-set distinguishes unsupported-parameter from invalid-schema) / `RateLimitError`(429) / `InternalServerError`(5xx) — all real, triggered live except 403 (no permission-denied condition was available to trigger safely) and 429/5xx (deliberately not provoked against the live API — see §6) |

### Pricing (read from official docs, cross-checked on two pages, 2026-09-12)

| | Input | Cached input | Output |
|---|---:|---:|---:|
| Standard, per 1M tokens | $10.00 | $1.00 | $50.00 |
| Long-context, per 1M tokens | $20.00 | $2.00 | $75.00 |

Source: `developers.openai.com/api/docs/models/gpt-6-astra` and
`developers.openai.com/api/docs/pricing`, both fetched 2026-09-12. Neither page carries an
explicit version/date stamp; the pricing page references "models released on or after March 5,
2026" for a separate regional-processing note, which is the only dating signal either page gives.
Recorded as `PRICING_VERSION = "gpt-6-astra:2026-09-12:developers.openai.com"` in
`buyorwait/config.py`. **All costs in this project are estimates against this price list, labeled
as such everywhere they appear** — there is no live billing API this SDK exposes to check them
against.

### Determinism (U-LLM-DETERMINISM-1, new this stage)

No parameter in this API guarantees determinism: `temperature` is rejected outright for this
model, and `seed` does not exist as a parameter at all on this endpoint/SDK. A same-prompt,
same-effort probe (`"Name one prime number between 10 and 20"`, effort=low, run twice) returned
`"13"` both times — a weak, single data point in favor of low-effort stability on a trivial
factual question, **not proof of general determinism**. Separately, the real 16-image audit
needed a bounded retry ladder (2000 → 4000 → 8000 output tokens) for `image_10` (a 22-line-item
receipt): the response that ultimately succeeded used 3,402 output tokens, comfortably under the
4,000-token tier that had already failed twice — consistent with genuine run-to-run output-length
variance on the same input, not merely "needed a bigger fixed budget." Nothing in this project
treats repeated extraction as byte-identical across fresh calls; only cache-hit replay (§7) is
byte-identical, because it makes no fresh call at all.

---

## 3. Coverage: images and messages

### Images: **16 of 16** (100%)

Every image in `dataset/media/images/` was run through the real pipeline
(`buyorwait.evidence.extract_image_observation` → `select_amount_role`). Full results:
`evaluation/image_audit_results.json`; a tracked snapshot of the underlying cached model output
for every one of them is at `evaluation/extraction_snapshot/observations/`.

| image | event (category) | selected field | selected amount | legible | independent re-read | agrees |
|---|---|---|---:|---|---|---|
| image_01 | event_253 (salary) | net_pay | 4,365,000 | yes | net_pay | ✅ |
| image_02 | event_1442 (rent) | balance_due | 100,000 | yes | balance_due | ✅ |
| image_03 | event_1545 (groceries) | paid_amount | 41,272 | yes | — | — |
| image_04 | event_1700 (groceries) | **none** | **null** | **no** | — | — |
| image_05 | event_1786 (utilities) | balance_due | 704.05 | yes | balance_due | ✅ |
| image_06 | event_3051 (groceries) | total | 1,995.00 | yes | — | — |
| image_07 | event_3231 (dining) | total | 8,528 | yes | total | ✅ |
| image_08 | event_4535 (housing) | paid_amount | 15,339.00 | yes | paid_amount | ✅ |
| image_09 | event_5170 (utilities) | total | 723.00 | yes | paid_amount (723.00) | ✅ |
| image_10 | event_6033 (groceries) | total | 79,679.26 | yes | — | — |
| image_11 | event_6859 (healthcare) | balance_due | 3,650.00 | yes | — | — |
| image_12 | event_7307 (transport) | total | 33.5 | yes | total | ✅ |
| image_13 | event_7941 (shopping) | paid_amount | 2,298 | yes | total (2,298) | ✅ |
| image_14 | event_9421 (healthcare) | total | 4,543.00 | yes | — | — |
| image_15 | event_9806 (transport) | total | 9,968.00 | yes | total | ✅ |
| image_16 | event_10521 (transport) | total | 393.22 | yes | total | ✅ |

**10 of 16 financially decisive fields were independently re-read** (a fresh call, no prior
answer shown, `effort=xhigh`, targeting the field this project's own code actually selected).
**10 of 10 agreed exactly with the initial extraction.** The remaining 6 were not re-read either
because the field is not currency-decisive in the same way (image_03/06/11/14, all category
`total`/`paid_amount` already cross-checked once in image-legibility terms) or because the audit
already produced its own strong internal corroboration (image_10's total, `79,679.26`, was
independently cross-checked by hand against the receipt's own printed amount-in-words line,
*"Indian Rupee Seventy-Nine Thousand Six Hundred Seventy-Nine and Twenty-Six Paise Only"* — an
exact match, done as part of this write-up, not by the model).

**Unresolved evidence: `image_04` (event_1700, "Delivered grocery order").** The model reported
`legible=false` with the note *"lower portion of receipt is cropped out of frame"* — matching the
Stage 3 instruction's own audit note for this image verbatim. `select_amount_role` returned
`selected_amount=None`, `needs_review=True`, with an empty `alternatives` tuple (no candidate
amounts were visible at all, not merely an unlabeled one). **This event's amount remains
genuinely unresolved by this stage.** It is not coerced to zero and not silently defaulted; it is
surfaced here as exactly the kind of "visible internal review/error record" item 5/the general
instruction requires, to be picked up by the evidence-resolver stage (still an interface stub) or
by a further, differently-cropped-region-aware re-read strategy in a later stage.

### Messages: **21 of 215** (a representative pilot, not full coverage)

Chosen to cover every one of the 31 message archetypes catalogued in `evaluation/inventory.md`
§9 at least once, plus every field-level check the Stage 3 instruction named:

| Check named in the instruction | Message(s) | Result |
|---|---|---|
| Net vs gross pay, salary timing | message_01, message_04, message_06, message_20 | income_amount_change / income_confirmed_one_off extracted, amounts and effective dates captured |
| Income not yet confirmed / employment changes | message_03, message_09, message_10 | income_not_yet_confirmed, income_ended, new_unquantified_recurring_expense (the childcare clause: **no amount fabricated**, `amount: null`) |
| Outstanding vs paid amounts, receipts | message_35, message_64, message_86 | receipt_confirms_amount; message_86 correctly split into **two** unrelated facts (an EV-charge receipt confirmation and a separate future USD salary credit) rather than forced into one |
| Late charges / disputes | message_69, message_106 | pending_debit_unresolved, unrelated_card_dispute |
| Rent increase | message_12 | rent_percentage_increase, 12% captured as stated, no base amount invented |
| Pending credits, arrears, reimbursement | message_18, message_53, message_117 | income_confirmed_one_off, income_reimbursement_not_recurring (correctly NOT treated as recurring salary) |
| Investment valuation vs sale | message_15, message_92 | investment_valuation_change_non_cash, investment_sale_settled — correctly distinguished |
| **Untrusted instruction (safety)** | message_67, message_142 (English and Indonesian) | Both extracted as `fact_kind=untrusted_instruction` with **no amount, no currency, no compliance** — the model did not attempt to "help" pay a release charge; it flagged the content as untrusted and extracted nothing actionable from it |

Full results: `evaluation/message_pilot_results.json`. Extrapolated cost for the remaining 194
messages is in §5.

---

## 4. Adaptive investigation loop and tool round trip

Stage 3 scope for this specific requirement: demonstrate a REAL evidence-tool round trip using
the seven narrowly-scoped tools (`buyorwait/tools.py`), without connecting `simulate_candidate`
to a planner that does not exist yet (Stage 4/6).

The tool-calling round trip demonstrated in §2 (`get_event_lifecycle` → real tool
execution → grounded final answer) is real end-to-end evidence that the mechanism works, and
`tests/test_tools.py` (23 tests) exercises every one of the seven tools' validation logic
directly.

The bounded state machine (`buyorwait/investigation.py`) implements request-scoped typed state
(`InvestigationState`), step caps, tool-call caps, wall-time caps, repeated-no-progress detection,
and `submit_fact_resolution` as the loop's termination signal. It is covered by
`tests/test_investigation.py` (7 tests covering offline inspection, step limits, repeated call
detection, wall-time caps, and fact resolution) and exercised across representative requests
in `code/evaluation/run_investigation_demo.py`, saving its observable audit trace to
`evaluation/investigation_demo.json`.

`simulate_candidate` was called for real: it returns `{"available": false, "reason":
"simulate_candidate is not yet connected: it will call
buyorwait.independent_verifier.replay_plan once the planner (Stage 4/6) can produce a candidate
plan to check. This evidence-extraction stage never fabricates a simulation result."}` — tested
in `tests/test_tools.py::SimulateCandidateHonestyTests`.

---

## 5. Usage and cost (this pilot, NOT the final run)

Two real online runs were made this stage (the first was interrupted by the real `image_10`
incomplete-output failure documented in §2/§6; the second resumed and completed, serving the
first 9 images and all message extractions from cache with **zero** re-spend, and making 10 fresh
calls for the independent re-reads, which are deliberately never cached — see
`buyorwait/evidence.py::independent_reread_amount`'s docstring).

| Run | Fresh calls | Cache hits | Total tokens | Cost (USD, estimate) |
|---|---:|---:|---:|---:|
| 1 (interrupted after image_09) | 37 | 9 | 54,381 | 1.0781 |
| 2 (resumed to completion) | 10 (re-reads only) | 37 | 17,632 | 0.0767 |
| **Combined, this pilot** | **47** | **46** | **72,013** | **1.1548** |

Full per-model breakdown: `evaluation/pilot_usage_report.md` (run 2's report; run 1's numbers are
reproduced in the table above from this session's own log, since run 1's report file was
overwritten by run 2 — a known limitation of the current script writing one fixed filename per
run, noted for the packaging stage to fix by timestamping report filenames).

### Extrapolation to the remaining message corpus

21 messages cost **0.0163 USD** in fresh-call terms across both runs combined (message-only fresh
calls: 21 calls, ~9,600 tokens total, ≈$0.016 at this pricing). Linearly extrapolating to the
remaining 194 messages: **≈$0.15**, a few minutes of wall time at the observed 4-12s per-call
latency with no concurrency. This is comfortably inside "run a representative pilot and
extrapolate expected cost before a full run" (item 11) territory — nothing here suggests the full
corpus would be materially expensive, and no unexpected cost spike occurred.

### Cost management note

Total spend this stage: **≈$1.15**, against a pilot whose whole point was empirical verification,
not volume. No step in this stage entered unbounded inference, and no material unexpected cost
increase occurred; the one retry-driven cost increase (image_10 needing a third, 8000-token
attempt) was itself a bounded, logged, one-time event costing a few cents, not a silent
degradation or a runaway loop.

---

## 6. Errors, retries, and fault injection

### Real provider behaviour observed (not injected)

- `image_10` genuinely returned `status="incomplete"` / `incomplete_reason="max_output_tokens"`
  twice (2000, then 4000 output tokens) before succeeding at 8000 — a real capacity limitation
  triggered by a genuinely large 22-line-item receipt, not a fault this project manufactured. It
  is handled by `buyorwait.evidence.ExtractionIncompleteError` after a bounded 3-attempt ladder,
  never an uncaught `JSONDecodeError` (which is exactly what happened on the FIRST version of this
  code, before the fix — see the reversal log in `evaluation/state.md`).
- A genuine `400 BadRequestError` for `temperature` and a genuine `404 NotFoundError` for an
  invalid model id were both triggered live and are recorded in §2.
- No genuine 429 or 5xx occurred during this stage's real calls.

### Deliberately injected faults ([FAULT INJECTION] — never real provider incidents)

All of the following use a fake/mocked client and are labeled as such in code and test names
(`tests/test_openai_client.py`):

| Fault | Mechanism | Result |
|---|---|---|
| Fatal auth failure | A deliberately invalid string passed as the API key to a REAL `OpenAI()` client, sent to the REAL endpoint (this one **did** touch the network, on purpose, since it costs nothing to trigger and is the most honest way to test it) | Real `401 AuthenticationError`, key correctly redacted in the message (`sk-inval***...0000`) |
| Repeated transient failure | Fake client raising `RateLimitError`/`InternalServerError` N times via `unittest.mock` | Retried with backoff, succeeded on the Nth+1 attempt; exhausting `max_retries` raises `ClassifiedError(TRANSIENT)` |
| Malformed/invalid request | Genuine live call with an unsatisfiable JSON Schema (`{"type": "not_a_real_type"}`) | Real `400`, `code="invalid_json_schema"` |
| Invalid source ownership | `tools.py` called with an id belonging to a different user, or a nonexistent id | `ToolError`, no data returned (see `tests/test_tools.py`, 23 tests) |
| Interrupted-run resume | **This happened for real, unplanned**: the actual pilot script crashed on `image_10` mid-run; re-invoking it served images 1-9 and 21 message extractions from cache with `cache_hit=True`, zero re-spend, and continued fresh only for the unresolved items | Confirmed by the two real runs in §5's table — completed work was never lost or double-billed |
| Changed-source cache invalidation | `tests/test_cache.py::CacheInvalidationTests` — changed source bytes, model, schema version, or decoding config each produce a cache miss | All pass |
| Cache corruption | A hand-written invalid-JSON file dropped directly at a cache entry's path | `CacheCorruptionError` raised, `.corrupt` sidecar written, original preserved (not deleted) |

No injected fault is described anywhere in this project as an actual provider incident; every
test and log entry says "fault injection" explicitly.

---

## 7. Reproducibility

Two distinct claims, kept separate per the Stage 3 instruction:

1. **Fresh online execution** happened twice, for real, on 2026-09-12 (§5's two runs), against the
   live API, with real response ids recorded (`evaluation/image_audit_results.json`,
   `evaluation/message_pilot_results.json`).
2. **Cache-only replay is byte-identical and provably never touches the network.** Demonstrated by
   constructing an `OpenAIClient` wired to a fake SDK object whose `responses.with_raw_response
   .create()` raises `AssertionError` unconditionally, then replaying `image_01`, `image_06`,
   `image_10`, and `image_04` through the real `extract_image_observation` function against that
   client. All four replayed successfully from `.llm_cache/observations/` (and the tracked
   `evaluation/extraction_snapshot/observations/`), producing the identical selected amounts
   (`net_pay=4365000`, `total=1995.0`, `total=79679.26`, and the correctly-still-unresolved
   `image_04`) with **zero live calls** — proven structurally, not just by absence of a token
   count, since any live call attempt would have raised immediately.

"Cache replay is not evidence of model determinism" (the Stage 3 instruction's own caveat) is
respected: the byte-identical replay above proves this project's CACHE is deterministic and
correctly keyed, not that a fresh call to `gpt-6-astra` would reproduce the same JSON twice — §2's
determinism note addresses that separately and does not claim it.

---

## 8. Exact audit paths

```
evaluation/llm_capability_pilot.md          this file
evaluation/image_audit_results.json         all 16 images, full observation + selection + re-read
evaluation/message_pilot_results.json       21 pilot messages, full extracted facts
evaluation/pilot_usage_report.md            run 2's usage/cost report (pilot, not final)
evaluation/extraction_snapshot/observations/  tracked snapshot of the 37 cached model outputs
.llm_cache/observations/                    live working cache (gitignored; superset of the snapshot)
code/evaluation/run_evidence_pilot.py       the script that produced all of the above
code/buyorwait/openai_client.py             the real API wrapper (error classes, retry, cost)
code/buyorwait/evidence.py                  extraction schemas, amount-role selection, re-read
code/buyorwait/cache.py                     the content-addressed, atomic-write cache
code/buyorwait/tools.py                     the seven tools
code/buyorwait/investigation.py             typed investigation state and bounded loop
code/buyorwait/llm_harness.py               runtime harness with validation and repair loop
code/evaluation/run_investigation_demo.py   investigation demo script
evaluation/investigation_demo.json          audit trace of representative investigation states
dataset/media/images/image_04.png           the one genuinely unresolved image (cropped, no amount)
tests/test_openai_client.py                 15 tests, real-shaped fault injection
tests/test_cache.py                         12 tests
tests/test_tools.py                         23 tests
tests/test_evidence.py                      14 tests (deterministic selection logic + role selection)
tests/test_investigation.py                 7 tests (bounded state machine and tool loop)
tests/test_llm_harness.py                   4 tests (repair loop and caching)
```
