# inventory.md — participant-facing dataset inventory

Recount of every file in `dataset/` at commit `963ad7eb3d058ace2bf2e8bf4324472c981f0840`,
performed 2026-09-12. SHA-256 for each file is in `contract.md` §1.3.

Counting method: `csv.reader` with `encoding='utf-8-sig'`, header excluded, all-blank rows dropped.
No file contained an all-blank row, so the count equals `lines - 1` for every file.

---

## 1. Count reconciliation against the preparatory snapshot

| File | Snapshot | Recounted | Difference |
|---|---|---|---|
| `requests.csv` | 250 | **250** | none |
| `sample_requests.csv` | 25 | **25** | none |
| `financial_profiles.csv` | 275 | **275** | none |
| `financial_events.csv` | 25,342 | **25,342** | none |
| `request_payment_options.csv` | 790 | **790** | none |
| `messages.csv` | 215 | **215** | none |
| `exchange_rates.csv` | 134 | **134** | none |
| `media/images/*.png` | 16 | **16** | none |
| `images.csv` (rows) | — | 16 | one row per image file |
| `output.csv` (template rows) | — | 250 | one blank row per evaluation request |

**All eight snapshot counts reproduce exactly. There is nothing to explain.** This is consistent
with the organizer `main` being at the same commit as the local checkout, so the dataset has not
been revised since the preparatory inspection.

---

## 2. Identifier spaces and joins

| Property | Value |
|---|---|
| Distinct users in `financial_profiles.csv` | 275, no duplicate `user_id` |
| Distinct users in `requests.csv` | 250 |
| Distinct users in `sample_requests.csv` | 25 |
| Overlap between evaluation users and sample users | **0** |
| Users appearing in more than one request (any file) | **0** — the mapping is strictly 1 request : 1 user |
| Evaluation users missing a profile | 0 |
| Sample users missing a profile | 0 |
| Profiles not referenced by any request | 0 |
| Distinct users in `financial_events.csv` | 275; every profile user has events, no orphan events |
| `request_id` ranges | samples `request_01`..`request_25`; evaluation `request_26`..`request_275`; no collision |
| `request_payment_options.request_id` values outside requests+samples | 0 |
| Requests with zero payment options | 0 |
| `messages.related_event_id` values not present in events | 0 |
| `images.related_event_id` values not present in events | 0 |
| `messages.user_id` disagreeing with the linked request's user | 0 |
| `messages.related_event_id` whose event belongs to another user | 0 |

**Join consequence that matters:** because every user has exactly one request, a message or image
row with a blank `request_id` still resolves to a unique request through `user_id`. Joining evidence
on `request_id` alone reaches 128 of 275 requests; joining on `user_id` reaches all 215 messages,
covering **198 of the 250 evaluation requests** instead of 116.

---

## 3. `requests.csv` (250 rows, 8 columns)

Columns: `request_id, user_id, request_date, request_type, requested_amount, desired_completion_date, allows_partial_payment, request_text`.
No blank cells anywhere.

| Field | Observation |
|---|---|
| `request_type` | 9 values; near-uniform: family_transfer 28, purchase 28, investment 28, debt_repayment 28, travel 28, housing 28, education 28, emergency_expense 27, other 27 |
| `allows_partial_payment` | lowercase strings only: `false` 170, `true` 80 |
| `request_date` | 61 distinct values, range `2023-01-20` .. `2026-09-04` |
| `desired_completion_date` | 170 distinct; never earlier than `request_date` |
| completion horizon | min 6 days, median 65, max 86 — **never exceeds the 90-day forecast window** |
| `requested_amount` | 199.89 .. 83,923,000 (magnitudes differ by currency) |

Request-date distribution across all 275 requests (samples included) spans 2019 to 2026, so
"today" is always `request_date`, never the wall clock:

```
2019-09: 1    2023-01: 1    2023-08: 1    2024-03: 22   2024-06: 22   2024-09: 22
2024-12: 23   2025-02: 22   2025-05: 22   2025-08: 23   2025-10: 2    2025-11: 21
2026-01: 28   2026-02: 1    2026-03: 1    2026-04: 29   2026-06: 2    2026-07: 31
2026-09: 1
```

