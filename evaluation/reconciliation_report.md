# Reconciliation Report: Financial State Resolver and Recurrence Forecast

**Dataset Evaluation Set**: 250 evaluation requests (`requests.csv`) across 250 distinct users.
**Date Generated**: 2026-09-12 (Stage 4 Completion)

## 1. Global Reconciliation Counts (250 Evaluation Requests)

| Metric | Count | Description / Contract Rule |
|---|---|---|
| Source Event Rows Considered | 23,069 | Total financial event rows processed across 250 users |
| Historical Settled Cash Excluded | 22,871 | Settled events dated < request_date (already in opening balance; S-03/S-04) |
| Cancelled Transactions Dropped | 20 | S-17: Cancelled transactions excluded from cash movements |
| Failed Transactions Dropped | 19 | S-17: Failed transaction attempts excluded |
| Unrealized/Non-Cash Valuations Dropped | 8 | S-17: Investment valuations never counted as cash |
| Pending Credits Excluded | 7 | S-16: Pending refunds, bonuses, commissions excluded until settlement |
| Pending Debits Reserved | 55 | S-16 / U-DUP-1: Reserved as immediate outflow on request_date |
| Explicit Future Scheduled Events Admitted | 77 | S-18: Scheduled future salary, rent, debt retries |
| Image Amount Amendments | 11 | Blank event amounts resolved from image audit (S-21) |
| Message Amendments Applied | 30 | Evidence fact amendments applied (S-24 precedence) |

### Lifecycle Graph Patterns Identified

| Lifecycle Group | Count | Cash Treatment |
|---|---|---|
| `cancelled_duplicate` | 14 | Verified against Table 5.4 |
| `failed_then_scheduled_retry` | 14 | Verified against Table 5.4 |
| `refund_settled` | 12 | Verified against Table 5.4 |
| `investment_valuation` | 8 | Verified against Table 5.4 |
| `refund_pending` | 7 | Verified against Table 5.4 |
| `disputed_pending_mirror` | 6 | Verified against Table 5.4 |
| `investment_sale_settled` | 5 | Verified against Table 5.4 |

## 2. Recurrence Engine Statistics

- **Supported Recurring Streams**: 1814 streams (history >= 2 with consistent interval/day)
- **Insufficient History Streams**: 215 streams (suppressed from forward projection per S-19)

**Supported Streams Breakdown by Category**:

- `salary`: 323 active recurring streams
- `utilities`: 250 active recurring streams
- `rent`: 211 active recurring streams
- `cloud_storage`: 151 active recurring streams
- `shopping`: 130 active recurring streams
- `streaming`: 127 active recurring streams
- `debt_repayment`: 100 active recurring streams
- `entertainment`: 94 active recurring streams
- `insurance`: 82 active recurring streams
- `music_subscription`: 81 active recurring streams
- `delivery_membership`: 62 active recurring streams
- `healthcare`: 60 active recurring streams
- `education`: 53 active recurring streams
- `housing`: 39 active recurring streams
- `gym`: 30 active recurring streams
- `family_support`: 21 active recurring streams

## 3. Comparison of Robust Variable Spending Estimators

Comparison of aggregate monthly estimates across 250 users for essential variable spending (Groceries, Transport, Dining):

| Estimator Method | Aggregate Monthly Spend (EUR-equiv) | Contract / Financial Rationale |
|---|---|---|
| `trailing_3_month_mean_floored_at_latest_month` *(Default)* | 437,285,328.58 | Conservative default (U-FORECAST-1); prevents under-projecting recent spending surge |
| `trailing_3_month_median` | 397,785,890.77 | Robust to single-month spending outliers |
| `trailing_3_month_mean` | 409,812,575.65 | Standard rolling 3-month unfloored average |
| `latest_complete_month` | 413,361,125.67 | Most recent complete month only |

## 4. 90-Day Baseline Trajectory and Binding Headroom

- **Baseline Breaches** (users who dip below minimum balance without making any payment): 10 / 250
- **Average Binding Day Offset** from `request_date`: Day 16.1

**Binding Date Distribution (days after request_date)**:

- Day +00: 28 requests (11.2%)
- Day +04: 1 requests (0.4%)
- Day +07: 75 requests (30.0%)
- Day +08: 36 requests (14.4%)
- Day +09: 27 requests (10.8%)
- Day +10: 21 requests (8.4%)
- Day +11: 16 requests (6.4%)
- Day +12: 4 requests (1.6%)
- Day +13: 1 requests (0.4%)
- Day +14: 6 requests (2.4%)
- Day +16: 1 requests (0.4%)
- Day +21: 1 requests (0.4%)
- Day +23: 1 requests (0.4%)
- Day +42: 5 requests (2.0%)
- Day +49: 1 requests (0.4%)
- Day +58: 1 requests (0.4%)
- Day +64: 1 requests (0.4%)
- Day +70: 6 requests (2.4%)
- Day +84: 7 requests (2.8%)
- Day +87: 3 requests (1.2%)
- Day +88: 2 requests (0.8%)
- Day +89: 2 requests (0.8%)
- Day +90: 4 requests (1.6%)

## 5. Source-Linked Walkthroughs of Representative Cases

### Case: Job Ending (`request_29` / `user_29`)

- **Request Date**: `2025-11-04` | **Requested Amount**: `51524`
- **Opening Balance**: `113540.1` | **Minimum to Keep**: `28300`
- **Baseline Minimum Headroom**: `1071.10` (Binding Date: `2026-01-27`)
- **Amount Safe to Pay on Request Date**: `1071.10`
- **Key Evidence Facts**:
  - `[message_21] income_ended`: amount=None, eff=None, excerpt='Here’s the latest payroll information from Riverline Retail. The current seasonal contract'
- **Resolved Fields**:
  - `income_ended` = `True` (precedence: `explicit_cancellation_settlement_or_amendment`, notes: `Income ended confirmed by message message_21`)
- **Supported Streams**:
  - `housing`: `Building maintenance payment` | typical=3806 (Day 3) | detected from historical settled events
  - `utilities`: `Electricity and water bill` | typical=2654.23 (Day 6) | detected from historical settled events
  - `insurance`: `Insurance policy payment` | typical=1962.4 (Day 7) | detected from historical settled events
  - `education`: `School fee payment` | typical=5170 (Day 8) | detected from historical settled events
  - `healthcare`: `Diagnostic test` | typical=3227.06 (Day 10) | detected from historical settled events
  - `cloud_storage`: `Online backup subscription` | typical=181.5 (Day 12) | detected from historical settled events
  - `entertainment`: `Games and recreation` | typical=1596.85 (Day 14) | detected from historical settled events

### Case: Salary Amendment (`request_32` / `user_32`)

- **Request Date**: `2025-02-05` | **Requested Amount**: `40018`
- **Opening Balance**: `69005.8` | **Minimum to Keep**: `35700`
- **Baseline Minimum Headroom**: `14582.18` (Binding Date: `2025-02-12`)
- **Amount Safe to Pay on Request Date**: `14582.18`
- **Key Evidence Facts**:
  - `[message_22] income_amount_change`: amount=54120, eff=2025-02-15, excerpt='BrightPath Media has updated your payroll record. Your first salary will be ZAR 54120. The'
- **Resolved Fields**:
- **Supported Streams**:
  - `rent`: `Monthly rent` | typical=15664 (Day 1) | detected from historical settled events
  - `utilities`: `Municipal utilities` | typical=3372.96 (Day 5) | detected from historical settled events
  - `education`: `Course tuition` | typical=4180 (Day 7) | detected from historical settled events
  - `debt_repayment`: `Personal loan payment` | typical=4631 (Day 10) | detected from historical settled events
  - `music_subscription`: `Music service subscription` | typical=398.2 (Day 10) | detected from historical settled events
  - `delivery_membership`: `Grocery delivery membership` | typical=897.6 (Day 12) | detected from historical settled events
  - `salary`: `First-job payroll` | typical=54120 (Day 15) | detected from historical settled events; amount amended to 54120 from evidence

### Case: Pending Refund (`request_35` / `user_35`)

