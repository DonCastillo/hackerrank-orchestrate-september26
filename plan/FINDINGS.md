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