---

## 4. `financial_profiles.csv` (275 rows, 10 columns)

| Field | Observation |
|---|---|
| `home_currency` | INR 67, EUR 62, IDR 55, ZAR 51, USD 40 |
| `current_available_balance` | 683.69 .. 136,691,818.94; 275 distinct values |
| `minimum_balance_to_keep` | 400 .. 41,430,800 |
| balance below minimum at request time | **0 profiles** — every user starts above their floor |
| `financial_priorities` | always populated, `\|`-separated; 8 tokens: emergency_savings 171, education 94, retirement_investment 61, debt_repayment 56, family_support 49, travel 46, healthcare 44, housing 29 |
| `expense_categories_to_protect` | always populated; 10 tokens: rent 232, groceries 166, transport 109, utilities 105, education 60, debt_repayment 56, insurance 46, healthcare 44, housing 43, family_support 25 |
| `expense_categories_user_is_willing_to_reduce` | **39 blank**; 5 tokens: dining 153, shopping 72, streaming 66, entertainment 44, gym 14 |
| `expense_categories_user_is_willing_to_stop` | **62 blank**; 5 tokens: cloud_storage 109, streaming 84, music_subscription 58, delivery_membership 41, gym 12 |
| `payment_methods_user_will_consider` | always populated; full_payment 163, installments 156, partial_payment 139 |
| `max_installment_months` | **119 blank** (user will not consider installments); otherwise 2..12 |

Separator is `\|` in every multi-value field; no commas or semicolons appear inside a field.

---

## 5. `financial_events.csv` (25,342 rows, 14 columns)

Columns: `event_id, user_id, event_type, description, category, direction, amount, currency, event_date, settlement_date, status, linked_event_id, flexibility, minimum_allowed_amount`.

### 5.1 Field completeness

| Field | Blanks | Notes |
|---|---|---|
| `amount` | **16** | every one is resolvable from exactly one image — see §8 |
| `settlement_date` | **10** | all ten are `investment_valuation` / `non_cash` / `unrealized` rows, which have no cash settlement |
| `linked_event_id` | 25,284 | 58 rows carry a link; 59 distinct values across parents and children |
| `minimum_allowed_amount` | 22,435 | populated on exactly the 2,907 `reducible` and `reducible_or_stoppable` rows, never on `fixed` or `stoppable` |
| all other fields | 0 | — |

### 5.2 Enumerations with counts

```
event_type : expense 20525, subscription 2488, income 1696, debt_payment 567,
             investment_purchase 29, refund 22, investment_valuation 10, investment_sale 5
direction  : debit 23609, credit 1723, non_cash 10
status     : settled 25148, pending 71, scheduled 70, cancelled 22, failed 21, unrealized 10
flexibility: fixed 21138, reducible 2682, stoppable 1297, reducible_or_stoppable 225
currency   : INR 6457, EUR 5585, IDR 4992, ZAR 4489, USD 3819
category   : groceries 5812, transport 5626, dining 3479, salary 1690, utilities 1452,
             rent 1355, cloud_storage 833, shopping 813, streaming 683, debt_repayment 553,
             entertainment 521, insurance 456, music_subscription 451, healthcare 356,
             delivery_membership 351, education 306, housing 246, gym 170, family_support 125,
             investment 44, work_expense 14, windfall 6
```

Flexibility maps cleanly onto categories, which matters for spending changes:

```
reducible              : dining 1925, shopping 360, entertainment 220, streaming 127, gym 50
stoppable              : cloud_storage 547, music_subscription 290, streaming 215,
                         delivery_membership 205, gym 40
reducible_or_stoppable : streaming 205, gym 20
fixed                  : everything else, including all income, rent, utilities, insurance,
                         education, healthcare, debt_payment, investment rows
```

### 5.3 Timing relative to `request_date` — the single most important structural fact

