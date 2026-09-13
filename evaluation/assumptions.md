# assumptions.md

Three strictly separated sections:

- **§1 Specified rules (S-*)** — stated in a participant-facing document. Cited. Not negotiable.
- **§2 Observed examples (O-*)** — patterns measured in the dataset or in the 25 public samples.
  Evidence about how the organizer's generator behaves. **Not rules.** An O- item may be wrong about
  the hidden set.
- **§3 Unresolved interpretation (U-*)** — where the documents do not decide. Each carries the
  conservative default adopted, the reasoning, and what would change it.

Nothing in this file claims knowledge of September scoring weights, per-field point values, or judge
tolerances. Those are recorded as unknown in U-SCORE-1 and U-SCORE-2.

---

## 1. Specified rules (S-*)

| ID | Rule | Source |
|---|---|---|
| S-01 | Predict every `request_id` in `dataset/requests.csv`; exactly one row each; exact column order. | `AGENTS.md` §6.1-6.2; `README.md` |
| S-02 | `0 <= amount_safe_to_pay <= requested_amount`. | `problem_statement.md` "Output meaning" |
| S-03 | `amount_safe_to_pay` is the most the user can pay **on `request_date`**, **before** optional spending changes, without breaking the 90-day safety check, capped at `requested_amount`. | `problem_statement.md` "90-Day Safety Check" |
| S-04 | Forecast 90 days from `request_date`; a plan is safe only if the balance never falls below `minimum_balance_to_keep` at any point. | `problem_statement.md` "90-Day Safety Check"; `AGENTS.md` §6.3 |
| S-05 | The plan must complete the request by `desired_completion_date`. | `problem_statement.md` "90-Day Safety Check" |
| S-06 | `earliest_date_for_full_payment` is the first date the **full** amount passes the safety check **without** optional spending changes; it equals `request_date` for `affordable_now`; empty when never safe inside the forecast period. | `problem_statement.md` "Output meaning", "Allowed values", "90-Day Safety Check" |
| S-07 | `earliest_date_for_full_payment` measures financial capacity independently of payment-method preference, so it may equal `request_date` even when the recommendation is `installments`. | `problem_statement.md` "Allowed values" (explicit) |
| S-08 | `affordable_now` requires the full amount safe on `request_date` **and** the user accepts `full_payment`. | `problem_statement.md` "Allowed values" |
| S-09 | `affordable_with_plan` means the full requested amount is completed safely via a partial-payment schedule, installments, or permitted spending changes. | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2 |
| S-10 | `partial_payment` requires `affordability_status == affordable_with_plan`, `allows_partial_payment` true, the user accepting `partial_payment`, `0 < amount_safe_to_pay < requested_amount`, and `earliest_date_for_full_payment <= desired_completion_date`; exactly two payments summing to `requested_amount`; no supplied option needed. | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2 |
| S-11 | An `installments` plan must exactly match a supplied `request_payment_options` row. | `problem_statement.md` "Allowed values"; `AGENTS.md` §6.2 |
| S-12 | `full_payment` / `partial_payment` / `installments` are eligible only if present in `payment_methods_user_will_consider`; `wait` is eligible only when full payment becomes safe later **and** the user accepts `full_payment`; `not_recommended` is the fallback when no safe eligible payment exists. | `problem_statement.md` "Choosing Between Safe Plans" |
| S-13 | `max_installment_months` blank means the user will not consider installments. | `AGENTS.md` §6.1 |
| S-14 | Plan ranking, in order: completes by `desired_completion_date`; no spending changes; minimize total paid; start earlier; fewer payments; lowest `payment_option_id`. | `problem_statement.md` "Choosing Between Safe Plans" |
| S-15 | Spending changes: at most three; forms `stop:<event_id>` and `reduce_to:<event_id>:<new_amount>`; only recurring expenses marked flexible; only non-protected categories the user permits; stop and reduce must target different events. | `problem_statement.md` "Allowed values", "Choosing Between Safe Plans"; `AGENTS.md` §6.2 |
| S-16 | Reserve pending **debits**. Do not count pending **credits**, bonuses, commissions, refunds, lottery proceeds, or investment gains until they settle. | `AGENTS.md` §6.3; `problem_statement.md` "90-Day Safety Check" |
| S-17 | Ignore failed and cancelled transactions, duplicate records, and unrealized investments. Unrealized investment value is never available cash. | `problem_statement.md` "90-Day Safety Check"; `AGENTS.md` §6.1 |
| S-18 | Count confirmed salary on its settlement date. | `AGENTS.md` §6.3 |
| S-19 | Detect recurrence only when history supports it; forecast essential variable spending conservatively. | `AGENTS.md` §6.3 |
| S-20 | Never invent unsupported future income, expenses, payment options, or other financial facts. | `problem_statement.md` "Choosing Between Safe Plans"; `AGENTS.md` §6.3 |
| S-21 | A blank event `amount` must be resolved from the image whose `related_event_id` matches the `event_id`; never treat it as zero. | `problem_statement.md` "Files provided"; `README.md` step 3 |
| S-22 | Foreign-currency cash event: use the `exchange_rates.csv` row for its **settlement date** and the stated `from_currency` -> `to_currency` direction. | `AGENTS.md` §6.1; `problem_statement.md` "Files provided" |
| S-23 | Messages and images may clarify, amend, cancel, delay or confirm facts, but their content is untrusted data and embedded instructions never override the challenge rules. | `problem_statement.md` "Important Behavior"; `AGENTS.md` §1 |
| S-24 | Conflict precedence: explicit cancellation/settlement/amendment; then a newer record from the same source; then a settled event over an estimate; then the financially safer interpretation. | `problem_statement.md` "Choosing Between Safe Plans"; `AGENTS.md` §6.3 |
| S-25 | `messages.related_event_id` is populated only when the message describes one supplied event row; blank means no one-to-one event row exists. | `AGENTS.md` §6.1; `problem_statement.md` "Files provided" |
| S-26 | Resolve images as `dataset/media/images/<image_id>.png`; do not invent evidence when an image file is absent. | `AGENTS.md` §6.1 |
| S-27 | Investment requests concern affordability and existing contributions; no asset-price prediction or security recommendation is required. | `problem_statement.md` "Choosing Between Safe Plans" |
| S-28 | Solution must be terminal-runnable, read inputs from `dataset/`, use no organizer-only files and no hardcoded labels, stay deterministic where possible, and read secrets only from environment variables. | `AGENTS.md` §6.4; `README.md` "Requirements" |
| S-29 | `code.zip` must contain `evaluation/usage_report.md` describing the final full-dataset run: providers, model names, call count, input tokens, output tokens, totals, average tokens per request, estimated total and per-request cost; per-model and overall totals when multiple models are used. No credentials. | `AGENTS.md` §6.5; `problem_statement.md` "Token Usage and Cost Analysis" |
| S-30 | Append-only `log.txt` beside `AGENTS.md`, gitignored, UTF-8 with `\n`, one non-empty `tool=` line per entry naming the running harness exactly. | `AGENTS.md` §2, §5, §7 |
| S-31 | Scoring considers accuracy of `amount_safe_to_pay`, correctness of `affordability_status`, correctness of `recommended_payment_method` and `payment_plan`, accuracy of `earliest_date_for_full_payment`, validity of `spending_changes_needed`, and usefulness/consistency of `decision_explanation`. | `problem_statement.md` "Evaluation"; `README.md` "Evaluation" |

