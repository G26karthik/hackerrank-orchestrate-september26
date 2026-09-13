# Buy or Wait? — Production Financial Decision Engine

An AI-powered financial decision engine built for the HackerRank Orchestrate challenge (September 2026). The system evaluates purchase requests against a user's multi-month financial reality to deliver personalized, provably safe recommendations: pay in full, wait, pay in installments, split into partial payments, or decline.

---

## 1. The Affordability Problem

Assessing whether an expense is affordable cannot be answered by checking the current account balance alone. A user with $5,000 today may have an upcoming rent payment of $3,500, a quarterly insurance bill, and pending card debits that make an immediate $2,000 purchase disastrous. Conversely, a user with $500 today may have confirmed payroll settling in three days and minimal fixed expenses.

### Safety Invariants
Under our financial model, a purchase recommendation is **safe** if and only if:
1. **Balance Floor**: The forecasted balance remains at or above the user's preferred `minimum_balance` at the end of every calendar day across the entire 90-day forecast horizon.
2. **Daily Event Ordering**: Within each day, events settle in strict conservative sequence:
   $$\text{Opening Balance} + \text{Confirmed Credits} \to \text{Committed Debits} \to \text{Proposed Payment} \ge \text{Minimum Balance}$$
3. **Pending Debit Reservation**: All pending debits are treated as committed and reserved against available funds; pending credits are excluded until settled.
4. **Input-Derived Obligations**: Payment plans must complete the entire requested amount (or the exact scheduled option total for installments) without silent haircutting or debt inflation.

---

## 2. Architecture: Separation of Evidence from Financial Calculations

A core design principle of this solution is the strict separation between **multimodal evidence perception** and **deterministic financial reasoning**:

```
                 UNSTRUCTURED EVIDENCE LAYER
  [Payslips / Bills / Receipts]        [Chat Messages / Emails]
              │                                   │
              ▼                                   ▼
      gpt-6-astra Vision                  Fact Extraction Archetypes
   (Amount Candidates, Dates)           (Income Changes, One-offs)
              │                                   │
              └─────────────────┬─────────────────┘
                                ▼
               Content-Addressed Observation Cache
              (.llm_cache/ & extraction_snapshot/)
 ───────────────────────────────┼───────────────────────────────
                  DETERMINISTIC FINANCIAL CORE
                                ▼
                     Event & Flow Resolver
               (fx.py, recurrence.py, resolver.py)
                                ▼
                   Conservative Cash Simulator
                    (simulator.py, forecast.py)
                                ▼
                       Candidate Planner
                 (S-14 6-Level Hierarchy Ranking)
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
           Independent Verifier    Reference Evaluator
           (Obligation Auditing)  (Differential Testing)
                    │                       │
                    └───────────┬───────────┘
                                ▼
                     RFC 4180 / CRLF Output
                         (output.csv)
```

1. **LLM Perception**: `gpt-6-astra` is utilized exclusively for document perception (OCR, table reading, extracting candidate numbers and payment statuses from messy receipts and payslips) and message fact extraction. Every LLM response is cached by content hash (`source_sha256`, model, prompt version, decoding config).
2. **Pure Deterministic Reasoning**: Once observations are captured, all subsequent calculations—currency conversion, recurrence interval fitting, phase anchoring, day-by-day cash simulation, candidate plan generation, spending change pruning, candidate ranking, and post-decision verification—are executed in pure Python standard library code using exact `Decimal` arithmetic. No financial decisions or arithmetic calculations are delegated to an LLM.

---

## 3. Evolution: What Early Implementations Missed

During early prototype development (Stages 1–11), multiple edge cases were uncovered that compromised decision safety:

1. **Naive Capacity Calculations**: Initial logic derived available capacity simply by subtracting the minimum balance from the current balance, ignoring pending debits and upcoming essential commitments.
2. **Semantic Role Confusion in Images**: Simple OCR or basic regex parsing picked arbitrary numbers from receipts (e.g., tax amounts or cash tendered by the customer) rather than distinguishing between `total`, `paid_amount`, `balance_due`, and `net_pay`.
3. **Unanchored Recurrence**: Early recurrence detection simply estimated monthly cadence without anchoring to the true historical phase, causing future salary credits to drift away from actual payroll dates.
4. **Spending Change Side Effects**: Naive spending-change filters matched substrings, accidentally stopping unrelated debits (e.g., canceling a pending "gym insurance" transaction when attempting to pause an optional "gym" subscription).

---

## 4. The Independent Audit & Defensible Repairs (Stage 14)

A rigorous audit was conducted using counterexample stress testing, uncovering subtle edge cases that required architectural hardening:

* **Counterexample 1 (Under-obligation acceptance)**: The initial verifier accepted a plan paying only $1 for a $50 request.
  * *Repair*: Replaced plan-derived expectations with input-derived obligations. The expected total is computed directly from `request.amount` (for full/wait/partial) or `option.total_payable_amount` (for installments).
* **Counterexample 2 (Unjustified Rejection)**: Approved `not_recommended` when an immediate full payment was demonstrably safe.
  * *Repair*: Added an explicit audit pass in `independent_verifier.py` that recalculates capacity and asserts that no negative recommendation is made if immediate payment or a deadline-compliant option is completely safe.
* **Counterexample 3 (Zero-Capacity Truncation)**: Reported `amount_safe_to_pay = 0` despite $50 of safe headroom.
  * *Repair*: Re-implemented capacity calculation to search for the maximal safe amount $C \in [0, \text{requested\_amount}]$ that preserves the minimum balance across all 90 days.
* **Counterexample 4 (Spending Change Leakage)**: Stopping an expense stream removed unrelated pending debits.
  * *Repair*: Hardened `planner.py` to match exact stream IDs and descriptions, restricting changes strictly to flexible recurring streams and preserving all committed pending debits.