| Measure | Value |
|---|---|
| Events with effective date at or before the user's `request_date` | **25,201** |
| Events with effective date after the user's `request_date` | **141** |
| Users with at least one future-dated event | **122 of 275** |
| Future-event offsets | 1 to 20 days only (never beyond +20d) |
| Future events by kind | pending expense debit 63, scheduled income credit 47, scheduled expense debit 16, pending refund credit 8, scheduled debt_payment debit 7 |
| `pending` rows | 71, **all** effective after `request_date` |
| `scheduled` rows | 70, **all** effective after `request_date` |
| `cancelled` / `failed` / `unrealized` rows | 22 / 21 / 10, **all** effective at or before `request_date` |
| Events per user | min 56, median 98, max 129 |
| History span per user | median 177 days, min 169, max 196 (about six monthly cycles) |

Consequence: the 90-day forward ledger cannot be read off the table. At most +20 days of explicit
future rows exist, and only 47 users have a scheduled salary row. Days 21 to 90 must be produced by
recurrence detection over roughly six months of history, plus message and image amendments.
"Effective date" above means `settlement_date` when present, else `event_date`.

### 5.4 Lifecycle patterns in the 58 linked rows

Every link is child -> earlier parent. Six distinct patterns, each with a different cash meaning:

| Pattern | Count | Cash treatment |
|---|---|---|
| `refund` credit linked to a settled `expense` — **settled** | 12 | counts as a credit on its settlement date (already inside history) |
| `refund` credit linked to a settled `expense` — **pending** | 8 | pending credit: **excluded** until it settles |
| `expense` settled linked to a **cancelled** `expense` of the same amount | 8 | the cancelled parent is dropped; only the settled child counts (a duplicate representation, not two charges) |
| `investment_valuation` non_cash/unrealized linked to `investment_purchase` | 10 | never cash, either direction of movement |
| `investment_sale` credit settled linked to `investment_purchase` | 5 | settled credit; counts |
| `debt_payment` **scheduled** linked to a **failed** `debt_payment` of the same amount | 8 | the failed attempt is dropped; the scheduled retry is a future debit |
| `expense` **pending** linked to a **settled** `expense` of the same amount, ~11 days later | 7 | ambiguous — see `assumptions.md` U-DUP-1 |

The last pattern is the only one the rules do not settle by themselves: `problem_statement.md`
says to reserve pending debits but also to ignore duplicate records, and eight of these rows are
described by a bank message as a disputed extra card charge with no reversal posted.

---

## 6. `request_payment_options.csv` (790 rows, 9 columns)

| Property | Value |
|---|---|
| Options per request | 2 to 4 — 2 options: 65 requests, 3 options: 180, 4 options: 30 |
| `payment_method` | `full_payment` 275, `installments` 515. **No `partial_payment` rows exist.** |
| Exactly one `full_payment` option per request | yes, 275/275 |
| `full_payment.payment_amount == requested_amount` | 275/275, zero fee, `total_payable_amount` equal |
| `full_payment.first_payment_date == request_date` | 275/275 |
| `payment_frequency_days` | blank on all 275 `full_payment` rows; 28 (180), 31 (169), 30 (166) on installments |
| `number_of_payments` | 1 (275), 2 (7), 3 (80), 4 (3), 6 (65), 15 (89), 18 (87), 21 (88), 24 (96) |
| `payment_amount * number_of_payments == total_payable_amount` | 790/790 exact (tolerance 0.02) |
| `requested_amount + financing_fee == total_payable_amount` | 790/790 exact |
| `first_payment_date - request_date` | 0 (381), 1 (2), 3 (156), 5 (2), 6 (1), 7 (104), 14 (144) |
| Options whose last payment falls after `desired_completion_date` | **434 of 515 installment options** |
| Options whose last payment falls after `request_date + 90d` | 428 |

Completion-by-deadline, broken down by plan length — the decisive filter in practice:

```
n= 2:  7/7  complete by desired_completion_date
n= 3: 74/80
n= 4:  0/3
n= 6:  0/65
n=15:  0/89
n=18:  0/87
n=21:  0/88
n=24:  0/96
```

Combining the deadline filter with `max_installment_months`:

| Situation | Evaluation requests |
|---|---|
| User leaves `max_installment_months` blank (installments not considered) | 119 of 275 overall |
| User considers installments but **no** option fits within `max_installment_months` | 67 of 275 overall |

Eligible-method availability per evaluation request (full payment accepted / partial usable, meaning
the request allows it and the user accepts it / installments usable, meaning accepted, within
`max_installment_months`, and completing by the deadline):

```
full only                        131
installments only                 63
full + partial                    17
partial only                      12
partial + installments            11
no usable method at all           16
```

Notable structural property: **no evaluation request has both `full_payment` accepted and a usable
installment option.** The two never co-occur in this dataset, which removes a whole class of
ranking ties. Sixteen evaluation requests have no usable payment method at all, which forces
`not_recommended`.

Also worth recording: `allows_partial_payment` and the user's acceptance of `partial_payment`
disagree far more often than they agree — across all 275 requests, allowed and accepted 45,
neither 89, allowed but not accepted 47, accepted but not allowed 94.

---

## 7. `exchange_rates.csv` (134 rows, 4 columns)

| Property | Value |
|---|---|
| Columns | `rate_date, from_currency, to_currency, rate` |
| Directed pairs (5 only) | USD->INR 33, USD->IDR 30, USD->EUR 25, EUR->USD 24, EUR->ZAR 22 |
| Distinct `rate_date` values | 39, range `2023-10-15` .. `2026-11-15`; all on the 15th except a single `2025-10-01` row |
| Rows per date | 1 to 5 |

Rates are directional and there is no inverse row for most pairs (for example INR->USD does not
exist), so conversion must use the stated direction only.

Coverage check against demand: 140 event rows carry a currency different from the user's
`home_currency` (USD->INR 54, USD->IDR 28, USD->EUR 22, EUR->ZAR 20, EUR->USD 16). The distinct
`(effective_date, from_currency, to_currency)` triples they require number 101, and **all 101 are
present in `exchange_rates.csv`** — zero misses. This is by construction: 139 of the 140 foreign
rows settle on the 15th, and the single foreign expense settles on `2025-10-01`, which is exactly
the one off-cycle rate date.

Foreign-currency exposure detail: 139 of the 140 rows are `income`, 1 is an `expense`; 132 settled
and 8 scheduled; 27 users affected, 26 of them evaluation users; 8 of the rows are dated after their
user's `request_date`. The table extends to `2026-11-15`, far enough to price projected
foreign-currency salary inside any 90-day window in the data.

---

## 8. `images.csv` (16 rows) and `media/images/` (16 files)

Every row populates all four columns (`image_id, user_id, request_id, related_event_id`), every
referenced PNG exists on disk, and every one of the 16 blank-`amount` events is covered by exactly
one image. Sizes 111 KB to 756 KB, 512x364 to 1628x1366 pixels.

| image | user | request | event | event status | category | effective date |
|---|---|---|---|---|---|---|
| image_01 | user_03 | request_03 (sample) | event_253 | settled | salary (income) | 2019-08-31 |
| image_02 | user_16 | request_16 (sample) | event_1442 | **scheduled** | rent | 2023-08-16 |
| image_03 | user_17 | request_17 (sample) | event_1545 | settled | groceries | 2026-02-27 |
| image_04 | user_19 | request_19 (sample) | event_1700 | settled | groceries | 2024-09-03 |
| image_05 | user_20 | request_20 (sample) | event_1786 | **pending** | utilities | 2026-02-09 |
| image_06 | user_33 | request_33 | event_3051 | settled | groceries | 2026-01-06 |
| image_07 | user_35 | request_35 | event_3231 | settled | dining | 2025-10-29 |
| image_08 | user_48 | request_48 | event_4535 | settled | housing | 2026-07-24 |
| image_09 | user_55 | request_55 | event_5170 | settled | utilities | 2026-06-07 |
| image_10 | user_64 | request_64 | event_6033 | **pending** | groceries | 2024-06-10 |
| image_11 | user_73 | request_73 | event_6859 | **scheduled** | healthcare | 2023-01-23 |
| image_12 | user_78 | request_78 | event_7307 | settled | transport | 2025-10-01 |
| image_13 | user_84 | request_84 | event_7941 | settled | shopping | 2026-04-03 |
| image_14 | user_101 | request_101 | event_9421 | settled | healthcare | 2025-11-02 |
| image_15 | user_105 | request_105 | event_9806 | settled | transport | 2026-06-07 |
| image_16 | user_113 | request_113 | event_10521 | settled | transport | 2026-09-03 |

