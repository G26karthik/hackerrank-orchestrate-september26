# Interview Brief: Technical Architecture, Empirical Decisions, and Case Walkthroughs

**Project**: Buy or Wait? AI-Powered Financial Affordability Agent  
**Context**: HackerRank Orchestrate (September 2026)  
**Configuration**: `exp2_terminate` (`gpt-6-astra`, reasoning=high for development extractions; pure deterministic execution for forward evaluation)  
**Output Reference**: Root `output.csv` (250 rows, SHA-256: `7B0A3120B6DC18883D7442ADCF7025A8CE04A861173ED1E8BA30115DEE0293A0`)  

---

## 1. Executive Architectural Principles

This section provides clear, defensible explanations of core system design decisions for use in technical evaluations.

### 1.1 Why the Opening Balance Is Never Reconstructed by Replaying History
* **Design Decision**: `current_available_balance` from `financial_profiles.csv` is accepted directly as the verified opening cash snapshot as of `request_date`.
* **Financial Rationale**: Historical events in `financial_events.csv` span months or years prior to the request. In real-world retail banking, transaction histories are frequently incomplete (e.g., untracked cash withdrawals, point-of-sale holds, off-platform transfers, micro-fees). Attempting to compute opening balance by summing past events is an error-prone anti-pattern that creates cumulative drift.
* **Double-Counting Prevention (S-03 / S-04)**: Past settled cash credits have already cleared into the bank account and are already sitting inside `current_available_balance`. If historical settled transactions are re-applied into the forward simulation, cash is double-counted. Historical events exist exclusively to infer recurrence periodicity (interval, day of month) and estimate trailing variable spend baselines (S-19).

### 1.2 Confirmed Future Salary vs. Pending Credits
* **Confirmed Future Salary (S-18)**: Contractually guaranteed ongoing employment payroll verified either by historical regularity ($\ge 2$ consecutive paychecks with $\le 3$ days standard deviation) or by an explicit employer communication establishing employment start, amount, and credit date (S-24). It is reliably projected forward across the 90-day horizon on scheduled payday intervals.
* **Pending Credits (S-16)**: Incoming merchant refunds, bonus promises, prize winnings, or affiliate commissions marked `pending`. Under the conservative safety rule (S-24.4), pending credits cannot be treated as available cash until their settlement date has arrived. Pending transactions can be cancelled, reversed, delayed, or disputed. Counting pending credits before settlement risks advising a user to spend non-existent funds.

### 1.3 Recurring Income vs. Arrears
* **Recurring Income**: A stable ongoing cash flow that recurs on an established cycle (bi-weekly, monthly).
* **Arrears / Retroactive Adjustments**: A one-time catch-up disbursement (e.g., delayed back-pay, insurance settlement, tax refund). While arrears may appear as a large credit in transaction logs or messages, they do not repeat. Treating arrears as recurring income artificially inflates 90-day forecast liquidity, leading to false affordability approvals. The resolver isolates and marks arrears as non-recurring.

### 1.4 Why Preferences Cannot Alter Baseline Capacity
* **Mathematical Invariant**: Baseline capacity (`amount_safe_to_pay`) is an objective physical measurement of the user's cash trajectory. It represents the maximum cash that could exit the account on `request_date` such that the daily cash balance never breaches `minimum_balance_to_keep` over the next 90 days, after reserving all pending debits.
* **Role of Preferences**: Whether the user prefers installments, dislikes partial payments, or refuses full payment does not alter their true bank balance or financial headroom. Preferences act strictly as candidate filters in the recommendation planner (`planner.py`). Metamorphic Property 4 verifies this invariance: mutating `payment_methods_user_will_consider` strictly preserves `amount_safe_to_pay`.

### 1.5 The Bounded Role of the Runtime LLM
* **What the LLM Does**: The LLM (`gpt-6-astra`) operates strictly as an unstructured-to-structured extraction engine. It reads invoice/receipt images (multimodal vision) and ambiguous user/employer messages, emitting typed JSON facts (`image_observation` and `evidence_fact`).
* **What the LLM NEVER Does**: The LLM does not perform math, does not forecast balances, does not evaluate candidates, does not rank payment options, and does not select the recommended payment method. All financial logic, simulation, candidate enumeration, and rule validation are executed in pure, deterministic, typed Python code.