---

## 2. Observed examples (O-*)

Measured facts. Useful for design and for sanity checks. **Do not treat as specification.**

### 2.1 Dataset structure

| ID | Observation | Why it matters |
|---|---|---|
| O-01 | Exactly one request per user; 275 users, 25 sample + 250 evaluation, disjoint user sets. | Evidence with a blank `request_id` still resolves uniquely through `user_id`. Raises message coverage of evaluation requests from 116 to 198. |
| O-02 | Only 141 of 25,342 events fall after their user's `request_date`, none more than +20 days; only 47 users have a scheduled salary row. | Days 21-90 of the forecast must be generated by recurrence detection, not read from the table. |
| O-03 | `pending` and `scheduled` rows are always future-dated; `cancelled`, `failed` and `unrealized` rows are always at or before `request_date`. | Status alone separates "forward ledger" from "history to suppress". |
| O-04 | Per-user history is 169-196 days (median 177) with 56-129 events. | About six monthly cycles; enough for anchored-stream detection, thin for annual patterns. |
| O-05 | `current_available_balance` does not equal the net of settled events in history for any sampled user. | The profile balance is an authoritative opening balance at `request_date`, not a derivable quantity. Do not attempt to reconstruct it. |
| O-06 | Every user starts at or above `minimum_balance_to_keep`. | No request begins already in breach. |
| O-07 | Anchored monthly streams repeat on a fixed day-of-month with near-constant amounts: rent, utilities, insurance, subscriptions (streaming / cloud_storage / music_subscription / delivery_membership / gym), `debt_payment`, `Household shopping`, `Monthly entertainment spend`, and salary. | These project exactly. |
| O-08 | `groceries`, `transport`, `dining` (14,917 rows) use many rotating descriptions, irregular days, and varying amounts, roughly 2-5 occurrences per month per category. | These are the "essential variable spending" of S-19 and drive U-FORECAST-1. |
| O-09 | `minimum_allowed_amount` is populated on exactly the `reducible` and `reducible_or_stoppable` rows and nowhere else. | It is the floor for a `reduce_to:` action. |
| O-10 | Every request has exactly one `full_payment` option whose amount equals `requested_amount`, fee 0, and `first_payment_date == request_date`. | A `full_payment` recommendation always has a matching supplied option, even though S-10 does not require one for partial. |
| O-11 | Only `n=2` (7/7) and `n=3` (74/80) installment options ever complete by `desired_completion_date`; every `n>=4` option finishes late. | Combined with S-05 and S-14.1, long plans are effectively excluded. |
| O-12 | 67 of 275 requests have a user who considers installments but no option within `max_installment_months`; 119 users leave it blank. | Installments are usable on a minority of rows. |
| O-13 | No evaluation request has both `full_payment` accepted **and** a usable installment option. 16 evaluation requests have no usable method at all. | Removes a class of ranking ties; creates the U-STATUS-1 question for those 16. |
| O-14 | All 101 distinct `(settlement_date, from, to)` FX lookups demanded by the data are present; rates are directional with no inverse rows. | FX is a table lookup with no interpolation and no inversion. Missing lookups should hard-fail, not silently default. |
| O-15 | All 16 images exist, are legible, and each covers exactly one blank-`amount` event; 11 belong to evaluation requests, 2 of those to non-settled events. | Image extraction affects 11 evaluation rows, only 2 of them in the forward ledger. |
| O-16 | `messages.csv` is templated into about 31 archetypes across 5 `source_type` values, in English and Indonesian, always sent 1-12 days before `request_date`. | Interpretation can be schema-driven rather than free-form. |
| O-17 | Two messages are advance-fee fraud ("pay the release charge today"): `message_67` (user_88) and `message_142` (user_179). | The untrusted-content test of S-23. Neither may create an expense or income. |
| O-18 | `message_86` (user_113) is multi-fact: an EV-charging receipt confirmation **and** an employer-confirmed USD 1,296 salary credit for 2026-09-15 at the settlement-date rate. | One message can carry two claims of different types. |