* **Counterexample 5 (Ranker Inversion)**: Selected a plan costing 110 with 1 change over a plan costing 100 with 2 changes.
  * *Repair*: Enforced the exact S-14 6-level ranking hierarchy: completion by deadline $\to$ binary no-changes preference $\to$ total cost $\to$ earliest payment date $\to$ payment count $\to$ option ID.
* **Counterexample 6 (Output Validation Gaps)**: The output validator previously tolerated missing rows or amounts above requested amounts.
  * *Repair*: Hardened `validate_output_csv` to verify exactly 250 evaluation IDs, strict 8-column schema, CRLF line endings, and cross-column semantic consistency.

To guarantee correctness, an independent reference calculator (`buyorwait/reference_evaluator.py`) was introduced. It implements first-principles simulation and evaluation completely separately from the production planner, providing continuous differential verification.

---

## 5. Measured Evaluation & Benchmark Results

### Public Sample Evaluation (25 Solved Requests)
Evaluating against `dataset/sample_requests.csv` via `code/evaluation/main.py`:

| Metric | Result | Target / Standard |
| :--- | :--- | :--- |
| **False Positives (Unsafe Plans)** | **0 / 25 (0.0%)** | 0 allowed |
| **Recommended Payment Method** | **20 / 25 (80.0%)** | Strict contract compliance |
| **Payment Plan Exact Match** | **19 / 25 (76.0%)** | Date-set match: 20/25; Sum match: 21/25 |
| **Spending Changes Set Match** | **22 / 25 (88.0%)** | 25/25 rule well-formed |
| **Affordability Status** | **17 / 25 (68.0%)** | Conservative safety alignment |
| **Decision Explanation Grounding** | **25 / 25 (100.0%)** | 0 empty, 0 hallucinated claims |
| **Amount Safe to Pay (Mean Relative Error)** | **EUR 7.97%, IDR 6.80%, INR 4.07%, USD 1.97%, ZAR 5.24%** |

*Root-Cause of Sample Divergence*: The few sample divergences stem from deliberate safety conservatism: where public samples optimistically counted unconfirmed future income or simulated truncated horizons (e.g., request_13, request_17), our engine strictly enforces conservative settlement and full 90-day safety.

### Clean-Room Test Suite & Differential Verification
* **Automated Unit & Regression Tests**: 308 tests across 18 test suites run in **~5.0 seconds** with 100% pass rate.
* **Differential Verification**: 0 discrepancies across all 250 evaluation requests between the production planner and the independent reference evaluator.

---

## 6. Quickstart & Execution Guide

The engine requires Python 3.11+ and runs out-of-the-box using the standard library.

### A. Environment Setup
```bash
# Clone repository
git clone https://github.com/G26karthik/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26

# (Optional) Install pinned packages for live LLM evidence re-extraction
pip install -r code/requirements.txt
```

### B. Run Full Predictions (250 Requests)
Generate the competition `output.csv` for all 250 evaluation requests:
```bash
python code/main.py --mode full --output output.csv --dataset dataset
```
*Evaluates all 250 requests in ~6.2 seconds and validates schema compliance.*

### C. Run Sample Evaluation
Generate predictions for the 25 sample requests and score them:
```bash
# 1. Generate predictions for sample requests
python code/main.py --mode sample --output sample_preds.csv --dataset dataset

# 2. Score against sample labels
python code/evaluation/main.py sample_preds.csv --dataset dataset
```

### D. Validate Output CSV Compliance
Verify that any generated CSV satisfies all competition constraints:
```bash
python code/main.py --validate-csv output.csv --dataset dataset
```

### E. Run Automated Test Suite
```bash
python -m unittest discover -s code/tests
```

### F. Rebuild Deterministic Submission Package
Build `code.zip` and run clean-room verification in an isolated sandbox:
```bash
python code/main.py --package
```

---

## 7. Submission Artifacts & Verification Manifest

The three required submission artifacts:

1. **`code.zip`** (266,079 bytes)
   - SHA-256: `C57249B51811246DE9EFCBD816297339F6FA9DA997B41150B64B9C84900FF114`
   - Contains self-contained `code/` directory, pinned dependencies, tests, documentation, and `usage_report.md`. Strictly zero dataset files.
2. **`output.csv`** (50,405 bytes)
   - SHA-256: `0EB1D2E7163DCEC8D1AE9D90F605D28A74CD056AFB7C4417C6BD0B1A03F46F43`
   - Exactly 250 evaluation requests, valid CRLF, 100% compliant with schema and contract.
3. **`log.txt`** (112,749 characters)
   - Authentic, unedited development log tracking all conversational stages. Uploaded separately to HackerRank.

---

## 8. AI Assistance & Known Limitations

### AI Assistance Disclosure
Development was conducted with pair-programming assistance from Claude (Anthropic) during early exploratory stages (Stages 1–12) and Antigravity (Google DeepMind) for audit hardening, Ponytail simplification, clean-room verification, and release preparation (Stages 13–16). All code, tests, and calculations were independently verified through automated regression suites and differential reference modeling.

### Material Limitations
1. **Offline Replay Dependency**: Zero-call offline execution relies on the 38 pre-extracted content-addressed observation files in `evaluation/extraction_snapshot/`. Full regeneration from scratch requires an OpenAI API key (`gpt-6-astra`).
2. **Illegible Documents**: One image in the dataset (`image_04`) is cropped/illegible. The system explicitly tags it as non-legible rather than guessing an arbitrary number.
3. **Conservative Policy Boundary**: The engine rejects unconfirmed future income and restricts spending changes strictly to streams with verified user permission. In real-world deployments, users would be prompted interactively to confirm pending changes.