### 1.6 Independent Verifier vs. Recommendation Planner
* **The Planner (`planner.py`)**: A generative optimizer. It generates combinatorial candidates across payment options and permitted spending adjustments (up to the 3-change cap), ranks them by preference hierarchy (full payment $\succ$ installments $\succ$ partial payment $\succ$ wait), and picks the best feasible candidate.
* **The Independent Verifier (`independent_verifier.py`)**: An adversarial auditor. It has no access to candidate ranking or heuristics. It takes the proposed plan and re-simulates the cash flow from scratch using only the pure reference simulator (`simulator.py`). It independently validates 6 orthogonal invariants:
  1. Arithmetic: Plan installments sum exactly to the requested or payable amount.
  2. Chronology: Payment dates are strictly ascending.
  3. Deadline: Every payment occurs on or before `desired_completion_date`.
  4. Safety: No daily balance breaches `minimum_balance_to_keep` across the 90-day horizon.
  5. Eligibility: Recommended method is explicitly listed in profile preferences and available options.
  6. Grounding: Explanation text accurately matches the status and dates.
  If any check fails, the candidate is rejected and the system falls back to `not_recommended`.

### 1.7 Cache Lineage and Zero-Cost Replay
* **Lineage Key**: Every extraction cache entry in `.llm_cache/` is content-addressed by SHA-256 hash of: `source_content`, `model`, `prompt_version`, `schema_version`, `decoding_config`, and `tool_contract_version`.
* **Development vs. Production**: During development, 47 calls were made (10 fresh API calls, 37 cache hits), consuming 17,632 tokens ($0.0767 USD). For production evaluation and cold replay, all 38 necessary extraction artifacts are bundled in `evaluation/extraction_snapshot/`. At runtime, the pipeline operates with 100% cache hits, requiring 0 live API calls and 0 additional cost ($0.00 USD), while delivering bitwise-identical output.

---

## 2. Eight Source-Grounded Case Walkthroughs

Every case below is extracted directly from the verified production pipeline execution across `requests.csv`, `financial_events.csv`, `messages.csv`, and `images.csv`.

```
+---------------------------------------------------------------------------------------------------+
| SUMMARY MATRIX OF THE EIGHT REAL CASES                                                            |
+---------+------------+----------+---------------------+-------------------+-----------------------+
| Case #  | Request ID | User ID  | Category            | Recommended Method| Financial Mechanism   |
+---------+------------+----------+---------------------+-------------------+-----------------------+
| Case 1  | request_33 | user_33  | Image Extraction    | not_recommended   | Invoice total via OCR |
| Case 2  | request_32 | user_32  | Salary Amendment    | wait              | Wage increase applied |
| Case 3  | request_29 | user_29  | Employment Ending   | not_recommended   | Income stream ends    |
| Case 4  | request_55 | user_55  | Failed-Debit Retry  | installments      | Retry reserved + stop |
| Case 5  | request_35 | user_35  | Unsettled Refund    | wait              | Pending credit dropped|
| Case 6  | request_274| user_274 | FX Settlement       | installments      | USD->EUR on date      |
| Case 7  | request_30 | user_30  | Preference Override | installments      | Cash ok, pref governs |
| Case 8  | request_46 | user_46  | Partial Payment     | partial_payment   | Split across paydays  |
+---------+------------+----------+---------------------+-------------------+-----------------------+
```

---

### Case 1: Image-Derived Invoice Extraction (`request_33` / `user_33`)
* **Source Identifiers**: `request_id=request_33`, `user_id=user_33`, `related_event_id=event_3051`, `image_id=image_06.png`.
* **Input State**: Request date `2026-01-07`, desired deadline `2026-03-15`, requested amount INR 118,000, allows partial: `False`. Opening available balance INR 167,280, minimum balance floor INR 102,100.
* **Accepted Interpretation**: `image_06.png` contains an invoice for `event_3051` ("Building maintenance payment"). Multimodal vision extraction confirmed `legible=True`, extracting invoice `Total = 3806 INR` (preferred over line-item subtotals per S-21).
* **Forecast Assumptions**: Recurring living expenses (rent, utilities, groceries) continue along established cadences. User accepts `full_payment` and `partial_payment`.
* **Minimum Balance & Binding Date**: The user's baseline minimum balance reaches **INR 130,187.09** on **2026-01-14** (Day +7), leaving safe headroom of only **INR 28,087.09**.
* **Rejected Candidates**:
  - `full_payment` on `2026-01-07`: Breaches the minimum floor on 2026-01-14 by a shortfall of INR 89,912.91.
  - `installments` (Payment Option 92): Offers 18 payments of INR 7,473.33; rejected because completion date (July 2027) extends far beyond the desired deadline `2026-03-15` (S-05).
  - Spending reduction combinations (up to 3 changes): Insufficient to close the ~INR 90,000 deficit before the deadline.