**11 of the 16 images belong to evaluation requests** (request_33, 35, 48, 55, 64, 73, 78, 84, 101,
105, 113); the other 5 belong to public samples. Of the 11 evaluation cases, two are non-settled and
therefore change the forward ledger directly (`event_6033` pending groceries, `event_6859` scheduled
healthcare); the remaining nine are settled history and matter because they feed the recurring-spend
estimate for their category.

Legibility spot-check: `image_06` was opened and read. It is a clean tabular GST invoice whose
line items and a bold `Total` row are machine-legible; the extractable figure is the invoice
`Total` (1995.00), not a line-item or tax subtotal. Three of the sixteen are described in
`messages.csv` as receipts confirming "the final amount" (`message_35`, `message_64`, `message_86`),
which gives an independent cross-check for those three.

---

## 9. `messages.csv` (215 rows, 7 columns)

| Property | Value |
|---|---|
| Columns | `message_id, user_id, request_id, related_event_id, sent_at, source_type, message_text` |
| Rows | 215, one per user — **no user has two messages**; 215 of 275 users are covered |
| `request_id` populated | 128; blank 87 (still resolvable via `user_id`, see §2) |
| `related_event_id` populated | 39; blank 176, consistent with the documented rule that it appears only when the message describes one supplied event row |
| `sent_at` | ISO-8601 with `Z`, always 1 to 12 days **before** the user's `request_date` |
| `source_type` | employer 126, service_provider 31, financial_service 23, bank 18, merchant 17 |
| Evaluation requests reachable | **198 of 250** |
| Languages | mixed English and Indonesian (`Rincian penggajian…`, `Klien menyetujui…`, `Ada pembaruan…`); roughly a quarter of the corpus is Indonesian |
| Encoding note | several rows contain a mis-encoded apostrophe (rendered `Here�s` in a strict read); text must be read tolerantly, and this does not affect any amount or date |

The corpus is templated. Twenty archetypes were identified, grouped by the financial action they
imply. This classification is evidence for `assumptions.md`, not itself a rule:

**Employer / payroll (126)**
1. Salary increased to X, effective from a stated date.
2. Temporary reduced monthly pay of X, continuing "for the next payroll".
3. Next salary reduced to X because of approved unpaid leave.
4. First salary will be X with a confirmed credit date.
5. First salary of X scheduled, approved and sent for processing.
6. Confirmed salary date moved to a new date, explicitly replacing an earlier date.
7. Quarterly bonus still subject to review; amount and date **not approved**.
8. Confirmed base salary X, but commission on open deals **pending approval**.
9. Seasonal contract ended; no off-season income or renewal confirmed.
10. Employment ended; no regular salary after final settlement.
11. One household employment record ended; remaining confirmed monthly salary is X.
12. Regular salary of X resumes on a date, **and** a new recurring childcare payment begins the same month (amount not stated).
13. Regular salary X plus a separately identified one-time arrears adjustment Y.
14. Salary of X confirmed for a date in a foreign currency, converted at the settlement-date rate.
15. Latest employer credit is a reimbursement for an earlier work expense, not regular salary; claim closed.

**Service provider (31)**
16. Gig payout still pending and not withdrawable until closed.
17. Client approved an invoice payment of X, settlement expected on a date; other invoices still awaiting approval.
18. Renewed lease increases monthly rent by 12% from the next rent payment.

**Merchant (17)**
19. Refund initiated but not yet credited (sometimes "within ten business days").
20. Foreign-currency refund still processing; home-currency credit depends on the settlement-date rate.
21. Bill charged in a foreign currency; final home-currency amount set at settlement.
22. Receipt confirms the final paid amount (pairs with an image).

