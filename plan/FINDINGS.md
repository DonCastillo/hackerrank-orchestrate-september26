# FINDINGS.md — What the 25 samples reveal about the reference logic

Derived by hand-tracing request_01/04/05/08/10/13/18/23 and grid-searching a prototype
forecaster over all 25 samples (`amount_safe_to_pay` only). Updated as we learn more.

## Confirmed structure

1. **Core formula.** `amount_safe_to_pay = clamp(trough_balance − minimum_balance_to_keep, 0, requested_amount)`
   where `trough_balance` = minimum projected balance over the 90-day window starting on
   `request_date`, with **no** spending changes applied. Verified on every non-capped sample:
   `balance − min − safe` always equals a plausible sum of projected outflows up to the trough.
2. **Window = 90 days** ("over the next 90 days" appears in explanations for affordable_now).
3. **Trough is usually the day before the next salary** (most samples), but moves to the end of
   the window when monthly net cash flow is negative (request_05: no income; request_13: −260/mo).
4. **Salary is projected monthly** from history even when no scheduled row exists (request_18:
   wait-until = Sep 15 = salary day, 2 salaries ahead). Only *confirmed* salary counts:
   - constant-amount monthly payroll (155/275 users), or a scheduled `Next confirmed salary` row
   - after a step change (raise/cut), the **latest** amount continues (request_06)
   - a `Prorated first salary` + scheduled next salary ⇒ project the scheduled amount monthly (request_01)
   - `Payroll before leave` / `after returning from leave` ⇒ resumes monthly (request_14; gap breaks median-cadence detection — use description/day-of-month instead)
   - **not** counted: gig weekly payouts (request_10 — reference used zero income), freelance
     irregular invoices, bonuses/commissions, variable "Second household income", lapsed series
     (last occurrence older than ~1.5× cadence), `Final employer payroll` ⇒ no future salary (request_05)
   - foreign-currency salary is converted at the settlement-date rate (request_25: USD 1800 → IDR)
5. **Recurring expenses** are projected per (category, description) for fixed items and per
   category for groceries / transport / dining:
   - constant series (rent, debt, subscriptions, insurance, family_support, gym, education) → exact amount, same day-of-month
   - variable monthly (utilities, healthcare, shopping, entertainment) → a central estimate; reference
     rounds it to a currency unit (EUR/USD/ZAR → 1, INR → 10, IDR → 100)
   - weekly / biweekly / 10-day series (groceries, transport, dining) → same cadence continued from last occurrence
   - the estimate is close to the **mean/median of recent history** but not reproducible exactly
     (errors of ±1 unit per occurrence in both directions ⇒ hidden generator base amounts). Best
     fit so far: median (median |err| 3.2% of headroom). Don't chase exactness further.
6. **Same-day ordering:** debits on the salary day appear to be applied before the credit (request_18).
   Items falling on `request_date` itself are included (request_08 education, request_18 utilities).
7. **Pending debits:** ambiguous (request_22 fits with reserve; request_23 parity suggests not).
   Follow the rules text — reserve them — and re-test in score_samples.
8. **Scheduled rows** are used as-is on their settlement date and suppress the recurring projection for that
   (category, date) (request_04 school fee, request_13 salary).
9. **Ignore:** failed, cancelled, unrealized/investment valuations, pending credits, bonus messages that say
   "not yet approved", refunds unless settled, internal transfers between own accounts (message_13 pattern).
10. **Messages change the numbers** (needed for exact matches): reduced/raised salary (request_06/08),
    salary resume date + new recurring childcare payment (request_14). Images fill blank amounts (request_19 event_1700).

## Decision-layer patterns (from labels + explanations)

- `affordable_now` ⇒ full payment today, `earliest = request_date`, explanation cites "at least <min> over the next 90 days".
- `wait` ⇒ single full payment on `earliest_date_for_full_payment`; in every sample that date is either
  the **next salary date** (request_04: Jun 15) or the **desired_completion_date** (request_03/08/13/18/23) —
  never an arbitrary mid-month date. Hypothesis: earliest = first salary date on/after which a full payment
  stays safe; if none ≤ deadline, wait is not offered.
- `partial_payment` ⇒ `safe` today + remainder on the next salary date (request_19: Sep 15), requires
  `allows_partial_payment` and user considers it.
- `installments` ⇒ the chosen option is always the **3-payment** option in samples (never 15/18/24), even when
  `max_installment_months` allows more; `earliest_date_for_full_payment` is still filled with the wait date
  (e.g. request_02: plan starts Aug 8, earliest = Sep 15) — so `earliest` is computed independently of the plan.