* **Chosen Schedule**: `payment_plan=none`, `spending_changes_needed=none`, `status=not_affordable`, `method=not_recommended`.
* **Limitation**: The user has sufficient cash today (INR 167,280 > INR 118,000) for an instantaneous debit, but doing so would cause an unavoidable floor breach 7 days later when regular bills clear.

---

### Case 2: Salary Amendment via Employer Message (`request_32` / `user_32`)
* **Source Identifiers**: `request_id=request_32`, `user_id=user_32`, `message_id=message_22`.
* **Input State**: Request date `2025-02-05`, desired deadline `2025-03-24`, requested amount ZAR 40,018, allows partial: `False`. Opening available balance ZAR 69,005.80, minimum balance floor ZAR 35,700.
* **Accepted Interpretation**: `message_22` from employer BrightPath Media states: *"Your first salary will be ZAR 54120. The confirmed credit date is 2025-02-15."* S-24 precedence level 1 overrides historical salary projections with ZAR 54,120 starting 2025-02-15.
* **Forecast Assumptions**: The amended payroll credit of ZAR 54,120 lands on 2025-02-15; same-day credits-first rule (U-SIMORDER-1) applies on payday.
* **Minimum Balance & Binding Date**: On request date, safe headroom is **ZAR 14,582.18** with a binding date of **2025-02-12** (Day +7). Immediate payment of ZAR 40,018 would trigger an opening breach.
* **Rejected Candidates**:
  - Immediate `full_payment` on `2025-02-05`: Rejected due to ZAR 25,435.82 breach on 2025-02-12.
  - Spending reductions on day 0: Cannot safely bridge the gap before 2025-02-12.
* **Chosen Schedule**: `status=affordable_later`, `method=wait`, `payment_plan=2025-02-15:40018`, `spending_changes_needed=none`.
* **Limitation**: Assumes the employer's confirmed first salary date is adhered to without payroll delay.

---

### Case 3: Contract Employment Termination (`request_29` / `user_29`)
* **Source Identifiers**: `request_id=request_29`, `user_id=user_29`, `message_id=message_21`.
* **Input State**: Request date `2025-11-04`, desired deadline `2025-11-23`, requested amount ZAR 51,524, allows partial: `False`. Opening available balance ZAR 113,540.10, minimum balance floor ZAR 28,300.
* **Accepted Interpretation**: `message_21` from Riverline Retail: *"The current seasonal contract has ended. No off-season pay is scheduled."* S-24 precedence sets `income_ended=True`, terminating all recurring salary inflows across the 90-day window.
* **Forecast Assumptions**: Outflows (rent, utilities, healthcare, food) continue unabated with zero salary replenishments.
* **Minimum Balance & Binding Date**: The baseline minimum balance collapses to **ZAR 29,371.10** on **2026-01-27** (Day +84), leaving a total 90-day headroom of only **ZAR 1,071.10**.
* **Rejected Candidates**:
  - `full_payment` on `2025-11-04`: Leaves account vulnerable, breaching floor on 2025-12-07 by shortfall ZAR 225.53, worsening to a massive deficit by January 2026.
  - `installments` (Payment Option 82): 15 payments of ZAR 3,778.43; rejected because it extends past deadline and still breaches in month 2.
* **Chosen Schedule**: `status=not_affordable`, `method=not_recommended`, `payment_plan=none`, `spending_changes_needed=none`.
* **Limitation**: A model looking only at the opening balance (ZAR 113,540 vs request of ZAR 51,524) would falsely approve this request; only 90-day forward cash-flow modeling with salary termination detects the deferred insolvency.

---