**Bank (18)**
23. Matching debit and credit are a transfer between the holder's own two accounts.
24. Previous debit attempt failed; the bill is still outstanding and another debit will be attempted.
25. Extra card charge under investigation; no reversal posted yet; dispute open.
26. Minimum payments due on two separate cards; paying one does not clear the other.

**Financial service (23)**
27. Portfolio displayed value rose or fell; no units sold, no cash proceeds.
28. Prize claim verified but still in payment processing, not credited.
29. Prize proceeds have reached the account after withholding; claim closed.
30. Investment sale proceeds settled in the cash account; nothing pending.
31. **Advance-fee fraud**: "you have been selected for a cash prize — pay the release/processing
    charge today". Two instances, `message_67` (user_88) and `message_142` (user_179, Indonesian).
    These are untrusted instructions that must create neither an expense nor income.

One message is multi-fact and crosses sources: `message_86` (user_113, request_113) contains both
an EV-charging receipt confirmation and an employer-confirmed USD 1,296 salary credit for
2026-09-15 to be converted at the settlement rate.

---

## 10. `sample_requests.csv` (25 rows, 15 columns)

Eight input columns identical to `requests.csv`, plus the seven output columns filled in.

Label distribution across the 25 public examples:

```
affordability_status      : affordable_with_plan 9, not_affordable 7, affordable_later 6, affordable_now 3
recommended_payment_method: not_recommended 7, full_payment 6, wait 6, installments 5, partial_payment 1
payment_plan == "none"    : 7  (exactly the not_recommended rows)
earliest_date empty       : 7  (exactly the not_recommended rows)
spending_changes != none  : 3  (request_06, request_11, request_21)
```

These 25 rows are treated strictly as a format-and-style reference and as evidence about how the
organizer's generator behaves. They are **not** a held-out validation set: all 25 labels were
already inspected during preparatory research, so any score measured on them is optimistic. Their
output columns are never passed into prediction inputs. What they are used for is written up in
`assumptions.md` §2.

---

## 11. Financial ambiguities that matter (ranked by expected point impact)

Full statements, with the conservative default chosen for each, are in `assumptions.md`. Short list:

1. **The variable-spend estimator** (U-FORECAST-1). `amount_safe_to_pay` equals balance minus the
   minimum minus the worst projected cumulative dip. Rent, utilities, insurance, subscriptions,
   debt and salary are anchored and easy. Groceries, transport and dining are 14,917 of 25,342 rows,
   irregular in date and amount, and the spec says only "forecast essential variable spending
   conservatively". The choice of estimator moves `amount_safe_to_pay` on almost every row and is
   the largest single lever on output correctness.
2. **Approved-invoice and resuming-salary credits** (U-INCOME-1). About 25 messages say a client
   approved an invoice of X with settlement expected on a date. Is that "confirmed income" to count
   on that date, or a pending credit to exclude? The two readings change `earliest_date_for_full_payment`
   for a large share of the 198 message-bearing evaluation requests.
3. **Pending debit that duplicates a settled charge** (U-DUP-1). Seven linked rows plus disputed
   card charges: reserve as a pending debit, or drop as a duplicate record.
4. **Unstated new recurring expense** (U-EXPENSE-1). Archetype 12 announces a new recurring
   childcare payment without an amount. Safer interpretation says include it; "do not invent
   financial facts" says it cannot be quantified.
5. **Status when no method is usable but capacity arrives later** (U-STATUS-1). Sixteen evaluation
   requests have no usable payment method. `wait` needs `full_payment` acceptance, so the method is
   `not_recommended`, but `affordable_later` is defined by capacity rather than by method.
6. **Temporary pay reductions** (U-INCOME-2). "The reduced amount continues for the next payroll"
   does not say what happens afterwards.
7. **Rounding and formatting of amounts and the explanation register** (U-FORMAT-1, U-SCORE-2).
   The public samples show a consistent style; no public document states a tolerance.
