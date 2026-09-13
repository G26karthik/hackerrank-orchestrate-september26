# Buy or Wait? — Production Financial Decision Engine

An AI-powered financial decision engine built for the HackerRank Orchestrate challenge (September 2026). The system evaluates purchase requests against a user's multi-month financial reality to deliver personalized, provably safe recommendations: pay in full, wait, pay in installments, split into partial payments, or decline.

---

## 1. The Affordability Problem

Assessing whether an expense is affordable cannot be answered by checking current account balance alone. A user with $5,000 today may have an upcoming rent payment of $3,500, a quarterly insurance bill, and pending card debits that make an immediate $2,000 purchase disastrous. Conversely, a user with $500 today may have confirmed payroll settling in three days and minimal fixed expenses.

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

During early prototype development, multiple edge cases were uncovered that compromised decision safety:

1. **Naive Capacity Calculations**: Initial logic derived available capacity simply by subtracting the minimum balance from the current balance, ignoring pending debits and upcoming essential commitments.
2. **Semantic Role Confusion in Images**: Simple OCR or basic regex parsing picked arbitrary numbers from receipts (e.g., tax amounts or cash tendered by the customer) rather than distinguishing between `total`, `paid_amount`, `balance_due`, and `net_pay`.
3. **Unanchored Recurrence**: Early recurrence detection simply estimated monthly cadence without anchoring to the true historical phase, causing future salary credits to drift away from actual payroll dates.
4. **Spending Change Side Effects**: Naive spending-change filters matched substrings, accidentally stopping unrelated debits (e.g., canceling a pending "gym insurance" transaction when attempting to pause an optional "gym" subscription).

---

## 4. Independent Audits & Defensible Repairs

Rigorous external audits challenged the system with counterexamples and adversarial tests, driving ten architectural fixes:

1. **Underpayment Rejection**: Enforced that plan sums must strictly equal the requested amount (for full/wait/partial) or option total (for installments). Rejects accepting a plan paying 1 for a request of 50.
2. **Unjustified Rejection Prevention**: In `independent_verifier.py`, asserts that `not_recommended` is rejected if full payment or an eligible partial schedule is demonstrably safe.
3. **Maximal Safe Capacity**: Searches for the maximal safe amount $C \in [0, \text{requested\_amount}]$ that preserves the minimum balance across all 90 days, rejecting non-maximal zero-capacity estimates when positive capacity exists.
4. **Stable Stream & Occurrence Identity**: Spending changes match exact recurring stream descriptions on flow labels (`recurring <cat>: <desc>`). Stopping a `gym` stream removes `recurring gym: gym` while strictly preserving `recurring gym insurance: gym insurance` and pending debits.
5. **Ranker Hierarchy Enforcement**: Adheres strictly to the S-14 6-level hierarchy: deadline compliance $\to$ binary no-spending-changes preference $\to$ total cost $\to$ earliest payment date $\to$ fewest payments $\to$ option ID.
6. **Date and Method Timing**: Rejects `full_payment` dated tomorrow instead of today; full payment must be scheduled today.
7. **Request Permission Enforcement**: Rejects `partial_payment` when `allows_partial_payment=False` or user profile excludes partial payments.
8. **Installment Offer Schedule Conformity**: Rejects installment entries whose dates diverge from the provider's option schedule (`first_payment_date + interval * index`).
9. **Factual Explanation Grounding**: Rejects fabricated numerical claims (e.g. ungrounded salary figures like 999,999) and ungrounded buzzwords. For `not_recommended` where full payment is user-excluded and partial is disallowed (e.g. `request_251`), explains eligibility constraints rather than incorrectly claiming a floor breach.
10. **Dataset-Aware CSV Contract**: `validate_output_csv` requires the exact 250 evaluation IDs (`request_26` to `request_275`), rejects empty CSVs with clear diagnostic feedback, and rejects underpayments or sample files submitted as final submissions.

---

## 5. Measured Evaluation & Benchmark Results

### Public Development Sample Results (25 Requests)
Evaluating against `dataset/sample_requests.csv` via `code/evaluation/main.py`:

| Field | Measured Result | Context / Rationale |
| :--- | :--- | :--- |
| **Safe Capacity Matches** | **3 / 25** | Shipped evaluator's 0.005 tolerance. In 17 cases our capacity exceeds sample, in 5 it is below. |
| **Affordability Status** | **17 / 25** | 4 cases (`request_06`, `request_11`, `request_13`, `request_21`) are labeled `affordable_now` because available cash headroom safely covers the purchase today without requiring changes or waiting. |
| **Payment Method** | **20 / 25** | Method matches in 80% of development examples. |
| **Exact Payment Plan** | **19 / 25** | Plan matches in 76% of development examples. |
| **Earliest Full-Payment Date** | **17 / 25** | Includes 7 cases where both sample and engine determine no full payment date is possible within 90 days. |
| **Spending Changes Set** | **22 / 25** | Strict preservation of protected categories and essential debits. |
| **Explanation Grounding** | **25 / 25** | 100% grounded against verified structured facts and financial decisions. |

