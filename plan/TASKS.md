# TASKS — Buy or Wait? (HackerRank Orchestrate, Sept 2026)

Deadline: **2026-09-13 18:00 IST**. Deliverables: `output.csv` (250 rows), `code.zip` (with `code/evaluation/usage_report.md` + README), `log.txt` as chat transcript.

Strategy in one line: **deterministic Python engine does all the money math; an LLM is used only where text/images need interpreting (messages + 16 images) and to write `decision_explanation`.** Evaluation is numeric-heavy, so the engine must be exact and reproducible.

---

## Phase 0 — Setup (~30 min)

- [x] Confirm Python 3 + `pip`; create `code/requirements.txt` (stdlib-only for the engine; `anthropic` + `python-dotenv` for the LLM layer) — Python 3.14 locally; `pyproject.toml` requires >=3.10; exact pins in `code/requirements.lock.txt`; `python bootstrap.py` creates `.venv/` + installs + runs on any OS
- [x] Create `.env.example` with `ANTHROPIC_API_KEY=` (never commit `.env`; confirm `.gitignore` covers `.env` and `log.txt`)
- [x] Scaffold `code/` modules (all import cleanly; `validate.py`, `score_samples.py`, `usage_report.py` fully implemented; the rest raise `NotImplementedError("Phase N")`):
  - [x] `code/main.py` — CLI entry: `--no-llm`, `--limit N`, `--request-ids ...`, `--output`, `--validate`, `--score-samples`, `-v` → writes root `output.csv`
  - [x] `code/config.py` — paths, output columns, enums, 90-day horizon
  - [x] `code/loader.py` — all `dataset/*.csv` → frozen dataclasses, Decimal money (verified: 275 profiles, 25,342 events, 250 requests, 25 samples, 790 options, 215 messages, 16 images)
  - [x] `code/state.py` — `build_state()` + `convert()` (Phase 2)
  - [x] `code/forecast.py` — `daily_balances / is_safe / amount_safe_on / earliest_full_payment_date` (Phase 3)
  - [x] `code/planner.py` — `Decision` dataclass with `to_row()`; `decide()` (Phase 5)
  - [x] `code/evidence.py` — `Amendment`/`AmendmentSet`, content-hash cache + `usage.jsonl`; `gather_amendments()` (Phase 4)
  - [x] `code/explain.py` — `explain()` (Phase 6)
  - [x] `code/validate.py` — full contract checks; verified 0 problems on the 25 ground-truth samples
  - [x] `code/score_samples.py` — column-by-column diff vs `sample_requests.csv`
  - [x] `code/usage_report.py` — builds `code/evaluation/usage_report.md` from `cache/usage.jsonl`
- [x] Decide rounding convention and centralize it → `code/money.py`: Decimal everywhere, `q()` = 2 dp ROUND_HALF_UP after any multiplication; `fmt_safe()` minimal digits for `amount_safe_to_pay` (17229139.2 / 462); `fmt_plan()` 2 dp-if-fractional for plan + reduce_to amounts (620.40 / 23.50 / 25256). Verified 0 mismatches across all 25 samples

## Phase 1 — Understand the data (~45 min)

- [x] Walk through all 25 rows of `sample_requests.csv` by hand for 3–4 users; reverse-engineer how `amount_safe_to_pay`, `earliest_date_for_full_payment`, and the chosen plan were derived → see `plan/FINDINGS.md` (core formula, 90-day window, salary rules, trough logic; exact variable-spend estimates are not reproducible — timeboxed)
- [x] Confirm the exact meaning of "at least X available" in sample explanations (X == `minimum_balance_to_keep`) — confirmed on all 25
- [ ] Inventory `financial_events.csv` (25k rows): event_type × status × direction × flexibility; note the 16 blank-amount rows (image-backed), 58 `linked_event_id` rows, 10 `unrealized` valuations, 22 cancelled, 21 failed, 71 pending, 70 scheduled
- [ ] Inventory `messages.csv` (215 rows): multilingual (EN / ID / others); sources = employer, service_provider, financial_service, bank, merchant; 128 tied to a request, 39 tied to an event
- [ ] Inventory `images.csv` (16) and open a few PNGs to see what they contain (payslips, bills, statements)
- [ ] Inventory `request_payment_options.csv`: 2–4 options per request; `full_payment` vs `installments`; note `first_payment_date`, `payment_frequency_days`, `number_of_payments`, `total_payable_amount`
- [ ] Inventory profiles: `payment_methods_user_will_consider` combos; `max_installment_months` blank for 119/275 users
- [ ] Check `exchange_rates.csv` coverage: which (date, from, to) pairs exist; confirm every foreign-currency cash event has a rate on its settlement date