### Case 4: Failed Debit Followed by Scheduled Retry (`request_55` / `user_55`)
* **Source Identifiers**: `request_id=request_55`, `user_id=user_55`, `event_id=event_5169`, `image_id=image_09.png`.
* **Input State**: Request date `2026-06-08`, desired deadline `2026-08-22`, requested amount INR 218,600, allows partial: `False`. Opening balance INR 314,341.19, minimum floor INR 124,300. User considers `installments` and `partial_payment` (max 11 months).
* **Accepted Interpretation**: `event_5169` is a "Scheduled bill payment retry" (status `scheduled` on 2026-06-11). An earlier debit attempt failed. Under S-17, the failed record is dropped, and under S-18, the scheduled retry is reserved as an explicit future liability.
* **Forecast Assumptions**: Payment Option 151 (3 monthly installments of INR 75,781.33) is evaluated.
* **Minimum Balance & Binding Date**: Baseline minimum headroom is **INR 134,746.67** on **2026-06-14**. Under Option 151, the third installment on 2026-08-12 creates a shortfall of **INR 6,149.02** on **2026-08-14**.
* **Rejected Candidates**:
  - Zero-change `installments`: Breaches floor on 2026-08-14 by INR 6,149.02.
* **Chosen Schedule**: `status=affordable_with_plan`, `method=installments`, `payment_plan=2026-06-11:75781.33|2026-07-12:75781.33|2026-08-12:75781.33`, `spending_changes_needed=stop:event_5101`. Stopping non-essential delivery membership `event_5101` saves enough cumulative cash to keep the account safely above the INR 124,300 floor.
* **Limitation**: Requires active user cooperation to cancel the delivery subscription.

---

### Case 5: Unsettled Refund Excluded from Liquidity (`request_35` / `user_35`)
* **Source Identifiers**: `request_id=request_35`, `user_id=user_35`, `event_id=event_3230`, `message_id=message_25`, `image_id=image_07.png`.
* **Input State**: Request date `2025-10-30`, desired deadline `2026-01-15`, requested amount INR 212,000, allows partial: `False`. Available balance INR 231,530, floor INR 106,400. Preference: `full_payment`.
* **Accepted Interpretation**: `event_3230` is a "Pending merchant refund" of INR 8,528. `message_25` notes the refund was initiated but has not cleared. Per rule S-16, pending refunds are strictly excluded from available cash.
* **Forecast Assumptions**: User's monthly salary of INR 162,000 clears on the 15th of each month.
* **Minimum Balance & Binding Date**: Current safe headroom is **INR 33,052.98** (binding date **2025-11-13**). Immediate payment of INR 212,000 creates an immediate shortfall of INR 86,870 below the floor.
* **Rejected Candidates**:
  - Immediate `full_payment` on `2025-10-30`: Severe floor breach.
  - Credit counting: If the INR 8,528 pending refund were mistakenly treated as cash, safe headroom would still be insufficient.
* **Chosen Schedule**: `status=affordable_later`, `method=wait`, `payment_plan=2026-01-15:212000`, `spending_changes_needed=none`. On 2026-01-15, cumulative confirmed salary credits make full payment safe on the exact deadline.
* **Limitation**: The user must delay the purchase by 77 days.

---

### Case 6: Cross-Border FX Settlement (`request_274` / `user_274`)
* **Source Identifiers**: `request_id=request_274`, `user_id=user_274`, `event_id=event_25151`, `event_id=event_25159`.
* **Input State**: Request date `2024-12-04`, desired deadline `2025-02-11`, requested amount EUR 2,713.70, allows partial: `False`. Available balance EUR 4,847.31, floor EUR 1,800. Preferences: `installments`, `partial_payment` (max 4 months).
* **Accepted Interpretation**: User 274 lives in a EUR home-currency jurisdiction but receives monthly payroll from a US employer in USD (`event_25151`, `event_25159`, USD 3,200).
* **Forecast Assumptions**: Per rule S-22, foreign income is converted using the exact dated rate from `exchange_rates.csv` on the specific settlement date (`from_currency=USD, to_currency=EUR`). No rate inversion or linear interpolation is permitted.
* **Minimum Balance & Binding Date**: Baseline minimum headroom is **EUR 2,325.30** on **2024-12-13**. Under 3-installment Option 785 (EUR 940.75 per month), the third payment on 2025-02-04 triggers a minor breach of **EUR 65.57** on **2025-02-13**.
* **Rejected Candidates**:
  - Zero-change `installments`: Breaches floor by EUR 65.57.
  - `full_payment`: Excluded from user preferences.
* **Chosen Schedule**: `status=affordable_with_plan`, `method=installments`, `payment_plan=2024-12-04:940.75|2025-01-04:940.75|2025-02-04:940.75`, `spending_changes_needed=stop:event_25180`. Stopping subscription `event_25180` maintains positive headroom.
* **Limitation**: Exposure to currency volatility between forecast date and future settlement dates is governed by static historical table rates.

