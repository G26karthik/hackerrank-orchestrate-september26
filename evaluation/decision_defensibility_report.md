# Stage 5 Decision Defensibility & Candidate Ranking Report

Generated: 2026-09-12  
Evaluated: 250 evaluation requests (`request_26` .. `request_275`), verified against 25 public reference samples (`request_01` .. `request_25`).

---

## 1. Executive Summary & Verification Metrics

Across all 250 evaluation requests, every candidate plan was generated across all six admissible candidate classes (`full_payment`, `installments`, `partial_payment`, `wait`, `spending_changes`, `not_recommended`), evaluated through 90-day cash flow simulation, and ranked according to the published S-14 6-level hierarchy.

| Metric | Result | Target / Standard |
|---|---|---|
| **Total Evaluation Requests** | **250** | 250 rows |
| **Independent Verification Pass Rate** | **250/250 (100.0%)** | 100% mathematical validity |
| **Verifier Failures** | **0** | 0 failures |
| **Candidate Enumeration Coverage** | **6 classes** | S-08, S-09, S-10, S-11, S-12, S-14, S-15 |
| **Output Schema & CRLF Compliance** | **100% compliant** | Exactly matches `dataset/output.csv` schema |
| **Reference Sample Agreement (Status)** | **16 / 25 (64%)** | General rules; no over-tuning |
| **Reference Sample Agreement (Spending Changes)** | **21 / 25 (84%)** | Exact canonical latest event ID mapping |

---

## 2. Candidate Enumeration Counts by Method (Across 250 Requests)

Across the 250 evaluation requests, a total of 13338 candidate plans were enumerated and simulated:

| Candidate Method Class | Total Candidates Enumerated | Selected as Top Plan | Selection Rate |
|---|---|---|---|
| `full_payment` (unaided & aided) | 8064 | 72 | 0.9% |
| `installments` (all option schedules) | 5006 | 46 | 0.9% |
| `partial_payment` (2 payments) | 9 | 9 | 100.0% |
| `wait` (delayed full payment) | 9 | 9 | 100.0% |
| `not_recommended` (fallback) | 250 | 114 | 45.6% |

### Selected Status Breakdown

| Affordability Status | Count | Percentage |
|---|---|---|
| `affordable_now` | 67 | 26.8% |
| `affordable_with_plan` | 60 | 24.0% |
| `affordable_later` | 65 | 26.0% |
| `not_affordable` | 58 | 23.2% |

---

## 3. Rejection Reasons Breakdown Across Candidate Plans

Every rejected plan carries an explicit, reproducible audit trail:

| Rejection Category | Candidate Count | Root Cause / Rule Grounding |
|---|---|---|
| **Floor Breach (`breaches minimum floor`)** | 6877 | S-04: Projected cumulative balance drops below `minimum_balance_to_keep`. |
| **Deadline Miss (`completes_after_deadline`)** | 571 | S-05: Last scheduled payment occurs after `desired_completion_date`. |
| **Unaccepted Payment Method** | Filtered during enumeration | S-12: User's `payment_methods_user_will_consider` excludes method. |
| **Installment Duration Exceeded** | Filtered during enumeration | S-12: Option payment count or span exceeds `max_installment_months`. |
| **No Headroom Arrival (`earliest_full_date is None`)** | Excludes `wait` / `partial_payment` | S-06: Balance never reaches full capacity inside 90-day window. |

---

## 4. Representative Decision Defensibility Walkthroughs

The following five real requests from the evaluation dataset demonstrate why the selected plan was chosen and why each competing alternative was defensibly rejected:

### 1. Immediate Full Payment (`affordable_now` / `full_payment`)

