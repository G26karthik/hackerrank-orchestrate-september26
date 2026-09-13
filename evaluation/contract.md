# contract.md — Buy or Wait? (HackerRank Orchestrate, September 2026)

Authoritative requirement-to-source mapping. Every row cites the participant-facing document
that imposes the requirement. Nothing here is inferred from organizer-only material; where a
requirement is not stated in a public document it is marked as an interpretation and lives in
`assumptions.md` instead.

Stage 1 recorded this file. Later stages may only append or correct with a cited source.

---

## 1. Recorded facts (verified 2026-09-12)

### 1.1 Repository state

| Item | Value |
|---|---|
| Implementation remote (`origin`) | `https://github.com/G26karthik/hackerrank-orchestrate-september26` |
| Branch | `main` (tracking `origin/main`) |
| HEAD commit | `963ad7eb3d058ace2bf2e8bf4324472c981f0840` |
| HEAD subject | `docs: clarify participant setup and outputs` (2026-09-12 15:46:42 +0530, Pawan Ajjar K) |
| Working tree at stage start | clean; no stashes |
| Organizer remote `main` | `963ad7eb3d058ace2bf2e8bf4324472c981f0840` — **identical to local HEAD** |
| Organizer other refs | `refs/heads/codex/update-orchestrate-readme` and `refs/pull/1/head` both at `c58e55d4fc61b50353bf25d9da60e8eb9e8d0fdf` (the parent commit; not merged into `main`) |
| Instruction drift vs organizer | **none** — local instruction files are byte-identical to organizer `main` |

Verification commands used: `git remote -v`, `git branch -vv`, `git log -3`, `git status --porcelain=v1`,
`git stash list`, `git ls-remote https://github.com/interviewstreet/hackerrank-orchestrate-september26.git`.

### 1.2 Clock and deadline

| Item | Value |
|---|---|
| Session start (local) | `2026-09-12T18:53:05+05:30` (`2026-09-12T13:23:05Z`) |
| Clock at contract write | `2026-09-12T19:01:57+05:30` (`2026-09-12T13:31:57Z`) |
| Official deadline | `2026-09-13T18:00:00+05:30` |
| Deadline source | `AGENTS.md` §3.3 (literal ISO string) and §3.2 (prose: "6:00 PM IST on September 13, 2026") |
| Remaining at contract write | 0d 22h 58m |
| Verification result | The inspected deadline `2026-09-13T18:00:00+05:30` **matches** the current files exactly. No change to record. |

`problem_statement.md` and `README.md` contain no deadline; `AGENTS.md` is the only source.

### 1.3 Input SHA-256 (participant-facing inputs and instruction documents)

Instruction documents:

| Path | SHA-256 |
|---|---|
| `AGENTS.md` | `bba4767f21d4fac3eefc3ee3af1f9a639babbf70540677b7c1764f9cb7ed255d` |
| `CLAUDE.md` | `d631d88045f74623d568adfb4783b72e3d1b732330d749bc6c72e6648d4581d3` |
| `README.md` | `f443e431b853f3e70fbed8a524e87d6e172321a891ce2481513b6958e18bfa13` |
| `problem_statement.md` | `3b2bf6889e36ae124e3cc4ce4df98eac8b7dcccf42f92c8e4dc363d722430bd3` |

Dataset CSVs:

| Path | SHA-256 |
|---|---|
| `dataset/requests.csv` | `13663d50b7098b28a8c087a02eb085041260999707adade5230d29f1c2e6595d` |
| `dataset/sample_requests.csv` | `117bf2ab9e5f0054bae48afe8506f5daa35929559cb771f2c27dd4fe18da62f6` |
| `dataset/financial_profiles.csv` | `fa173608f8ec99c8d9d633eace762695aeaa2d276a509989f0edd8e123c07964` |
| `dataset/financial_events.csv` | `b6c3f43a8ad3a80ca11c72cce6f2818eea06621a3582d2851886fd9127b1229d` |
| `dataset/request_payment_options.csv` | `4922c56f10c06698d24b86b8a43580cbc6bc6ee44c95936c3037878005980c40` |
| `dataset/exchange_rates.csv` | `ff56e9feb482f909837dc309f52f8de5b167d9d6685a2ee8e8fd807639658a04` |
| `dataset/messages.csv` | `7b9db27a4546a850a76d3475ebf65de80fb9fe374e26d469586f62f537eac9a6` |
| `dataset/images.csv` | `6b5428565ca98e4b71e182f8a8fa3fd3013727399bdea847f3e4a3d2c129dfc9` |
| `dataset/output.csv` (template, must stay unchanged) | `e6e6f4aae1eed6d1c178fd3daca7b5ad82cc9c1461650969c373b4dedab43baf` |