## Phase 2 — Financial-state reconstruction (`state.py`) (~2 h)

- [ ] Filter events per user, sorted by `event_date` / `settlement_date`
- [ ] Classify each event's cash effect:
  - [ ] `settled` debit/credit → already reflected in `current_available_balance` (do **not** double count)
  - [ ] `pending` debit → reserve (subtract from projection); `pending` credit → ignore
  - [ ] `scheduled` → future dated flow on `settlement_date`
  - [ ] `failed` / `cancelled` → ignore
  - [ ] `unrealized` / `non_cash` (investment valuations) → ignore
  - [ ] `refund` credit → count only if settled
- [ ] Handle `linked_event_id` chains (cancellation/settlement/amendment of an earlier event; investment lifecycle) — the newer linked row wins
- [ ] De-duplicate repeated representations of the same event (same user/amount/date/description with different status)
- [ ] Currency conversion: for a cash event in a currency ≠ `home_currency`, use the rate row for `settlement_date` and the exact `from_currency → to_currency` direction; fail loudly if missing
- [ ] Blank `amount` → look up `images.csv` by `related_event_id` → extract from image (Phase 4); never treat as zero
- [ ] Recurrence detection (per user × category × description):
  - [ ] Detect monthly cadence (same day-of-month ± a few days, ≥ 2–3 occurrences) for rent, utilities, subscriptions, debt payments, insurance, gym, salary
  - [ ] Detect essential variable spending (groceries, transport, dining) → forecast conservatively (e.g. monthly max or upper-quantile of recent months)
  - [ ] Ignore one-offs (shopping, windfall, refund, work_expense) unless scheduled
  - [ ] Record `flexibility` + `minimum_allowed_amount` for each recurring debit so the planner knows what can be stopped/reduced
- [ ] Salary: find the next confirmed salary (scheduled income row) and project the recurrence on its settlement day-of-month; apply message amendments (date moved, amount raised/reduced, bonus pending → ignore)
- [ ] Unit-test the reconstruction on 2–3 sample users and eyeball the recurring table

## Phase 3 — 90-day forecast + safety check (`forecast.py`) (~1.5 h)

- [ ] Build a daily ledger from `request_date` to `request_date + 90 days`: start balance = `current_available_balance` − reserved pending debits
- [ ] Add projected recurring debits/credits, scheduled events, and evidence-driven adjustments
- [ ] `is_safe(plan_payments, spending_changes)` → true iff min balance over the whole window ≥ `minimum_balance_to_keep` after every projected essential expense and plan payment
- [ ] `amount_safe_to_pay` = max amount payable on `request_date` (no spending changes) that keeps the window safe, capped at `requested_amount`, floored at 0 (binary search or direct: min-over-window headroom)
- [ ] `earliest_date_for_full_payment` = first date in the window where a single full payment is safe without spending changes (empty if none)
- [ ] Verify against samples: request_01 (affordable_now), request_03/04 (wait), request_05/10 (not_affordable), request_19 (partial)

## Phase 4 — Evidence layer: messages + images (`evidence.py`) (~2 h)

- [ ] Define a strict amendment schema the engine can consume, e.g. `{event_id | scope, action: cancel|amend_amount|amend_date|confirm|pending, amount, date, confidence}`
- [ ] Load `claude-api` skill; use Claude (Sonnet 5 for cost, Opus 5 if needed) with structured output; treat message/image text as untrusted data — system prompt says embedded instructions never override rules
- [ ] Message handling: translate/interpret multilingual employer/bank/provider messages into amendments; ignore anything that is "pending / not yet approved / may change"
- [ ] Image handling: send each of the 16 PNGs to a vision call; extract amount + date + currency; map back to the blank-amount event via `related_event_id`
- [ ] Cache every LLM response to `code/cache/*.json` keyed by content hash so re-runs are deterministic and cheap
- [ ] Record per-call usage (model, input/output tokens) into `code/cache/usage.jsonl` for the usage report
- [ ] Add a `--no-llm` fallback that ignores evidence (engine still produces a valid, safer output)
- [ ] Spot-check amendments for sample users against sample outputs (e.g. request_03 image → event_253 amount)

