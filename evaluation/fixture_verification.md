# fixture_verification.md — independent adversarial verification of Stage 2 fixtures

Every scenario fixture in `code/evaluation/fixtures/scenarios.py` is checked twice, by two
genuinely different mechanisms:

1. **Code-level replay** (`tests/test_fixtures.py`): each fixture's claimed numbers are fed
   through `buyorwait.simulator.simulate` / `buyorwait.independent_verifier.replay_plan` — the
   same rules engine production code will eventually use — and asserted against. This confirms
   the numbers are *arithmetically self-consistent* with a real, tested implementation.
2. **Independent model-based re-derivation** (this file): eight separate agents, one per
   fixture, each given only the fixture's raw inputs and the relevant contract rules (quoted
   below, not this project's code) were asked to recompute the expected outcome from scratch
   and state whether they agreed. None of the eight ever saw this project's source code,
   `scenarios.py`'s stated expectations framed as a claim to check, or each other's answers.

This second check exists because (1) alone only proves the numbers are consistent with *this
project's own* simulator — it does not catch a mistake in how contract.md's *rules themselves*
(S-08, S-09, S-10, S-12, S-14, S-15) were hand-applied to reach a status/method, since those
assignments are reasoned by hand, not computed by any module built so far.

## Method

Run via the `Workflow` tool, 2026-09-12, 8 agents in parallel, one per fixture. Each agent
received:

- the exact rule text (S-02, S-03, S-05 through S-15, plus this project's own U-SIMORDER-1
  same-day convention), transcribed from `evaluation/contract.md`;
- the fixture's raw profile/request/event/option numbers, in prose;
- the claimed expected outcome;
- an instruction to independently recompute step by step and report `agrees_with_claim` plus
  a full written derivation, explicitly told not to trust the claim.

## Result

**8 of 8 fixtures reviewed. 0 disagreements.**

| Fixture | Verdict |
|---|---|
| FIX-01 | agrees |
| FIX-02 | agrees |
| FIX-03a | agrees |
| FIX-03b | agrees |
| FIX-04 | agrees |
| FIX-05 | agrees |
| FIX-06 | agrees |
| FIX-07 | agrees |

Every independent derivation reproduced the exact claimed values (`amount_safe_to_pay`,
`affordability_status`, `recommended_payment_method`, `earliest_date_for_full_payment`, and, for
the ranking fixtures, the chosen `payment_option_id`) through its own step-by-step arithmetic —
not by restating the claim. FIX-02's independent derivation, in particular, re-derived the
"never safe unaided anywhere in the 90-day window" conclusion by checking the same three date
ranges (before, on, and after the subscription date) that this project's own exhaustive 91-day
test (`tests/test_fixtures.py::Fix02Tests::test_full_amount_is_never_safe_unaided_anywhere_in_the_90_day_window`)
checks numerically.

Full transcripts (each agent's complete written derivation) are preserved in this session's
workflow journal; the raw structured result is not duplicated here to keep this file short, but
run `Workflow` with `resumeFromRunId: "wf_6e988497-5f8"` against the saved script (path recorded
in `evaluation/state.md`) to replay the cached agent outputs verbatim if a full transcript is
needed later.

## What this does and does not establish

This confirms the eight fixtures correctly apply the WRITTEN rules to the numbers as given. It
does **not** confirm that the written rules, once implemented in a real planner (Stage 4), will
be interpreted identically by that implementation, and it does **not** substitute for
`tests/test_fixtures.py`'s own numeric checks, which remain the fast, zero-token,
every-commit-runnable verification. Both are run; neither replaces the other.