---

### Case 7: Installment Preference Overriding Available Cash (`request_30` / `user_30`)
* **Source Identifiers**: `request_id=request_30`, `user_id=user_30`.
* **Input State**: Request date `2026-04-06`, desired deadline `2026-06-06`, requested amount USD 775.20, allows partial: `False`. Available balance USD 3,752.72, minimum balance floor USD 900.
* **Accepted Interpretation**: User's baseline headroom is **USD 2,476.52** on **2026-06-03**. The user possesses sufficient cash today to pay USD 775.20 in full without ever breaching the floor.
* **Forecast Assumptions**: Profile explicitly specifies `payment_methods_user_will_consider = {'installments', 'partial_payment'}`. Full payment is intentionally excluded by user preference.
* **Minimum Balance & Binding Date**: Baseline minimum balance USD 3,376.52 vs USD 900 floor. `amount_safe_to_pay` is correctly calculated as **USD 775.20** (capacity is independent of preferences).
* **Rejected Candidates**:
  - `full_payment`: Mathematically safe, but rejected because it violates profile preference constraints (S-06).
* **Chosen Schedule**: `status=affordable_with_plan`, `method=installments`, `payment_plan=2026-04-06:268.74|2026-05-06:268.74|2026-06-05:268.74`, `spending_changes_needed=none`. Option 83 (3 installments of USD 268.74, total payable USD 806.22) is selected.
* **Limitation**: The user incurs a financing fee of USD 31.02 ($806.22 - 775.20$) to satisfy their installment preference despite having adequate cash.

---

### Case 8: Partial Payment Across Salary Cycles (`request_46` / `user_46`)
* **Source Identifiers**: `request_id=request_46`, `user_id=user_46`.
* **Input State**: Request date `2024-12-03`, desired deadline `2025-01-09`, requested amount INR 49,450, `allows_partial_payment=True`. Available balance INR 202,335, floor INR 84,000. Preferences: `installments`, `partial_payment` (max 7 months).
* **Accepted Interpretation**: Baseline minimum balance is INR 124,101.86 on binding date 2024-12-13, establishing `amount_safe_to_pay = 40101.86 INR`. The user has a shortfall of INR 9,348.14 for full payment today.
* **Forecast Assumptions**: Confirmed salary lands on 2024-12-15.
* **Minimum Balance & Binding Date**: The safe initial payment is **INR 40,101.86** on **2024-12-03**.
* **Rejected Candidates**:
  - `installments` (Option 125 & 126): Option 125 has 2 payments but its second payment occurs on 2025-02-04, breaching desired deadline 2025-01-09. Option 126 completes in March 2025.
  - `full_payment`: Excluded by preferences and cash capacity.
* **Chosen Schedule**: `status=affordable_with_plan`, `method=partial_payment`, `payment_plan=2024-12-03:40101.86|2024-12-15:9348.14`, `spending_changes_needed=none`. Per S-10, pay safe amount (INR 40,101.86) today, and remainder (INR 9,348.14) on the first payday (2024-12-15) prior to the deadline.
* **Limitation**: Two-payment partial splits are only valid when `allows_partial_payment=True` and the second payment date precedes the requested deadline.

---

## 3. Empirical Decisions: Rejected Experiment, Retained Tradeoff, and Limitations

### 3.1 Genuinely Rejected Experiment: `exp3_variable`
* **Hypothesis**: In `code/buyorwait/variable_spend.py`, front-load trailing variable spending estimates entirely onto day 0 (anchor date) rather than disbursing them uniformly across weekly buckets, under the theory that pre-payday liquidity dips occur immediately.
* **Evaluation Result (over 25 public samples)**:
  - `affordability_status`: 18/25 (72.0%) — stagnant vs. `exp2_terminate`.
  - `recommended_payment_method`: 21/25 (84.0%) — stagnant.
  - Currency error degradation: Relative errors on EUR, IDR, and USD worsened because day-0 front-loading assumed users spend their entire month's variable budget instantaneously on day 0, penalizing users whose expenses had not yet occurred.
* **Rejection Rationale**: Rejected per project workflow rules: *"Reject experiments that only improve a local metric through unsupported assumptions."* The codebase retained uniform weekly variable spending disbursement.