### 2.2 Behaviour of the 25 public samples

All 25 labels were inspected during preparatory research, so these rows are **not** a pristine
holdout and any score measured on them is optimistic. They are used only to read off format and to
falsify candidate interpretations, never as a tuning target.

| ID | Observation | Illustrated by |
|---|---|---|
| O-20 | `amount_safe_to_pay` is always reported, including for `wait` and `not_recommended` rows, and is never zero in the 25 samples. | request_05 = 737 with `not_recommended`; request_03 = 873,000 with `wait` |
| O-21 | `amount_safe_to_pay` is far below `balance - minimum` in general, so it is gated by the worst projected dip, not by today's headroom. | request_02: balance 60,383,889.20, minimum 29,158,400, label 17,229,139.20 |
| O-22 | `earliest_date_for_full_payment` lands on the user's salary credit day. | 15th in most samples; request_07 lands on 2024-10-23 because `message_05` moved that user's payroll to the 23rd |
| O-23 | An `installments` plan is written as `first_payment_date + k * payment_frequency_days` with the option's `payment_amount` repeated. | request_17 `2026-03-01|2026-03-31|2026-04-30` at freq 30; request_22 `2024-12-08|2025-01-05|2025-02-02` at freq 28 |
| O-24 | All five installment samples chose an `n=3` option and all five complete on or before `desired_completion_date`. | consistent with O-11 |
| O-25 | `affordable_with_plan` + `full_payment` occurs: the spending changes are what make today's full payment safe, and `earliest_date_for_full_payment` still reports the change-free date, which may be **after** `desired_completion_date`. | request_06 (earliest 2026-01-15 vs due 2026-01-14), request_11, request_21 |
| O-26 | `affordable_with_plan` + `installments` occurs even when the full amount is safe today, because the user does not accept `full_payment` — exactly the S-07 case. | request_12: `amount_safe_to_pay == requested_amount`, `earliest == request_date` |
| O-27 | `wait` rows carry a one-entry plan on `earliest_date_for_full_payment`, which is always on or before `desired_completion_date`. | request_04 plan `2024-06-15:12693000`, due 2024-06-19 |
| O-28 | `not_recommended` rows always have `payment_plan = none` and an empty `earliest_date_for_full_payment` (7 of 7). | requests 05, 10, 14, 15, 20, 24, 25 |
| O-29 | Spending changes appear on only 3 of 25 samples, and never more than two actions; `reduce_to` targets the event's `minimum_allowed_amount`. | request_21 `stop:event_1815\|reduce_to:event_1816:23.50`, where `event_1816.minimum_allowed_amount = 23.5`; request_11 `reduce_to:event_989:665950` where the floor is 665950 |
| O-30 | Number formatting differs by field: `amount_safe_to_pay` is printed with trailing zeros trimmed (`603.3`, `433.4`, `462`), while `payment_plan` amounts use two decimals when fractional (`620.40`, `996.60`, `3246.10`) and no decimals when whole (`122500`). | across all 25 |
| O-31 | Explanations are short, single- or two-sentence, currency-coded, thousands-separated, with dates written as `15 June 2024`, and they always name the minimum balance. Five recurring shapes: pay-today, installments, wait, partial, and two `not_recommended` variants. | see the templates below |