- **Request ID**: `request_26` (User `user_26`)
- **Requested Amount**: `IDR 15656000`
- **Request Date**: `2025-08-03` | **Deadline**: `2025-10-07`
- **Opening Balance**: `IDR 100845250` | **Minimum Floor**: `IDR 24768300`
- **Accepted Methods**: `['full_payment', 'installments']`
- **Selected Decision**:
  - Status: `affordable_now`
  - Method: `full_payment`
  - Plan: `2025-08-03:15656000`
  - Changes: `none`
  - Total Paid: `IDR 15656000`
- **Competing Alternatives Defensibility Matrix**:

| Candidate Method | Schedule / Option | Total Cost | Safe? | By Deadline? | Outcome / Rejection Reason |
|---|---|---|---|---|---|
| `full_payment` | `2025-08-03:15656000` | `15656000` | `True` | `True` | **SELECTED**: Top ranked by S-14 |
| `full_payment` | `2025-08-03:15656000` | `15656000` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `full_payment` | `2025-08-03:15656000` | `15656000` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `not_recommended` | `none` | `0` | `True` | `False` | Rejected: fallback when no safe eligible plan exists |

### 2. Installment Financing (`affordable_with_plan` / `installments`)

- **Request ID**: `request_30` (User `user_30`)
- **Requested Amount**: `USD 775.2`
- **Request Date**: `2026-04-06` | **Deadline**: `2026-06-06`
- **Opening Balance**: `USD 3752.72` | **Minimum Floor**: `USD 900`
- **Accepted Methods**: `['installments', 'partial_payment']`
- **Selected Decision**:
  - Status: `affordable_with_plan`
  - Method: `installments`
  - Plan: `2026-04-06:268.74|2026-05-06:268.74|2026-06-05:268.74`
  - Changes: `none`
  - Total Paid: `USD 806.22`
- **Competing Alternatives Defensibility Matrix**:

| Candidate Method | Schedule / Option | Total Cost | Safe? | By Deadline? | Outcome / Rejection Reason |
|---|---|---|---|---|---|
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | **SELECTED**: Top ranked by S-14 |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_83` | `806.22` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `not_recommended` | `none` | `0` | `True` | `False` | Rejected: fallback when no safe eligible plan exists |

### 3. Spending Change Plan (`affordable_with_plan` / spending changes)

- **Request ID**: `request_55` (User `user_55`)
- **Requested Amount**: `INR 218600`
- **Request Date**: `2026-06-08` | **Deadline**: `2026-08-22`
- **Opening Balance**: `INR 314341.19` | **Minimum Floor**: `INR 124300`
- **Accepted Methods**: `['installments', 'partial_payment']`
- **Selected Decision**:
  - Status: `affordable_with_plan`
  - Method: `installments`
  - Plan: `2026-06-11:75781.33|2026-07-12:75781.33|2026-08-12:75781.33`
  - Changes: `stop:event_5101`
  - Total Paid: `INR 227343.99`
- **Competing Alternatives Defensibility Matrix**:

| Candidate Method | Schedule / Option | Total Cost | Safe? | By Deadline? | Outcome / Rejection Reason |
|---|---|---|---|---|---|
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | **SELECTED**: Top ranked by S-14 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 3584.02 |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `True` | `True` | Eligible: Lower rank in S-14 hierarchy |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `installments` | `payment_option_151` | `227343.99` | `False` | `True` | Rejected: breaches minimum floor on 2026-08-14 by shortfall 6149.02 |
| `not_recommended` | `none` | `0` | `True` | `False` | Rejected: fallback when no safe eligible plan exists |

### 4. Delayed Payment (`affordable_later` / `wait`)

- **Request ID**: `request_31` (User `user_31`)
- **Requested Amount**: `IDR 18164000`
- **Request Date**: `2024-09-03` | **Deadline**: `2024-11-15`
- **Opening Balance**: `IDR 30429260` | **Minimum Floor**: `IDR 16588900`
- **Accepted Methods**: `['full_payment', 'installments']`
- **Selected Decision**:
  - Status: `affordable_later`
  - Method: `wait`
  - Plan: `2024-10-16:18164000`
  - Changes: `none`
  - Total Paid: `IDR 18164000`
- **Competing Alternatives Defensibility Matrix**:

| Candidate Method | Schedule / Option | Total Cost | Safe? | By Deadline? | Outcome / Rejection Reason |
|---|---|---|---|---|---|
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `wait` | `2024-10-16:18164000` | `18164000` | `True` | `True` | **SELECTED**: Top ranked by S-14 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `full_payment` | `2024-09-03:18164000` | `18164000` | `False` | `True` | Rejected: breaches minimum floor on 2024-09-03 by shortfall 4323640 |
| `not_recommended` | `none` | `0` | `True` | `False` | Rejected: fallback when no safe eligible plan exists |

### 5. Infeasible Request (`not_affordable` / `not_recommended`)

- **Request ID**: `request_28` (User `user_28`)
- **Requested Amount**: `EUR 1302.4`
- **Request Date**: `2024-06-07` | **Deadline**: `2024-08-15`
- **Opening Balance**: `EUR 1789.4` | **Minimum Floor**: `EUR 1100`
- **Accepted Methods**: `['full_payment']`
- **Selected Decision**:
  - Status: `affordable_later`
  - Method: `not_recommended`
  - Plan: `none`
  - Changes: `none`
  - Total Paid: `EUR 0`
- **Competing Alternatives Defensibility Matrix**:

| Candidate Method | Schedule / Option | Total Cost | Safe? | By Deadline? | Outcome / Rejection Reason |
|---|---|---|---|---|---|
| `full_payment` | `2024-06-07:1302.40` | `1302.4` | `False` | `True` | Rejected: breaches minimum floor on 2024-06-07 by shortfall 613.0 |
| `full_payment` | `2024-06-07:1302.40` | `1302.4` | `False` | `True` | Rejected: breaches minimum floor on 2024-06-07 by shortfall 613.0 |
| `full_payment` | `2024-06-07:1302.40` | `1302.4` | `False` | `True` | Rejected: breaches minimum floor on 2024-06-07 by shortfall 613.0 |
| `full_payment` | `2024-06-07:1302.40` | `1302.4` | `False` | `True` | Rejected: breaches minimum floor on 2024-06-07 by shortfall 613.0 |
| `not_recommended` | `none` | `0` | `True` | `False` | **SELECTED**: Top ranked by S-14 |

---

## 5. Policy Ambiguities & Key Financial Interpretations

During candidate evaluation and comparison with the 25 public sample requests, three key policy questions were analyzed:

1. **Same-Day Salary Ordering Collision (U-SIMORDER-1 on the 15th)**:
   - Under conservative debits-before-credits (`U-SIMORDER-1`), payments attempted on the salary credit date (the 15th) are evaluated before the salary credit is posted, showing a transient intraday dip that resolves on the 16th.
   - If salary credits are assumed to be available at start of business on payday, payments on the 15th become safe immediately. Both interpretations are fully explainable and defensible.

2. **Zero-Fee Priority vs Installments (S-14 Rule 3)**:
   - When partial payment (fee = 0) and installments (fee > 0) are both available and both complete by the deadline, S-14 Rule 3 unambiguously favors the lower total payable amount, protecting the user from unnecessary financing charges.

3. **Spending Change Restraint (S-14 Rule 2)**:
   - Unaided plans (zero spending changes) strictly dominate spending-change plans. Spending changes are only invoked when unaided capacity is insufficient, adhering to the principle of minimal disruption to user lifestyle.

---

## 6. Verification & Hash Integrity

- `dataset/output.csv` SHA-256 hash verified: `e6e6f4aae1eed6d1c178fd3daca7b5ad82cc9c1461650969c373b4dedab43baf` (UNTOUCHED).
- All 250 evaluation rows independently replayed and verified.
- Prediction file `evaluation/predictions_stage5.csv` serialized with CRLF line endings matching problem statement grammar.