### 3.2 Retained Engineering Tradeoff: `exp1_simorder` (`credits_first`)
* **Tradeoff Mechanism**: When a salary credit and recurring debits share the exact same calendar date, the simulator applies credits first before checking the minimum balance floor (`credits_first=True`).
* **Justification**: Standard retail banking direct deposits post during early morning clearing (00:01 AM batch processing), providing intraday liquidity for scheduled bill payments. Adopting `credits_first` improved sample accuracy significantly:
  - `recommended_payment_method`: 16/25 (64.0%) $\rightarrow$ 20/25 (80.0%).
  - `earliest_date_for_full_payment`: 8/25 (32.0%) $\rightarrow$ 15/25 (60.0%).
* **Known Risk**: If a bank processes debit sweeps prior to payroll deposits on same-day transactions, an intraday overdraft could theoretically occur. This tradeoff is explicitly documented in `evaluation/assumptions.md` (U-SIMORDER-1).

### 3.3 Unresolved Production Limitations
1. **Multimodal Boundary Cropping (`image_04` / `event_1700`)**: `image_04.png` suffers from severe lower-boundary cropping where net invoice totals are clipped. The vision harness correctly flags `legible=False, needs_review=True`. In production, unresolved facts trigger the conservative fallback (S-24.4) rather than guessing numbers.
2. **LLM Temperature/Seed Non-Determinism (U-LLM-DETERMINISM-1)**: The OpenAI `gpt-6-astra` model does not support `temperature=0.0` or deterministic `seed` parameters. A live, un-cached run will exhibit slight extraction variance. Offline replay from the shipped `extraction_snapshot/` is required for bitwise reproducible verification.

---

## 4. Likely Technical Interview Questions & Answer Notes

> [!IMPORTANT]
> **Source Code Familiarity Required**: Review `code/buyorwait/forecast.py` and `code/buyorwait/independent_verifier.py` before discussing capacity formulas and replay gates.

#### Q1: "How do you ensure spending reductions aren't applied to essential expenses like rent or child support?"
* **Answer**: We enforce strict schema-level domain separation between `ExpenseCategory` (16 categories) and `PriorityCategory` (8 categories). In `code/buyorwait/planner.py`, `find_flexible_streams()` enforces three filtering layers:
  1. The event must have `flexibility` in `{'stoppable', 'reducible', 'reducible_or_stoppable'}`.
  2. The category must be explicitly listed in `financial_profiles.csv` under `expense_categories_user_is_willing_to_reduce` or `stop`.
  3. The category must NOT exist in `expense_categories_to_protect`.
  Essential categories like `rent`, `housing`, and `healthcare` are never marked stoppable, and reductions are hard-floored at `minimum_allowed_amount`.

#### Q2: "What prevents the combinatorial spending changes from causing an exponential search explosion?"
* **Answer**: Rule S-15 limits changes to a maximum of 3. In `planner.py`, we identify at most 4 candidate flexible streams per user. The search space is bounded by $\sum_{k=0}^3 \binom{4}{k} = 1 + 4 + 6 + 4 = 15$ combinations per payment option. Across 3 payment options, the planner evaluates at most 45 candidates, completing in under 35 milliseconds per request.

#### Q3: "How does the system handle leap years and calendar edge cases in the 90-day window?"
* **Answer**: We use Python standard library `datetime.date` and `relativedelta`-equivalent date stepping. A debit scheduled for the 31st automatically shifts to the 28th/29th in February and the 30th in April/June/September/November. `tests/test_financial_stress.py` explicitly tests Feb 29 leap-day debits and horizon boundary day +90 inclusive simulation.

#### Q4: "If the LLM vision model hallucinates an invoice amount, how does the system catch it?"
* **Answer**: The vision extraction harness uses strict JSON schema validation (`buyorwait/evidence.py`). The extracted amount is checked for currency match, positivity, and reasonable bounds relative to the user's transaction history. Furthermore, if an extraction fails schema parsing or emits `legible=False`, rule S-24.4 defaults to the safer interpretation (rejecting the plan or requesting manual review).

#### Q5: "Why did you build an independent verifier instead of just trusting the planner?"
* **Answer**: Separation of concerns. The planner is complex and heuristic—it sorts, filters, and combines options. Complex heuristics can introduce subtle edge-case bugs. The independent verifier is a 100-line deterministic gatekeeper that knows nothing about heuristics; it simply simulates the candidate schedule against the cash flow. If a single cent dips below the floor on any of the 90 days, it immediately vetos the plan.