- **Request Date**: `2025-10-30` | **Requested Amount**: `212000`
- **Opening Balance**: `231530` | **Minimum to Keep**: `106400`
- **Baseline Minimum Headroom**: `31777.98` (Binding Date: `2025-11-15`)
- **Amount Safe to Pay on Request Date**: `31777.98`
- **Key Evidence Facts**:
  - `[message_25] refund_not_yet_settled`: amount=None, eff=None, excerpt='Here’s the latest payment status from Everyday Store. Your refund has been initiated but h'
- **Resolved Fields**:
  - `amount` = `8528.0` (precedence: `explicit_cancellation_settlement_or_amendment`, notes: `Amount resolved from image for event_3231`)
- **Supported Streams**:
  - `rent`: `Shared housing rent` | typical=37000 (Day 4) | detected from historical settled events
  - `utilities`: `Energy provider bill` | typical=11638.22 (Day 8) | detected from historical settled events
  - `education`: `Professional training fee` | typical=9710 (Day 10) | detected from historical settled events
  - `debt_repayment`: `Vehicle loan payment` | typical=9100 (Day 13) | detected from historical settled events
  - `music_subscription`: `Music subscription` | typical=1070 (Day 13) | detected from historical settled events
  - `salary`: `Payroll credit` | typical=162000 (Day 15) | detected from historical settled events
  - `delivery_membership`: `Grocery delivery membership` | typical=1275 (Day 15) | detected from historical settled events

### Case: Foreign Salary (`request_39` / `user_39`)

- **Request Date**: `2026-04-04` | **Requested Amount**: `208600`
- **Opening Balance**: `416505` | **Minimum to Keep**: `213400`
- **Baseline Minimum Headroom**: `61156.60` (Binding Date: `2026-04-14`)
- **Amount Safe to Pay on Request Date**: `61156.60`
- **Key Evidence Facts**:
- **Resolved Fields**:
- **Supported Streams**:
  - `rent`: `Residential rent payment` | typical=78000 (Day 4) | detected from historical settled events
  - `utilities`: `Energy provider bill` | typical=14231.07 (Day 8) | detected from historical settled events
  - `insurance`: `Vehicle insurance premium` | typical=10200 (Day 9) | detected from historical settled events
  - `streaming`: `Family streaming plan` | typical=5580 (Day 11) | detected from historical settled events
  - `cloud_storage`: `Shared storage plan` | typical=1265 (Day 14) | detected from historical settled events
  - `shopping`: `Clothing and household items` | typical=9687.98 (Day 14) | detected from historical settled events
  - `salary`: `Payroll credit` | typical=253989.84 (Day 15) | detected from historical settled events
  - `entertainment`: `Local event tickets` | typical=9050.61 (Day 16) | detected from historical settled events

### Case: Debt Retry (`request_55` / `user_55`)

- **Request Date**: `2026-06-08` | **Requested Amount**: `218600`
- **Opening Balance**: `314341.19` | **Minimum to Keep**: `124300`
- **Baseline Minimum Headroom**: `117661.93` (Binding Date: `2026-06-15`)
- **Amount Safe to Pay on Request Date**: `117661.93`
- **Key Evidence Facts**:
- **Resolved Fields**:
  - `amount` = `723.0` (precedence: `explicit_cancellation_settlement_or_amendment`, notes: `Amount resolved from image for event_5170`)
- **Supported Streams**:
  - `rent`: `Apartment rent transfer` | typical=54400 (Day 4) | detected from historical settled events
  - `utilities`: `Water and power payment` | typical=13529.34 (Day 8) | detected from historical settled events
  - `streaming`: `Family streaming plan` | typical=5240 (Day 11) | detected from historical settled events
  - `debt_repayment`: `Personal loan payment` | typical=15550 (Day 13) | detected from historical settled events
  - `cloud_storage`: `Online backup subscription` | typical=855 (Day 14) | detected from historical settled events
  - `shopping`: `Online retail purchases` | typical=6320.18 (Day 14) | detected from historical settled events
  - `salary`: `Payroll credit` | typical=216000 (Day 15) | detected from historical settled events