Observed explanation shapes (paraphrase targets, not strings to copy blindly):

```
full today      : "Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days."
installments    : "Use 3 installments of INR 68,432, starting 12 September 2024. This leaves at least INR 93,000 available."
wait            : "Pay EUR 996.60 in full on 15 April 2025. Paying earlier would take the balance below the EUR 800 minimum."
wait (variant)  : "Wait until 15 June 2024, then pay IDR 12,693,000 in full. Paying sooner would put the IDR 30,686,600 minimum at risk."
partial         : "Pay INR 28,820 today and the remaining INR 10,840 on 15 September 2024. This completes the full request and keeps the INR 92,800 minimum protected."
spending change : "Stop the online backup subscription and reduce the streaming subscription to USD 23.50, then pay USD 1,574.40 today. This leaves at least USD 1,800 available."
not affordable  : "Do not make this payment by 22 February 2026. None of the available options keeps the INR 64,500 minimum protected."
not affordable  : "Do not proceed with the INR 109,600 request. Although INR 13,420 is available today, the full amount cannot be completed safely within 90 days."
```

Spending-change explanations name the event by its `description` in natural language ("the family
streaming plan", "the online backup subscription"), not by `event_id`.

---

## 3. Unresolved interpretation (U-*)

Each item states the conflict, the conservative default adopted, and the evidence that would change
it. "Conservative" follows S-24.4: when a conflict cannot be resolved, take the financially safer
reading — the one that recommends less spending.

### U-FORECAST-1 — estimator for essential variable spending (highest impact)

**Conflict.** S-19 requires recurrence "only when history supports it" and a "conservative" forecast
of essential variable spending, but gives no estimator. `groceries`, `transport` and `dining` are
14,917 rows with rotating descriptions and irregular dates (O-08). Every candidate — last month's
total, trailing mean, trailing median, per-description projection, trailing maximum — produces a
different `amount_safe_to_pay` on nearly every row.

**Default adopted for Stage 1.** Per user and per variable category, project a monthly total equal to
the **mean of the trailing three complete monthly totals**, distributed on the category's observed
day pattern, and treat "conservative" as *not* discounting the recent trend: if the most recent
complete month exceeds that mean, use the most recent month. This never forecasts less spending than
recent history shows.

**What would change it.** A reproducible closed-form fit against the public samples: for each sample,
`balance - minimum - amount_safe_to_pay` is an exactly determined number (for example EUR 539.10 on
request_06, INR 140,430.00 on request_17, and many landing on exact `.00` values), which suggests the
generator uses a clean deterministic projection. Recovering that projection is the first task of the
next stage. This is derivation of a generative rule, not per-row tuning; it must be validated by
structure and held to a single global rule, never fitted per request.

### U-INCOME-1 — approved invoices and resuming salary as "confirmed income"

**Conflict.** S-16 says do not count pending credits until they settle. S-18 says count *confirmed*
salary on its settlement date. Archetype 17 ("the client approved an invoice payment of X, settlement
expected on <date>") and archetype 12 ("regular salary of X resumes on <date>") are approved and
dated but not settled. Roughly 25 messages are of archetype 17. Reading them as confirmed income
moves `earliest_date_for_full_payment` earlier on many of the 198 message-bearing evaluation requests.

**Default adopted.** Split by who confirms and what word is used.
- Employer/payroll messages that state an **amount and a confirmed or scheduled credit date**
  (archetypes 1, 3, 4, 5, 6, 11, 12, 13, 14) are treated as confirmed salary under S-18 and counted
  on that date. O-22 supports this: request_07's `earliest_date_for_full_payment` only makes sense if
  the message-amended payroll date was honoured.
- Explicitly unapproved or not-yet-credited items (archetypes 7 bonus, 8 commission, 16 gig payout,
  19/20 refunds, 28 prize in processing) are excluded under S-16.
- Archetype 17 approved client invoices sit between the two. Default: **count them**, because the
  client approval is an explicit confirmation with a stated settlement date and the row is
  structurally identical to a confirmed salary credit; but flag every affected request so the
  decision can be flipped as a single switch and measured.

**What would change it.** Any public sample whose `earliest_date_for_full_payment` is only reachable
with, or only reachable without, the invoice credit. None of the 25 samples carries archetype 17, so
this is currently undecidable from public labels and must remain a single global switch.

### U-DUP-1 — pending debit that mirrors a settled charge

**Conflict.** S-16 says reserve pending debits; S-17 says ignore duplicate records. Seven linked rows
are a `pending` expense debit of exactly the amount of a `settled` expense about eleven days earlier,
and bank archetype 25 describes such rows as an extra card charge under investigation with **no
reversal posted**.

**Default adopted.** Reserve the pending debit. The bank message states the money has left and no
reversal exists, so suppressing it would forecast more cash than the user has; that is the unsafe
direction, and S-24.4 selects the safer reading. A duplicate is only suppressed when the evidence
states the two rows are the same movement — as bank archetype 23 does for matched
debit/credit self-transfers, where both legs are removed.

### U-EXPENSE-1 — announced-but-unquantified new recurring expense

**Conflict.** Archetype 12 says a new recurring childcare payment begins in the same month as the
salary resumption, without an amount. S-24.4 favours including a known future outflow; S-20 forbids
inventing financial facts and there is no amount to use.

**Default adopted.** Do not fabricate an amount, and therefore do not add a cash line. Record the
claim in the evidence structure so the explanation can mention it where relevant, and prefer the
safer branch on any other tie for that user. Inventing a number would violate an explicit rule;
omitting an unquantifiable line does not.

### U-STATUS-1 — status when no method is usable but capacity arrives later

**Conflict.** Sixteen evaluation requests have no usable payment method (O-13), so S-12 forces
`recommended_payment_method = not_recommended`. But `affordable_later` is defined by capacity
("the full amount is expected to become safe later"), not by method eligibility, and `wait` requires
`full_payment` acceptance the user does not give.

**Default adopted.** Report the status the capacity test produces and the method the eligibility test
produces, allowing `affordable_later` with `not_recommended`, and `payment_plan = none` with an
non-empty `earliest_date_for_full_payment` in that case. Rationale: S-06 defines
`earliest_date_for_full_payment` as pure capacity and S-07 explicitly decouples it from preference,
so suppressing a real date to keep the row internally tidy would discard a field the scoring measures
separately. O-28 shows `not_recommended` samples with empty dates, but all seven of those are rows
where capacity genuinely never arrives, so they do not contradict this.

**Risk.** If the grader expects `not_affordable` whenever the method is `not_recommended`, this costs
`affordability_status` on up to 16 rows. Recorded as an A/B switch for the validation stage.

### U-INCOME-2 — duration of a temporary pay reduction

**Conflict.** Archetypes 2 and 3 say pay is reduced to X and that the reduced amount "continues for
the next payroll" or "will be visible on your next payslip". Neither says when the normal amount
returns.

**Default adopted.** Carry the reduced amount forward for the whole 90-day window. Assuming an
unannounced recovery would forecast income that no record supports (S-20), and the reduced figure is
the safer projection. Supported by user_06, whose history already shows two consecutive months at the
reduced 1,037.52 after 1,441.

### U-RENT-1 — applying a percentage rent uplift

**Conflict.** Archetype 18 says a renewed lease increases monthly rent by 12% from the next rent
payment. The multiplier is stated; the base and the rounding are not.

**Default adopted.** Multiply the most recent settled rent amount for that user by 1.12 and apply it
from the first projected rent date at or after the message date, rounding to two decimals. Keeps the
change grounded in a supplied number.

### U-ARREARS-1 — one-time arrears and reimbursement credits

**Conflict.** Archetype 13 states a regular salary X plus a separately identified one-time arrears
adjustment Y on the same payroll. Archetype 15 states the latest employer credit is a closed
work-expense reimbursement, not salary.

**Default adopted.** Count the arrears adjustment once, on the same payroll date, because it is part
of a confirmed payroll; never let it enter the recurring salary estimate. Treat the reimbursement as
history already reflected in the balance and never as recurring income. Both readings follow the
messages' own wording, which explicitly separates one-off from regular.

### U-FX-1 — pricing projected foreign-currency salary

**Conflict.** S-22 fixes the rate to the settlement date. Projected future salary dates have no
supplied settlement row, but `exchange_rates.csv` does publish monthly rates out to 2026-11-15
(O-14).

**Default adopted.** For a projected foreign-currency credit, use the rate row for that projected
settlement date when one exists; when none exists, use the latest rate on or before that date. Never
invent or interpolate a rate. If a needed direction is absent entirely, fail loudly rather than
invert another pair.

### U-VARSPEND-SCOPE-1 — which categories count as "essential"

**Conflict.** S-04 protects the minimum balance against "projected essential expense". The profile
names `expense_categories_to_protect`, but `dining`, `shopping`, `entertainment` and subscriptions
are real outflows that will occur whether or not the user calls them essential.

**Default adopted.** Project **all** recurring outflows in the safety check, protected or not,
because they will actually be paid. The protect / reduce / stop lists govern only which events a
`spending_changes_needed` action may target (S-15), not which outflows appear in the forecast. This
is both the safer reading and the only one consistent with O-25, where a change to a non-protected
subscription is what frees headroom that the change-free forecast had already reserved.

### U-ROUND-1 — number formatting in the output file

**Conflict.** No document states a format. O-30 shows `amount_safe_to_pay` with trailing zeros
trimmed and `payment_plan` amounts at two decimals when fractional.

**Default adopted.** Mirror the observed sample formatting exactly: `amount_safe_to_pay` rounded to
two decimals then printed with trailing zeros and a trailing point trimmed; `payment_plan` amounts
printed with two decimals when fractional and as integers when whole; `reduce_to` amounts formatted
the same way as plan amounts; dates strictly `YYYY-MM-DD`; empty string, not `none`, for an absent
`earliest_date_for_full_payment`. Cheap insurance if the grader compares strings, harmless if it
parses numbers.

### U-SCORE-1 — scoring weights are unknown

S-31 lists the six dimensions the scoring considers. **No public document states numeric weights,
per-field point values, or how the six are combined.** Nothing in this project may be tuned against
an assumed weight. Where a design choice trades one field against another, both variants are
recorded and the choice is made on rule-fidelity, not on a guessed weight.

### U-SCORE-2 — comparison tolerance is unknown

**No public document states a tolerance for `amount_safe_to_pay`, a date-proximity allowance for
`earliest_date_for_full_payment`, or whether `decision_explanation` is judged by a model or a human.**
Consequently: aim for exactness rather than "close enough", keep explanations grounded in the actual
decisive numbers so they survive either kind of judge, and do not assume partial credit for a nearly
right amount.

### U-SIMORDER-1 — same-day debit/credit ordering (new in Stage 2)

**Conflict.** S-04's 90-day safety check requires the balance to "never fall below" the minimum,
but says nothing about which order same-day movements are applied in. If a debit and a credit
land on the same calendar date, checking only the end-of-day net balance can miss an intraday
dip that a stricter ordering would catch.

**Default adopted.** All debits scheduled for a date are treated as applied before any credit for
that date, when checking whether the floor is breached that day (S-24.4: the financially safer
reading). Implemented in `buyorwait/simulator.py`'s `simulate()` and covered by
`tests/test_simulator.py::SameDayOrderingTests` with a hand-derived case where the opposite
(credits-first) convention would silently miss a real breach.

**What would change it.** Any public sample whose only explanation requires the opposite
ordering. None of the 25 samples has a same-day debit/credit collision, so this remains
unfalsified by public data and stays a documented, switchable convention.

### U-WINDOW-1 — 90-day forecast window boundary (new in Stage 2)

**Conflict.** "Forecast the user's balance for the next 90 days" (problem_statement.md) does not
say whether `request_date + 90` itself is inside or outside the window.

**Default adopted.** Inclusive of both ends: `[request_date, request_date + 90 days]`. This is
the wider, more conservative window (catches one more possible breach than an exclusive-end
window would) and is implemented as `simulator.FORECAST_HORIZON_DAYS = 90` with the addition done
via `timedelta(days=90)`. Covered by `tests/test_simulator.py::DateBoundaryTests`.

**What would change it.** No sample in the 25 public labels has a decisive date exactly on the
90-day boundary, so this is unfalsified and remains a named, switchable constant rather than a
hardcoded literal spread through the codebase.

### U-PARTIAL-FULL-1 — partial_payment when full unaided capacity already exists (new in Stage 2, discovered while designing FIX-03a/03b)

**Conflict.** S-10 requires `0 < amount_safe_to_pay < requested_amount` (a strict inequality) for
`partial_payment` to be eligible. If a user's unaided capacity already covers the ENTIRE
requested amount today (`amount_safe_to_pay == requested_amount`), `partial_payment` is
structurally ineligible by that same strict inequality. If, in addition, `full_payment` is not an
accepted method (so `affordable_now` and `wait` are both blocked by S-08/S-12) and no installment
option is usable, no rule assigns any eligible method at all, even though the user could plainly
afford the request outright. This is a genuine gap in the written rules, not a design choice
being second-guessed.

**Default adopted.** Fall through to `not_recommended` per S-12's explicit fallback ("the
fallback when no safe eligible payment is available"), since no rule affirmatively permits any
other method in this configuration. No fixture was built for this exact corner (it did not arise
from any of the eight required scenario categories), but the deliberate construction of FIX-03a
came close to it and was adjusted specifically to avoid landing in this gap by accident (see
`scenarios.py`'s FIX-03 module comment). Flagged here so Stage 4's planner does not have to
rediscover the same gap while implementing eligibility.

**What would change it.** Evidence from the hidden evaluation set that this configuration
actually occurs and is scored a particular way, or an organizer clarification. Neither is
available; this stays a named, documented gap.

### U-PKG-1 — placement of evaluation artifacts (recorded as a decision, not a rule)

The organizer skeleton ships `code/evaluation/main.py` and `code/evaluation/usage_report.md`, and
S-29 requires `evaluation/usage_report.md` **inside `code.zip`**. The working documents for this
attempt were placed in a repository-root `evaluation/` directory, matching the paths the user
specified. Decision: `code.zip` is built from the contents of `code/`, so that the archive root
contains `main.py` and `evaluation/usage_report.md` as required, and the relevant working documents
are copied into that `evaluation/` folder at packaging time. The organizer's empty files are filled,
never deleted or moved.