Organizer starter code files (all three are 0 bytes; preserve, do not delete):

| Path | SHA-256 |
|---|---|
| `code/main.py` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty file) |
| `code/evaluation/main.py` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty file) |
| `code/evaluation/usage_report.md` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty file) |

Images (`dataset/media/images/`):

| File | SHA-256 | Pixels |
|---|---|---|
| `image_01.png` | `f37b40e6af42c664846057252cac89ad41b7d029dfe8dacff2db8cceb79fa5ba` | 1628x1366 |
| `image_02.png` | `ccd779e5382b1bcfacfb47d4ccf346ffd667a34c8b94d0cfd48aa4a609bd117d` | 1166x1330 |
| `image_03.png` | `e5fb0bbcda6cc06f8ea95e32e45d4c76acd8c594f4b02ff0d78e6006e103ee4d` | 614x1170 |
| `image_04.png` | `281e7f1e7bd1f98fbd53cde1381977373e610e6634b11c98098000001ff10f0c` | 588x966 |
| `image_05.png` | `9abcda5647afb3dcdf91613253ac0160bd722333af33a4b952dfc96fea6ff97b` | 1460x946 |
| `image_06.png` | `9055551fbe5940feb01b947e1f18ccfed093192d103b1e930a56df0ea7cd3cb4` | 1162x1026 |
| `image_07.png` | `f6d30a74355224c0b5cda2d7f96399a7b1a0afe4f9fe59ea048bbecb1a21311e` | 524x854 |
| `image_08.png` | `e28592ad8b4dacd03055e0b1ebc46670c83fbfa1162af07bdef33bb226bf63c8` | 1560x950 |
| `image_09.png` | `e0e74e14425d923ff8a5c6db26ec6f4f26ee4697bfd257e414ba05c947a75ba8` | 1532x654 |
| `image_10.png` | `c90f98caf0877083e471fd47dace772f83d4782037cf112e97c63f79a10ea8cf` | 932x1332 |
| `image_11.png` | `795e000d48428c97748e8af370cb02b604bec88cc52ec8930f38dc744624e886` | 956x1296 |
| `image_12.png` | `e10b0123e66d512d82f6c431fb741053b336627b89b9d9a138071ac6980a14ff` | 512x964 |
| `image_13.png` | `1ae54b378a9556d94b753093ba80e7117caf86fab4d3fe11ec84e3dd2f6d6dd8` | 1340x884 |
| `image_14.png` | `bf88e4aa35e6f36304cbf76bf6f505f32b04466bfd5f7df693fcb3ebe8a3e2c1` | 790x364 |
| `image_15.png` | `0c0fe3d79e670f2b423bbb2aafc0b5601d3eb4e659ac64058cd189abf7792ee1` | 1440x1238 |
| `image_16.png` | `2665cf731a861ddb217be5b8082fbd390850a7a98feec018519b6fda0b30b4f8` | 1440x1030 |

---

## 2. Output contract

### 2.1 Required columns, exact order

Source: `problem_statement.md` "Required output"; `AGENTS.md` §6.2; `README.md` "What You Need to Build".
All three agree character-for-character:

```
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

The blank template `dataset/output.csv` carries the same header, CRLF line endings, and 250
pre-seeded `request_id` values `request_26` … `request_275` with all other cells empty
(251 CRLF-terminated lines, 5094 bytes).

### 2.2 Enumerations

| Field | Allowed values | Source |
|---|---|---|
| `affordability_status` | `affordable_now`, `affordable_with_plan`, `affordable_later`, `not_affordable` | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2 |
| `recommended_payment_method` | `full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended` | same |
| `payment_plan` | `YYYY-MM-DD:amount` entries, chronological, joined by `\|`; or the literal `none` | same |
| `earliest_date_for_full_payment` | `YYYY-MM-DD`, or empty string | `problem_statement.md` "Output meaning" + "Allowed values" |
| `spending_changes_needed` | `none`, or up to three actions joined by `\|`, each `stop:<event_id>` or `reduce_to:<event_id>:<new_amount>` | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2 |
| `amount_safe_to_pay` | number with `0 <= amount_safe_to_pay <= requested_amount` | `problem_statement.md` "Output meaning"; `AGENTS.md` §6.2 |

Input enumerations observed and confirmed against the spec:

| Field | Values | Note |
|---|---|---|
| `requests.request_type` | `purchase`, `travel`, `education`, `family_transfer`, `debt_repayment`, `investment`, `housing`, `emergency_expense`, `other` | 9 values, matches `problem_statement.md` list exactly |
| `financial_events.event_type` | `expense`, `subscription`, `income`, `debt_payment`, `investment_purchase`, `refund`, `investment_valuation`, `investment_sale` | 8 values; not enumerated in the spec, observed only |
| `financial_events.status` | `settled`, `pending`, `scheduled`, `cancelled`, `failed`, `unrealized` | 6 values; the spec names all six |
| `financial_events.direction` | `debit`, `credit`, `non_cash` | 3 values |
| `financial_events.flexibility` | `fixed`, `reducible`, `stoppable`, `reducible_or_stoppable` | 4 values; not enumerated in the spec, observed only |
| `request_payment_options.payment_method` | `full_payment`, `installments` | 2 values only — no `partial_payment` option rows exist |
| `financial_profiles.payment_methods_user_will_consider` | subset of `full_payment`, `partial_payment`, `installments`, `\|`-joined | 3 tokens |
| currencies | `INR`, `ZAR`, `IDR`, `USD`, `EUR` | matches `problem_statement.md` |

### 2.3 Hard invariants the writer must enforce

| Invariant | Source |
|---|---|
| Exactly one output row per `request_id` in `dataset/requests.csv` (250 rows + header) | `AGENTS.md` §6.1; `README.md` "Before submitting" |
| `0 <= amount_safe_to_pay <= requested_amount` | `problem_statement.md` "Output meaning" |
| `affordable_now` implies `earliest_date_for_full_payment == request_date` | `problem_statement.md` "Output meaning"; `AGENTS.md` §6.2 |
| `earliest_date_for_full_payment` empty when no safe full payment exists inside the forecast period | same |
| `partial_payment` implies `affordability_status == affordable_with_plan` | `problem_statement.md` "Allowed values" |
| `partial_payment` requires `allows_partial_payment` true, `partial_payment` in `payment_methods_user_will_consider`, `0 < amount_safe_to_pay < requested_amount`, and `earliest_date_for_full_payment <= desired_completion_date` | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2 |
| `partial_payment` plan has exactly two entries: `request_date:amount_safe_to_pay` then `earliest_date_for_full_payment:(requested_amount - amount_safe_to_pay)`, summing to `requested_amount` | same |
| An `installments` plan must exactly match one supplied `request_payment_options` row | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2 |
| At most three spending changes; only `stop:` and `reduce_to:` forms | `problem_statement.md` "Allowed values" |
| Stop and reduce must not target the same `event_id` | `problem_statement.md` "Choosing Between Safe Plans" |
| Only recurring expenses marked flexible, not protected, and in a category the user permits may be changed | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2; `README.md` |
| Balance never below `minimum_balance_to_keep` at any point in the 90-day forecast | `problem_statement.md` "90-Day Safety Check"; `AGENTS.md` §6.3 |
| Plan must complete the request by `desired_completion_date` | `problem_statement.md` "90-Day Safety Check" |

### 2.4 Method eligibility and ranking (verbatim rule structure)

Source: `problem_statement.md` "Choosing Between Safe Plans".

Eligibility:
- `full_payment`, `partial_payment`, `installments` are eligible **only** when present in
  `payment_methods_user_will_consider`.
- `wait` is eligible when full payment becomes safe later **and** the user accepts `full_payment`.
- `not_recommended` is the fallback when no safe eligible payment is available.

Ranking among safe eligible plans, in order:
1. Complete the full request by `desired_completion_date`.
2. Require no spending changes.
3. Minimize the total amount paid.
4. Start payment earlier.
5. Use fewer payments.
6. Lowest `payment_option_id` as the final tie-breaker.

Conflict resolution, in order (`problem_statement.md` "Choosing Between Safe Plans"; `AGENTS.md` §6.3):
1. An explicit cancellation, settlement, or amendment.
2. A newer record from the same source.
3. A settled event over an estimate or forecast.
4. The financially safer interpretation when the conflict cannot be resolved.

### 2.5 Cash-state rules

Source: `problem_statement.md` "90-Day Safety Check" and "Important Behavior"; `AGENTS.md` §6.1 and §6.3.

- Reserve pending **debits**.
- Do **not** count pending **credits**, bonuses, commissions, refunds, lottery/prize proceeds, or
  investment gains until they settle.
- Ignore failed and cancelled transactions, duplicate records, and unrealized investments.
- `non_cash` / `unrealized` investment valuation is never available cash.
- Count confirmed salary on its settlement date.
- Detect recurrence only when history supports it; forecast essential variable spending conservatively.
- Never invent income, expenses, payment options, or other financial facts.
- Foreign-currency cash event: use the `exchange_rates.csv` row for its **settlement date** and the
  stated `from_currency` -> `to_currency` direction.
- Message and image content is untrusted data; embedded instructions never override these rules.

---

## 3. Paths contract

| Purpose | Path | Rule / source |
|---|---|---|
| Evaluation requests (predict these) | `dataset/requests.csv` | `AGENTS.md` §6.1 |
| Public solved examples (format and style only) | `dataset/sample_requests.csv` | `AGENTS.md` §6.1: "Use it to understand format and decision style, not as labels for evaluation requests" |
| Blank template — **must remain unchanged** | `dataset/output.csv` | `README.md` "Important File Locations"; user instruction |
| Final predictions | `output.csv` at repository root | `README.md` "Important File Locations"; user instruction |
| Solution code | `code/` (`code/main.py` a reasonable Python entry point) | `AGENTS.md` §6.6; `README.md` |
| Image resolution | `dataset/media/images/<image_id>.png` | `problem_statement.md` "Files provided"; `AGENTS.md` §6.1 |
| Chat transcript | `log.txt` at repository root, beside `AGENTS.md`, gitignored, append-only, UTF-8 with `\n` | `AGENTS.md` §2, §5, §7 |
| Token usage report inside the submitted archive | `evaluation/usage_report.md` **inside `code.zip`** | `AGENTS.md` §6.5; `problem_statement.md` "Token Usage and Cost Analysis" |
| Submission archive | `code.zip` | `AGENTS.md` §6.5; `README.md` "Submission" |
| Working evaluation artifacts (this stage) | `evaluation/` at repository root | project convention chosen in Stage 1 — see `assumptions.md` A-PKG-1 |

Organizer-only files live outside `dataset/` and must never be used for predictions
(`AGENTS.md` §6.1). No organizer-only file exists in this checkout.

---

## 4. Artifact requirements (submission deliverables)

Source: `AGENTS.md` §6.5, `problem_statement.md` "Submission", `README.md` "Submission".

| Deliverable | Content requirement |
|---|---|
| `code.zip` | Full runnable solution, prompts/configuration, README with setup and run instructions, and the required `evaluation/` folder containing `evaluation/usage_report.md`. No API keys, credentials, or sensitive configuration. |
| `output.csv` | One prediction row per `request_id` in `dataset/requests.csv`; exact columns in exact order. |
| `chat_transcript` | The root `log.txt` produced under `AGENTS.md` §2/§5. |
| `evaluation/usage_report.md` (inside `code.zip`) | Must describe the **final full-dataset run that produced `output.csv`**: model providers and names, model calls, input tokens, output tokens, total tokens, average tokens per request, estimated total cost, estimated per-request cost. If multiple models are used, per-model **and** overall totals in the same file. |

Runtime constraints that make the submission evaluable (`AGENTS.md` §6.4; `README.md` "Requirements"):
runnable from the terminal, reads inputs from `dataset/`, no organizer-only files, no hardcoded
labels, deterministic where possible, secrets from environment variables only, clear setup and run
instructions in the package.

---

## 5. Logging contract (AGENTS.md §2 and §5)

- File: `log.txt` in the directory containing `AGENTS.md` (repository root here). Resolved relative
  to `AGENTS.md`, never hardcoded to a user path.
- Append-only. Never rewrite, reorder, or delete prior entries.
- `.gitignore` must list `log.txt`. Done in Stage 1.
- UTF-8, `\n` line endings. Verified: current `log.txt` has 0 CR bytes.
- Every `SESSION START` and per-turn entry must carry exactly one non-empty `tool=` line naming the
  running harness. **This harness identity is `Claude Code`** (runtime reports `2.1.269 (Claude Code)`).
  A bare model name, a generic label such as `AI`, or a different harness name invalidates the entry.
- Session-start entry fields: `tool=`, `Repo Root:`, `Branch:`, `Worktree:`, `Parent Agent:`,
  `Language:`, `Time Remaining:`.
- Per-turn entry fields: heading with ISO-8601 timestamp and a title of at most 80 characters,
  `User Prompt (verbatim, secrets redacted):`, `Agent Response Summary:` (2-5 sentences),
  `Actions:` bullet list, and a `Context:` block with `tool=`, `branch=`, `repo_root=`,
  `worktree=`, `parent_agent=`.
- Never log API keys, tokens, cookies, OAuth codes, private keys, or sensitive PII. No credential
  has appeared in this conversation; nothing required redaction so far.
- Sub-agents and worktrees append to this same file with `parent_agent=` set.

### 5.1 Mandatory submission link (AGENTS.md §4.1)

If the user asks where or how to submit, the response must contain this exact URL verbatim:

https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission

---

## 6. Requirement-to-source mapping (index)

| # | Requirement | Source | Where handled |
|---|---|---|---|
| R1 | One output row per evaluation request, exact column order | `AGENTS.md` §6.1-6.2, `problem_statement.md`, `README.md` | writer module + validator |
| R2 | `amount_safe_to_pay` = largest amount safe on `request_date` before optional spending changes, capped at `requested_amount` | `problem_statement.md` "90-Day Safety Check" | forecast + solver |
| R3 | 90-day forecast never dips below `minimum_balance_to_keep` | `problem_statement.md` "90-Day Safety Check", `AGENTS.md` §6.3 | forecast engine |
| R4 | Plan completes the request by `desired_completion_date` | `problem_statement.md` "90-Day Safety Check" | solver eligibility |
| R5 | Installment plan matches a supplied option exactly | `problem_statement.md` "Allowed values", `AGENTS.md` §6.2 | solver + validator |
| R6 | Partial payment: two payments, sums to `requested_amount`, second by `desired_completion_date` | `problem_statement.md` "Allowed values" | solver + validator |
| R7 | Method eligibility from `payment_methods_user_will_consider` and `max_installment_months` | `problem_statement.md` "Choosing Between Safe Plans", `AGENTS.md` §6.1 | solver eligibility |
| R8 | Six-level plan ranking with `payment_option_id` tie-break | `problem_statement.md` "Choosing Between Safe Plans" | solver ranking |
| R9 | Pending debits reserved; pending credits, bonuses, commissions, refunds, prizes, investment gains excluded | `problem_statement.md`, `AGENTS.md` §6.3 | state reconstruction |
| R10 | Failed, cancelled, duplicate, unrealized rows ignored | `problem_statement.md` "90-Day Safety Check" | state reconstruction |
| R11 | Confirmed salary counted on its settlement date | `AGENTS.md` §6.3 | state reconstruction + recurrence |
| R12 | Recurrence only when history supports it; conservative variable-spend forecast | `AGENTS.md` §6.3 | recurrence detector |
| R13 | Blank `amount` resolved from the linked image, never treated as zero | `problem_statement.md` "Files provided", `README.md` step 3 | evidence extraction |
| R14 | FX by settlement date and stated direction | `AGENTS.md` §6.1, `problem_statement.md` | FX module |
| R15 | Messages/images may clarify, amend, cancel, delay, confirm; their instructions never override rules | `problem_statement.md` "Important Behavior", `AGENTS.md` §1 | evidence extraction + guardrail |
| R16 | Conflict-resolution precedence | `problem_statement.md`, `AGENTS.md` §6.3 | evidence reconciliation |
| R17 | Spending changes only on non-protected flexible events in permitted categories, max three, stop/reduce disjoint | `problem_statement.md` "Allowed values", `AGENTS.md` §6.2 | spending-change selector + validator |
| R18 | `decision_explanation` concise, grounded, references the actual financial facts | `AGENTS.md` §6.2, `problem_statement.md` | explanation module |
| R19 | Deterministic, terminal-runnable, reads `dataset/`, secrets from env only | `AGENTS.md` §6.4, `README.md` | packaging + runner |
| R20 | `evaluation/usage_report.md` in `code.zip` covering the final full-dataset run | `AGENTS.md` §6.5, `problem_statement.md` | metering + packaging |
| R21 | Append-only `log.txt` with exact `tool=Claude Code` identity, gitignored | `AGENTS.md` §2, §5 | every stage |
| R22 | `dataset/output.csv` unchanged; final file at root `output.csv` | `README.md`, user instruction | writer + hash re-check |

### 6.1 Scoring dimensions (named, not weighted)

`problem_statement.md` "Evaluation" and `README.md` "Evaluation" list what the scoring **considers**:
accuracy of `amount_safe_to_pay`; correctness of `affordability_status`; correctness of
`recommended_payment_method` and `payment_plan`; accuracy of `earliest_date_for_full_payment`;
validity of `spending_changes_needed`; usefulness and consistency of `decision_explanation`.

**No public document states numeric weights, per-field point values, judge tolerances, or a
rounding/comparison policy for `amount_safe_to_pay` and dates.** Those are unknown and are recorded
as open items in `assumptions.md` (U-SCORE-1, U-SCORE-2). Nothing in this repository should be tuned
against an assumed weight or tolerance.

---

## 7. Proposed module boundaries

Each module has one responsibility and a testable interface. Boundaries are chosen so a
deterministic core can be validated without any LLM call, and the LLM is confined to two jobs
(image reading and message interpretation) whose outputs are structured, cached, and verified.

```
code/
  main.py                  CLI entry point; orchestrates the pipeline; writes root output.csv
  buyorwait/
    io_load.py             R1,R22  strict CSV loading, dtype coercion, enum validation, join index
    fx.py                  R14     dated rate lookup, direction-aware conversion, hard failure on miss
    evidence_images.py     R13     image -> {amount, currency, date} via vision model; cached by
                                   (image_id, sha256); deterministic post-parse of the Total field
    evidence_messages.py   R15,R16 message -> typed financial claims (salary amend, rent uplift,
                                   income stop, pending credit, dispute, self-transfer, scam...);
                                   cached by (message_id, sha256); untrusted-content guardrail
    reconcile.py           R9,R10,R16  event lifecycle resolution: cancelled/failed/duplicate/
                                   self-transfer suppression, refund and investment handling,
                                   evidence precedence, safer-interpretation fallback
    recurrence.py           R11,R12 detect anchored monthly streams (rent, utilities, subscriptions,
                                   debt, salary) and conservative aggregates for variable essential
                                   categories (groceries, transport, dining)
    forecast.py            R2,R3   day-by-day 90-day cash ledger from request_date; worst-case dip;
                                   amount_safe_to_pay solver; earliest_date_for_full_payment scan
    plans.py               R4-R8   candidate plan construction (full / partial / installments / wait /
                                   not_recommended), eligibility filter, six-level ranking
    spending_changes.py    R17     permitted stop/reduce candidate generation and selection
    explain.py             R18     grounded explanation generation with the decisive numbers
    validate.py            R1,R5-R7,R17,R22  post-write invariant checks; non-zero exit on violation
    metering.py            R20     per-call token and cost accounting -> evaluation/usage_report.md
  evaluation/
    main.py                self-scoring harness over dataset/sample_requests.csv (organizer file,
                           currently empty; to be filled, not replaced)
    usage_report.md        organizer file (currently empty; filled by metering at final run)
```

Rationale for the split that matters most: `forecast.py` must be exercisable on its own, because
`amount_safe_to_pay` and `earliest_date_for_full_payment` are the two fields that cost the most
points and both are pure functions of the reconstructed ledger. Keeping evidence interpretation
(`evidence_*`) behind a cache and a typed schema means the deterministic core can be re-run and
re-validated hundreds of times at zero token cost, which is the specific discipline that was missing
in previous attempts.