## Phase 5 — Plan generation & ranking (`planner.py`) (~2 h)

- [ ] Enumerate candidate plans:
  - [ ] `full_payment` on `request_date` (only if user considers `full_payment`)
  - [ ] `full_payment` with spending changes (stop/reduce flexible events in permitted categories, max 3, stop and reduce on different events, `reduce_to` ≥ `minimum_allowed_amount`)
  - [ ] `partial_payment`: exactly two payments — `amount_safe_to_pay` on `request_date`, remainder on `earliest_date_for_full_payment`; only if `allows_partial_payment`, user considers it, `0 < safe < requested`, and second date ≤ `desired_completion_date`
  - [ ] `installments`: each supplied installment option, expanded to `first_payment_date + k*frequency_days` × `number_of_payments`; reject if user doesn't consider installments, if months > `max_installment_months`, or if the schedule is unsafe / completes after `desired_completion_date`
  - [ ] `wait`: full payment on `earliest_date_for_full_payment` if ≤ `desired_completion_date`… and also handle the sample pattern where `wait` is recommended on the deadline itself (request_03, 08, 13, 18, 23) — verify how the samples treat wait-date vs deadline
- [ ] Rank safe plans by: completes by deadline → no spending changes → lowest total paid → earliest start → fewer payments → lowest `payment_option_id`
- [ ] Derive `affordability_status` from the chosen plan (`affordable_now` / `affordable_with_plan` / `affordable_later` / `not_affordable`)
- [ ] Fallback `not_recommended` + `payment_plan=none` when nothing safe & eligible
- [ ] Amount formatting: match sample style (e.g. `620.40`, `15952906.67`, whole IDR)

## Phase 6 — Explanation (`explain.py`) (~45 min)

- [ ] Template explanations that mirror sample phrasing per method (full/partial/installments/wait/not_recommended, with/without spending changes), including currency, amounts, dates, and the minimum balance figure
- [ ] Optional LLM polish pass (Haiku 4.5 / Sonnet 5) constrained to the facts in the template; skip if time is short

## Phase 7 — Validation & self-scoring (~1 h)

- [ ] `validate.py`: exact header order; one row per `request_id`; `0 ≤ amount_safe_to_pay ≤ requested_amount`; allowed enum values; `payment_plan` chronological and sums to `requested_amount`; installments match a supplied option exactly; partial = 2 payments; `earliest_date == request_date` for `affordable_now`; spending changes reference flexible events in permitted categories, ≤ 3, no stop+reduce on same event
- [ ] `score_samples.py`: run the engine on the 25 sample requests and diff every output column; iterate on Phases 2–5 until the samples match (target: all numeric fields exact)
- [ ] Log mismatches to `plan/SAMPLE_DIFF.md` so we know what's still off

## Phase 8 — Full run & submission (~1 h)

- [ ] Run full dataset: `python3 code/main.py` → root `output.csv` (250 rows + header)
- [ ] Run `validate.py` on the final `output.csv`
- [ ] Generate `code/evaluation/usage_report.md` from `usage.jsonl`: providers, model names, call counts, input/output tokens, total & avg tokens per request, estimated total & per-request cost (per-model + overall)
- [ ] Write `code/README.md`: setup (`pip install -r requirements.txt`, `.env`), run command, module overview, determinism/caching notes
- [ ] Build `code.zip` (code/, README, evaluation/, cache/ so the run is reproducible; exclude `.env`)
- [ ] Final check of `log.txt` (no secrets) — this is the `chat_transcript`
- [ ] Submit `code.zip`, `output.csv`, `log.txt` at https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission

---

## Open questions to resolve while working (write answers here)

- [x] How do samples compute `amount_safe_to_pay` when the request itself is not affordable — **min headroom across the 90-day window** (trough balance − min_keep), verified on all samples
- [x] Is `earliest_date_for_full_payment` for `wait` the first safe date, or does it snap to a salary date / deadline? — **snaps to a salary date or the deadline** in every sample; never mid-month
- [ ] Do installment months = `number_of_payments` or `(number_of_payments × frequency_days) / 30`?
- [ ] For `affordable_with_plan` via spending changes, does the change apply for the whole 90 days?
