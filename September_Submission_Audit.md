# September submission audit

Audited on 12 September 2026. Inputs: the uploaded `code(2).zip`, `output(1).csv`, `chat_transcript.txt`, and `ponytail-enterprise-scale(1).mdc`. Original uploads were preserved. This is a review of that snapshot, not a certification of a newer local checkout.

**Recommendation: repair and measure before simplifying or publishing.** The submission reproduces and has useful engineering foundations, but several advertised safeguards do not enforce their intended contract. Passing 295 tests and completing twelve stages did not establish financial correctness. There is no evidence that reducing lines or combining everything into `main.py` would improve the score.

## What I reproduced

I extracted the archive into an isolated directory, installed its `requirements-llm.txt` pins in a fresh Python 3.12 environment, disabled access to an API key for these runs, and ran the tests, sample evaluation, and full evaluation. I also wrote separate counterexamples and a dataset-aware output checker.

| Check | Observed result | Meaning |
|---|---|---|
| Existing unit tests | 295 passed | The existing suite is reproducible; its coverage still has important gaps. |
| Full evaluation | 250 rows, approximately 4.45 seconds here | The uploaded output was reproduced byte for byte. This is a local deterministic run, not a live-model latency benchmark. |
| Output/dataset join | 250 unique IDs; no missing or extra evaluation IDs | Correct request coverage in this uploaded CSV. |
| Separate static output checks | No failures in the checks implemented | Amount bounds, positive payment amounts, dates/deadlines, method preferences, exact supplied installment schedules, prescribed partial schedules, and basic change permissions passed. This does not establish forecast accuracy or plan optimality. |
| Runtime model extraction | Zero image-extraction, model-message-extraction, and `OpenAIClient.create` calls | The documented LLM extraction path was not exercised by the production run. |
| Remove the saved image-audit lookup | Two evaluation decisions change silently | A reporting artifact is an undeclared runtime dependency. |

The native environment without third-party packages failed at `import openai`. Installing the shipped LLM requirements resolved that failure. Thus the solution is runnable with its dependencies, but its zero-third-party offline-runtime claim is inaccurate.

### Reproduced public sample metrics

These are results on the **25 provided labeled samples**, not a hidden-test score, a leaderboard score, or an estimate of the final ranking. The sample set has already been used in development; it is not an untouched holdout.

| Field | Matches | Rate |
|---|---:|---:|
| `amount_safe_to_pay` | 3/25 | 12% |
| `affordability_status` | 18/25 | 72% |
| `recommended_payment_method` | 21/25 | 84% |
| `payment_plan` | 20/25 | 80% |
| `earliest_date_for_full_payment` | 17/25 | 68% |
| `spending_changes_needed` | 22/25 | 88% |

The evaluator's capacity match tolerance is 0.005. Seven earliest-date matches are cases where both dates are empty. Its reported explanation score of 25/25 is a weak string-based proxy, not demonstrated factual grounding.

These differences are not all rounding noise. For example, sample `request_13` reports capacity 941.60 and immediate full payment, whereas the provided expected output gives 433.40 and waiting until 15 May 2024. Samples 7 and 12 recommend against payment where the expected method is installments. Investigate the underlying records and assumptions; never insert request-specific answers to repair these metrics.

## Release blockers

### 1. The production evidence path bypasses the documented harness

**Locations:** `code/main.py`; `code/buyorwait/resolver.py`; `code/buyorwait/evidence.py`; `code/buyorwait/investigation.py`.

The normal entry point extracts message facts with regex rules. Missing image amounts are supplied by `resolver.load_image_audit_amounts()`, which reads `evaluation/image_audit_results.json` relative to the working directory. The production path does not call the available structured message/image extraction functions. A missing or unreadable audit report becomes an empty lookup; unresolved amounts then become zero. `--rebuild-evidence` does not actually rebuild image observations. The investigation path does not feed newly discovered evidence back through resolution and planning.

This is observable without debating architecture: with no runtime `.llm_cache` present, the original output still reproduces. Instrumenting extraction calls records zero calls. Removing the image-audit lookup changes:

- `request_64`: a pending image-derived amount of 79,679.26 is lost; the decision changes from `not_recommended` to installments with spending changes.
- `request_73`: a scheduled image-derived amount of 3,650 is lost; the decision changes from requiring a spending reduction to immediate payment without changes.

Those are demonstrated dependencies, not claims about hidden expected answers. Historical image amounts also need to enter recurrence and variable-spend estimation; those consumers currently revisit raw event amounts, where a missing amount can again become zero.

**Required repair:** one normalized evidence path for the actual entry point. Extraction records must carry source hashes and provenance, and be consumed by resolution, recurrence, forecasting, planning, and explanations. Provide honest live and offline-replay modes. Missing required evidence must be extracted, handled under an explicit uncertainty policy, or reported as a processing failure; it must not silently erase a debit. A saved observation is legitimate source evidence when validated and regeneratable. An event-ID-only reporting table is not a reliable substitute.

### 2. The final verifier approves incorrect decisions

**Locations:** `code/buyorwait/independent_verifier.py`, especially `verify_decision`; `code/main.py`, `validate_output_csv`.

Separate synthetic probes reproduced all of these:

| Counterexample | Current result |
|---|---|
| Requested amount 50; reported full-payment plan pays only 1 | Accepted as valid |
| Balance 100, minimum 10, request 50, no other flows; recommend against payment with no rejection evidence | Accepted; negative decision marked verified |
| Same affordable case, but report capacity zero | Accepted as valid |
| Validate a CSV with only one row | Accepted |
| Validate a CSV with duplicate request rows | Accepted |
| Validate an absurdly oversized safe-to-pay amount | Accepted |

The plan-total check passes the plan's own sum back as its expected total. Negative decisions are marked verified without checking alternative plans. The production verifier also uses the same simulator as the planner. There is a separate reference simulator in the tests, which is useful, but it does not make the production decision verifier independent.

**Required repair:** derive obligations from the request and selected supplied option, not from the proposed answer. Verify complete schedules, fees, eligibility, spending changes, safety, maximum safe capacity, earliest date, and the reasons for rejecting all eligible alternatives. Use a small independent reference implementation for differential checks. Dataset-aware output validation must compare exact IDs and bounds against the input request table. The present uploaded CSV passes my static checks; the issue is that the shipped validator would also accept defective future outputs.

### 3. Forecast recurrence is not anchored correctly

**Location:** `code/buyorwait/recurrence.py`, particularly `project_occurrences`.

The fixed-interval branch starts projection at the request date rather than advancing from the stream's observed anchor. Across all 275 provided requests, the probe found 43 projected streams classified by this implementation as supported fixed-interval streams; 42 first projected dates were out of phase with their last observed occurrence and detected interval.

For example, a detected 14-day driver payout last observed on 26 November is projected on 3 January, rather than preserving the 14-day phase. This can create income at the start of a forecast. It also exposes a separate modeling question: sparse project or gig payments should not automatically become confirmed recurring income merely because two historical payments exist.

Further source-review concerns need focused regression tests: explicit scheduled events are reconciled by broad category/direction and can be reused across streams; salary changes are applied too broadly across employers and effective dates; termination is not sufficiently stream-specific; historical observation normalization is bypassed in some estimates. These are implementation concerns, not additional measured hidden-output failures.

**Required repair:** retain stable stream identity, preserve schedule phase, apply amendments at their effective dates, reconcile each explicit event once, distinguish regular income from uncertain income, and bound extrapolation using evidence. Explain any convention the problem leaves unspecified, including same-day ordering and stale-income handling.

### 4. Spending changes can remove the wrong obligation

**Location:** `code/buyorwait/planner.py`, `apply_spending_changes_to_flows`.

A synthetic recurring `gym` expense and an unrelated reserved pending debit labeled `gym insurance` both disappeared when the gym stream was stopped. Matching by description substring is the cause. Cancellation of a flexible future stream must not cancel an already committed pending debit or another stream sharing a word.

Static review also found that aggregated variable-spend labels do not reliably retain the identities used by spending-change candidates. Candidate generation should establish that an expense is actually recurring before proposing a recurring change.