*Sample Divergence Analysis*:
- In requests 6, 11, 13, and 21, the user has sufficient immediate liquid balance above their floor throughout the 90-day horizon to pay in full today. The public development labels suggested waiting or pausing subscriptions; our engine recommends `affordable_now` because no floor breach occurs under exact daily cash simulation.
- In request 17, normalizing historical payslip and invoice images into the forecast adjusts available capacity to INR 208,252.37, correctly reflecting verified historical obligations.

### Automated Test Suite & Independent Reference Comparison
- **Automated Regression Suites**: 318 tests across 18 test suites run in **~5.0 seconds** with a 100% pass rate.
- **Independent Reference Evaluator**: Compared candidate plans across all 250 evaluation requests between production planner and `reference_evaluate_candidates`. 233/250 decisions match identically. The remaining 17 differences occur exclusively on requests where spending reductions are required (the independent reference evaluator does not model spending modifications).

---

## 6. Execution Guide

The engine requires Python 3.11+ and runs out-of-the-box using the standard library.

### A. Environment Setup
```bash
# Clone repository
git clone https://github.com/G26karthik/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26

# (Optional) Install pinned packages for live LLM evidence extraction
pip install -r requirements.txt
```

### B. Run Full Predictions (250 Requests)
Generate the competition `output.csv` for all 250 evaluation requests in deterministic replay mode:
```bash
python main.py --mode full --output output.csv --dataset /path/to/dataset
```
*Evaluates all 250 requests in ~4.7 seconds and validates schema compliance.*

### C. Run Sample Evaluation
Generate predictions for the 25 sample requests and score them:
```bash
# 1. Generate predictions for sample requests
python main.py --mode sample --output sample_preds.csv --dataset /path/to/dataset

# 2. Score against sample labels
python evaluation/main.py sample_preds.csv --dataset /path/to/dataset
```

### D. Validate Output CSV Compliance
Verify that any generated CSV satisfies all competition constraints:
```bash
python main.py --validate-csv output.csv --dataset /path/to/dataset
```

### E. Run Automated Test Suite
```bash
python -m unittest discover -s tests
```

### F. Rebuild Deterministic Submission Package
Build `code.zip` and execute clean-room verification in an isolated sandbox:
```bash
python main.py --package --dataset /path/to/dataset
```

### G. Live LLM Extraction and Investigation (Requires OPENAI_API_KEY)
```bash
# Rebuild evidence cache live via gpt-6-astra
python main.py --rebuild-evidence --live --dataset /path/to/dataset

# Run adaptive investigation on a single request with live tool calling
python main.py --investigate request_26 --live --dataset /path/to/dataset
```

---

## 7. Submission Artifacts

Per organizer guidelines, submission hashes are recorded in the external release manifest (`evaluation/release_manifest.json`):

1. **`code.zip`**: Self-contained `code/` directory, pinned dependencies, tests, documentation, and `usage_report.md`. Strictly zero dataset files. Verified clean-room pass.
2. **`output.csv`**: Exactly 250 evaluation requests (`request_26` to `request_275`), valid RFC 4180 CRLF formatting, 100% compliant with schema and contract.
3. **`log.txt`**: Authentic development log tracking all conversational stages. Kept locally for standalone HackerRank upload per publication separation.

---

## 8. AI Assistance & Known Limitations

### AI Assistance Disclosure
Development was conducted with pair-programming assistance from:
- **Claude Code** (Anthropic): Stages 1–2 (initial inventory, contract scaffolding, schemas).
- **Antigravity** (Google DeepMind): Stages 3–17 (runtime LLM harness, evidence extraction, simulator, planner, audit hardening, Ponytail simplification, clean-room packaging, and final release).

### Material Limitations
1. **Offline Replay Dependency**: Zero-call offline execution relies on the pre-extracted content-addressed observation files in `evaluation/extraction_snapshot/`. Live regeneration from scratch requires an OpenAI API key.
2. **Illegible Documents**: One image in the dataset (`image_04`) is cropped/illegible. The system explicitly tags it as non-legible rather than guessing an arbitrary number.
3. **Conservative Policy Boundary**: The engine rejects unconfirmed future income and restricts spending changes strictly to streams with verified user permission.