- `affordable_with_plan` + spending changes (request_06/11/21): full payment today after `stop:`/`reduce_to:`
  on non-protected flexible events; `reduce_to` uses the event's `minimum_allowed_amount` (23.50, 665950).
  `earliest_date_for_full_payment` is still the no-changes wait date.
- `not_affordable` ⇒ `not_recommended`, `payment_plan=none`, `earliest` empty; two explanation templates:
  "None of the available options keeps the <min> minimum protected" vs "Although <safe> is available today,
  the full amount cannot be completed safely within 90 days" (used when partial is allowed but no full completion is possible).

## Open questions (carry into Phase 5)

- Installment months: `number_of_payments` vs `(n × frequency_days)/30`? Samples: 3 payments @ 30d with max 7/12/11/3/6 — both readings fit.
- Does the ranking prefer installments over `wait` when both complete by the deadline? (request_02/07/12/17/22 chose installments; each user's methods excluded full_payment except 12/17… check.)
- Do spending changes apply to every future occurrence in the window (assumed yes)?

## Event inventory (Phase 1 · step 3) — 25,342 rows

| Status | Rows | Treatment |
|---|---|---|
| settled | 25,148 | already in `current_available_balance`; history for recurrence |
| pending | 71 | 63 debits → reserve on `settlement_date`; 8 `Pending merchant refund` credits → ignore |
| scheduled | 70 | 47 `Next confirmed salary` credits + 23 debits (bill retry, insurance, school fee, utility, rent balance, hospital) → dated future flows |
| failed | 21 | ignore; 7 have a linked `Scheduled bill payment retry` that carries the real future debit |
| cancelled | 22 | ignore; 8 `Card authorization` have a linked settled `Settled card purchase` (already in balance) |
| unrealized | 10 | `Current portfolio valuation` non_cash → ignore |

Linked pairs (58): refund↔purchase, duplicate charge↔original, retry↔failed, reimbursement↔work expense,
sale↔investment contribution, reversal↔charge, settled purchase↔cancelled auth, valuation↔contribution.
The **6 `Possible duplicate card charge` pending debits** are the judgement call: linked to a settled original
→ likely a duplicate, but the safer reading is to reserve them unless a message/bank note clears them.

Flexibility: fixed 21,138 · reducible 2,682 · stoppable 1,297 · reducible_or_stoppable 225.
`minimum_allowed_amount` is present on exactly the reducible rows → the `reduce_to` floor.

Blank amounts: 16 rows, all image-backed (`images.csv` covers every one). Mix of settled / pending / scheduled,
one salary credit (event_253) and one USD taxi fare for an INR user (event_7307 → needs FX after extraction).

Foreign currency: only salary rows (+ that one taxi fare): EUR/USD payroll into USD/ZAR/EUR/IDR/INR home
accounts, incl. 8 scheduled next salaries → convert at the settlement-date rate.

Dates: 10 blank `settlement_date` (use `event_date`); 178 rows where settlement ≠ event date (all pending/scheduled/cancelled
plus 62 settled card items settling 1–3 days later) → use `settlement_date` for cash timing.

Categories seen in settled debits: groceries, transport, dining (weekly-ish variable); utilities, healthcare, shopping,
entertainment (monthly variable); rent/housing, debt_repayment, insurance, education, gym, family_support, cloud_storage,
streaming, music_subscription, delivery_membership (monthly constant); investment, work_expense (one-off).

## Message inventory (Phase 1 · step 4) — 215 rows, ~30 templates, EN 170 / ID 45

128 tied to a request, 39 to an event (28 both), 76 to neither (user-level). 198 belong to evaluation-request
users; 116 of the 250 requests have at least one message. Every message is one of these archetypes:

| Source | Archetype | Engine action |
|---|---|---|
| employer | salary date moved to `<date>` | `amend_date` on next salary |
| employer | next salary reduced to `X` (unpaid leave) | `amend_amount` on next salary only |
| employer | temporary monthly pay `X` for the next N payrolls | `amend_amount` for N occurrences, then revert |
| employer | monthly salary increased to `X` from `<date>` | recurring salary = X from date |
| employer | first salary `X` on `<date>` (new job / new employer / scheduled & approved) | `new_recurring` salary from date |
| employer | salary `X` resumes on `<date>` + new recurring childcare payment begins | salary from date + `new_recurring` debit |
| employer | salary `X` (foreign currency) confirmed for `<date>`, bank converts at that day's rate | salary in FX → convert |
| employer | regular salary `X` + one-time arrears adjustment `Y` on the same payroll | salary = X; one-off credit Y on that date |
| employer | confirmed base salary `X`; commission pending approval | salary = base only; ignore commission |
| employer | household employment ended; remaining confirmed monthly salary `X` | salary = X (drop the other source) |
| employer | seasonal contract ended / employment ended, nothing scheduled | `cancel` future salary |
| employer | quarterly bonus still subject to review | ignore |
| employer | latest credit is a work-expense reimbursement | not income (one-off, already settled) |
| service_provider | client approved invoice `X` expected `<date>`; others pending | one-off credit X on date; ignore rest |
| service_provider | gig payout still pending / can change | ignore (no income) |
| service_provider | renewed lease raises rent by N% from next payment | `amend_amount` on recurring rent |
| service_provider | maintenance payment received; receipt has final amount | image-backed event |
| bank | extra card charge under investigation, reversal not posted | keep the pending duplicate reserved |
| bank | previous debit failed, bill still outstanding | scheduled retry stands |
| bank | matching debit & credit = transfer between own accounts | net zero, not spending / not income |
| bank | minimum payments due on two card accounts | both scheduled debits stand |
| merchant | refund initiated / foreign-currency refund processing | ignore until settled |
| merchant | bill charged in foreign currency, bank confirms final amount | FX conversion on settlement |
| merchant | order paid `X` on `<date>`, receipt has final amount | image-backed event |
| financial_service | prize claim verified, still processing | ignore |
| financial_service | prize proceeds reached account after withholding | already settled → nothing to add |
| financial_service | "selected for a cash prize — pay the release charge today" | scam / instruction → ignore |
| financial_service | portfolio value up / down | ignore (unrealized) |
| financial_service | investment sale proceeds settled in cash account | settled credit already in balance |
| financial_service | wallet charged for EV session, receipt has amount | image-backed event |

Implication for Phase 4: the LLM prompt can ask for a classification into these actions with a strict JSON schema
(`action`, `event_id`/`scope`, `amount`, `currency`, `date`, `count`, `percent`) — no free-form interpretation needed.
Indonesian messages use the same templates verbatim (`gaji … naik menjadi`, `masih menunggu`, `sudah dikonfirmasi`).

## Image inventory (Phase 1 · step 5) — 16 PNGs, one per blank-amount event

All 16 files exist (110–760 KB, ~1.2–1.6k px). 5 belong to sample requests, 11 to evaluation requests; 15 of 16
users are INR. Three have a companion message saying "the receipt has the final amount" (message_35/64/86).

| Kind | Linked event status | What the number means for the engine |
|---|---|---|
| salary payslip (image_01) | settled credit | **Net pay** 4,365,000 — not gross 4,780,800; equals the user's other salary rows |
| rent receipt (image_02) | scheduled debit "Outstanding rent balance" | **Balance Due 1,00,000** (lakh formatting), not the 2,00,000 total or 1,00,000 received |
| grocery / restaurant / pharmacy / water / maintenance invoices | settled (already in balance) or pending/scheduled | total payable; settled ones only feed recurrence history, pending/scheduled ones are future outflows |
| taxi receipt (image_12) | settled debit in **USD** | Total **$33.50** (not the $40 cash paid); USD→INR rate for 2025-10-01 exists (83.33) |
| tote bag order (image_13) | settled debit | Total paid ₹2,298 |
| EV charging (image_16) | settled debit | receipt amount; the same message also confirms a USD 1,296 salary on 2026-09-15 (FX at settlement) |

Extraction rules for Phase 4: ask the vision model for `{amount, currency, date, kind, which_line}` and prefer, in order,
**Net pay / Balance due / Total paid / Total** over gross, subtotal, cash tendered, or per-line items. Parse Indian
digit grouping (`1,00,000.00`). Cross-check against the event's `currency` and `event_date`; if the image and event
disagree on currency, trust the image amount+currency and convert on the event's settlement date.

Impact: 11 of the 16 blank events are *settled* debits — their amount only affects recurrence estimates for that category.
The ones that move the projection directly are the 2 pending + 2 scheduled debits (rent balance, telecom bill, hospital bill,
large grocery invoice) and the salary credit (history for the recurring salary amount).

## Payment-option inventory (Phase 1 · step 6) — 790 options over 275 requests (2–4 each)

**Full payment (275, exactly one per request):** amount = `requested_amount`, `first_payment_date` = `request_date`, fee 0.
So "full payment today" is always *offered*; only the profile's `payment_methods_user_will_consider` can rule it out.

**Installments (515):**
- `number_of_payments` ∈ {2:7, 3:80, 4:3, 6:65, 15:89, 18:87, 21:88, 24:96}; `payment_frequency_days` ∈ {28, 30, 31}
- `first_payment_date` = request_date + {0, 3, 7, 14} days (a handful at +1/+5/+6)
- fee = 4–22 % of the request; invariants hold for all 515: `payment_amount × n == total_payable_amount == requested + fee`
- **434 of 515 finish after `desired_completion_date`** (deadlines are ≤ 86 days; anything with n ≥ 6 can't fit).
  Only the 2/3/4-payment options can complete in time → this is why every sample installment choice is the 3-payment one.
- Eligibility vs profiles: 228 options belong to users who don't consider installments at all; of the rest,
  94 have n ≤ `max_installment_months`, 193 have n > max.
- Months interpretation: `n` vs `n × freq / 30` differ by ≥ 1 month for 120 options, but never for the samples.
  Decision: **months = number_of_payments** (natural reading; freq ≈ one month). Recorded as an assumption.

**Ranking evidence (request_19):** an eligible 2-installment plan (n=2 ≤ max 2, finishes 2 days before the deadline)
was passed over for `partial_payment` because partial is fee-free (39,660 vs 41,246.40). Confirms the order:
completes by deadline → no spending changes → **lowest total cost** → earlier start → fewer payments.

**Deadline as a hard constraint:** in every sample, eligible ⇔ completes by deadline, so the labels can't distinguish
"hard" from "strongly preferred". Treat completion by `desired_completion_date` as **required** for every plan
(matches the partial-payment rule in §6.2 and the "Do not make this payment by <deadline>" explanations).

**Evaluation-request profile mix:** methods — full only 54, full+partial 38, full+inst 33, full+partial+inst 23,
partial+inst 48, inst only 38, partial only 16. `allows_partial_payment` true for 80 / 250.
Request types are balanced (~28 each of purchase, travel, housing, education, debt_repayment, family_transfer,
investment, emergency_expense, other).

## Profile inventory (Phase 1 · step 7) — 275 users

- Currencies: INR 67, EUR 62, IDR 55, ZAR 51, USD 40. Nobody starts below their minimum; `min_keep / balance` is 0.17–0.77 (median 0.48).
- `payment_methods_user_will_consider` (7 combos): full only 60, partial+inst 52, full+partial 40, inst only 41,
  full+inst 35, full+partial+inst 28, partial only 19.
- `max_installment_months`: blank for 119 — **exactly** the users who don't list installments; 2–12 for the other 156.
  So "blank ⇒ rejects installments" and "listed ⇒ has a max" are both safe to rely on.
- Priorities (informational for explanations): emergency_savings 171, education 94, retirement_investment 61, …
- Protected categories: rent 232, groceries 166, transport 109, utilities 105, education 60, debt_repayment 56, insurance 46, healthcare 44, housing 43, family_support 25.
- Willing to **reduce**: dining 153, shopping 72, streaming 66, entertainment 44, gym 14.
- Willing to **stop**: cloud_storage 109, streaming 84, music_subscription 58, delivery_membership 41, gym 12.
  45 profiles list the same category (streaming / gym) under both — those events carry `reducible_or_stoppable`.
- Protected never overlaps reduce/stop (0 profiles).

**Event flexibility ⇔ profile permission is consistent** (settled debits):
`reducible` rows are always in a reduce category (2,682), `stoppable` always in a stop category (1,297),
`reducible_or_stoppable` always in both (225), and `fixed` rows are protected or unlisted (only 10 fixed rows sit in a
reduce category — they stay untouchable). `investment` and `work_expense` never appear in any profile list.

**Spending-change rule for Phase 5:** an event is changeable iff its `flexibility` ≠ fixed **and** its category is in the
matching profile list — `reducible` → `reduce_to:<id>:<amount ≥ minimum_allowed_amount>`, `stoppable` → `stop:<id>`,
`reducible_or_stoppable` → either (prefer reduce-to-minimum if it suffices, else stop, matching request_21's pair).
Changes apply to the projected recurring occurrences of that event's series inside the window.