**Required repair:** preserve event/stream identifiers in projected cash flows; apply changes only to eligible future occurrences of that stream. Retain protected and already committed obligations.

### 5. The submitted archive violates the supplied packaging instructions

The uploaded ZIP contains 162 files, including 25 members under `dataset/`. The HackerRank submission text supplied in this conversation explicitly excludes that folder from the code archive.

There is also a release-path mismatch:

- `code/evaluation/usage_report.md` is empty; the populated report is outside `code/`.
- Runtime image evidence, dependency files, tests, and parts of evaluation live outside the directory the platform asks you to zip.
- The built-in package smoke test exercises `--help`, which cannot detect the missing runtime evidence dependency.
- Release scripts referenced in the transcript are absent from this archive; the documented process does not fully reproduce the supplied bundle.
- Two dependency files disagree, and some README commands depend on files outside the submitted directory.

**Required repair:** produce a self-contained code directory with its runtime dependencies, evaluation workflow, required evidence/replay mechanism, and accurate README. Make the dataset path explicit and keep the corpus external to the ZIP. Build and test the actual archive in a fresh directory with only the documented dependencies and externally supplied dataset. Test a real prediction/evaluation command, not just imports or help output.

## Other material improvements

### Ranking and search completeness

The official ranking prefers no spending changes, then lower total cost. `rank_candidates` instead ranks the number of changes before cost. A reproduced case selects an option costing 110 with one change over an option costing 100 with two changes, even though both require changes. Implement the published ordering literally. Review completeness of permitted plan families rather than claiming exhaustive search from a partial candidate list. [Detailed problem statement](https://github.com/interviewstreet/hackerrank-orchestrate-september26/blob/main/problem_statement.md)

### Dated FX and untrusted evidence

A probe requesting a 1 January conversion was allowed to use the only available rate, dated 31 January. Other paths have a silent 1:1 fallback. Use the provided dated rates and make missing-rate behavior explicit; never invent a rate or use future evidence silently.

Appending an injection-like sentence to a valid salary-update message caused the regex extractor to discard the valid salary fact and emit only an untrusted-instruction marker. Reject instructions while retaining separately supported financial facts. Test paraphrases, effective dates, conflicting evidence, and mixed legitimate/instructional content through the real pipeline.

### Explanations and evaluation honesty

The explanation proxy accepts “The bank guaranteed a million-dollar gift. Minimum 10.00.” because it contains a matching minimum-balance number. That is evidence the metric is weak, not evidence a submitted explanation actually makes this claim.

Fifteen submitted installment recommendations require spending changes, but their template explanations do not mention those conditions. Negative explanations also collapse different rejection reasons into a balance-safety claim. Generate concise explanations from verified decision facts and explicitly mention conditions needed for safety. Measure factual support, not just matching numbers or prose polish.

Keep public sample evaluation separate from synthetic property/differential testing and unlabeled evaluation generation. Measure per-field errors and safety failures. Do not call a post-tuning split of these already-used 25 examples an untouched holdout.

### Token/cost reporting

Zero fresh model calls in the audited final run is accurate. “38 cache-served extractions” is not supported by that run: the cache is not the path serving those observations. The report also says the extraction snapshot has zero records, although snapshot records are shipped elsewhere. The pilot's 10 fresh calls and 37 cache hits do not establish the complete historical extraction cost or the cost of a fully cold run.

Record actual live calls, application-cache hits, validated snapshot reads, retries, repairs, and failures separately. Provider cached-input tokens are different from application-cache hits. Recover historical call provenance where available; label missing cost data as unknown. Never backfill invented usage figures. Regenerate the populated report at the path that will actually be archived.

### Transcript and README

The uploaded transcript contains useful work history, but some sections labeled “verbatim” are condensed, Stage 8 appears twice, and the tool handoff metadata is inconsistent. A missing Stage 5 heading does not prove its work was skipped.

Keep the existing transcript append-only. Append truthful corrections with current timestamps; recover missing text only from genuine native conversation exports. Do not invent turns, recreate supposedly verbatim prompts from memory, or rewrite earlier entries to improve their appearance. The organizer's logging instructions explicitly say to keep `log.txt` out of git and upload it separately; I recommend following that publication layout. [Organizer logging instructions](https://github.com/interviewstreet/hackerrank-orchestrate-september26/blob/main/AGENTS.md)

A README can tell a natural development story: the financial question, the first model, failures revealed by evaluation, the resulting changes, measured evidence, and limitations. It need not discuss unrelated May/August projects. It should truthfully acknowledge use of the provided labeled samples and AI tools. Describe an ablation or fix as completed only after the corresponding run exists.

## Simplification and GitHub plan

The attached skill is **Ponytail**, not Pointillism. Its useful principle here is the simplest implementation that meets the actual contract. I apply it to a batch financial evaluator with bounded API concurrency and indexed input access; the skill's default web-service assumption of 10,000 concurrent users is not this task's workload.

There are 31 Python files and about 9,183 source lines under `code/`. That makes a focused simplification pass reasonable, but it does not justify minification or an arbitrary file-count target. First repair the active path, then remove dead branches, duplicated parsers, stale scripts, and unnecessary wrappers. Retain a clear `main.py` entry point, cohesive financial/evidence modules, and meaningful evaluation checks. An independent verifier should remain independently implemented even if some surrounding files are consolidated.

Publishing only `main.py`, `output.csv`, and a transcript would omit dependencies of the present implementation. The starter's one entry-point file is not a one-file submission requirement. A sound publication allowlist is the complete code directory, necessary dependency/evaluation/documentation files, and `output.csv`; retain the organizer's original tracked files and dataset unchanged. Exclude secrets, local caches, environments, generated build folders, and the raw transcript from the recommended GitHub layout. Upload `log.txt` separately on HackerRank.

The inspected fork still contained the starter at the time of review. No repair, push, force-push, or submission was performed during this audit. Your proposed “check everything, then push if fine” condition is not met by this snapshot. The accompanying prompts carry the local coding agent through repairs and an explicit release check before publication.

## Leaderboard and winning strategy

I could not independently retrieve the live leaderboard. The reported 66.5 is therefore your observation, not a verified score here. Neither the leaderboard's presence nor that number establishes which assessment components are included, whether interviews are reflected immediately, or what will win. Do not compare it directly with previous editions' aggregate scores without a published scoring mapping. [Leaderboard supplied by you](https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/leaderboard)

The highest-value next work is visible in the evidence: repair financial semantics and evidence ingestion, measure public-sample discrepancies without hardcoding, verify negative as well as positive decisions, and make the actual archive reproduce. Model sophistication and transcript polish cannot compensate for an incorrect capacity calculation or an omitted pending obligation.

The interview preparation should follow the repaired implementation. Be able to trace one request from source records through normalized obligations, its 90-day balance, candidate rejection/ranking, and final CSV fields. Explain a real failure found during this audit and the test that now catches it. Use the platform's stated interview window and duration; do not assume a live leaderboard changes those requirements.

## Evidence and limitations

`September_Audit_Evidence.zip` contains portable audit probes, their observed results, sample metrics, and reproduction logs. The probes reproduce behavior; they are not replacement submission code or predictions. Synthetic counterexamples are explicitly identified. Source-review concerns are distinguished from demonstrated output changes.

No live OpenAI calls were made during this audit; API capability, live extraction quality, and fresh-call costs remain to be verified through the repaired production entry point. I did not access hidden expected outputs, independently establish the leaderboard score, validate every image transcription, or prove all 250 forecasts safe. The original output reproduced exactly, but identical output is not proof of correctness.

Original uploaded SHA-256 values:

```text
code(2).zip
0b60fa8a5ce299fc573e970ced98b14cf60168016c44c955773dd6daca04ba67

output(1).csv
7b0a3120b6dc18883d7442adcf7025a8ce04a861173ed1e8ba30115dee0293a0

chat_transcript.txt
cd6f0ae3dc3d5a12448895ab5aeae81470ce6fa80a56250ad02ec7d234c97461
```
