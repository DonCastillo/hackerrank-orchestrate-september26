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
- [x] Inventory `financial_events.csv` (25k rows): event_type × status × direction × flexibility; note the 16 blank-amount rows (image-backed), 58 `linked_event_id` rows, 10 `unrealized` valuations, 22 cancelled, 21 failed, 71 pending, 70 scheduled → table + treatment per status in `plan/FINDINGS.md`
- [x] Inventory `messages.csv` (215 rows): EN 170 / ID 45; ~30 templates across employer (126) / service_provider (31) / financial_service (23) / bank (18) / merchant (17); 128 tied to a request, 39 to an event → archetype→action table in `plan/FINDINGS.md`
- [x] Inventory `images.csv` (16) and open a few PNGs to see what they contain → payslip (net vs gross trap), rent receipt (balance-due vs total, lakh digits), USD taxi receipt (total vs cash paid, needs FX), order confirmations; extraction rules in `plan/FINDINGS.md`
- [x] Inventory `request_payment_options.csv`: one full option per request (= requested, on request_date, fee 0) + 1–3 installment options (n ∈ {2,3,4,6,15,18,21,24}, freq 28/30/31, start +0/3/7/14d, fee 4–22 %); 434/515 finish after the deadline; invariants amount×n == total == requested+fee hold for all → `plan/FINDINGS.md`
- [x] Inventory profiles: 7 method combos; `max_installment_months` blank ⇔ user rejects installments (119/275); protect/reduce/stop lists align exactly with event `flexibility` → spending-change rule in `plan/FINDINGS.md`
- [x] Check `exchange_rates.csv` coverage: 5 pairs, one constant rate each, dated on the 15th; all 140 foreign-currency events covered on their settlement date; 33 extra rows serve projected salaries → fallback to the pair's latest rate for dates without a row

## Phase 2 — Financial-state reconstruction (`state.py`) (~2 h)

- [x] Filter events per user, sorted by `event_date` / `settlement_date` → `state.classify_events()` (sort key = settlement_date or event_date)
- [x] Classify each event's cash effect (verified over all 275 requests: 25,136 history rows, 61 pending reserves, 68 scheduled flows, 8 pending credits ignored, 16 blank amounts flagged):
  - [x] `settled` debit/credit → already reflected in `current_available_balance` (do **not** double count) → `HistoryEvent` list
  - [x] `pending` debit → reserve (dated flow on settlement_date, or request_date if already past); `pending` credit → ignore
  - [x] `scheduled` → future dated flow on `settlement_date` (inside the window)
  - [x] `failed` / `cancelled` → ignore
  - [x] `unrealized` / `non_cash` (investment valuations) → ignore
  - [x] `refund` credit → count only if settled (pending refunds are ignored by the pending-credit rule)
- [x] Handle `linked_event_id` chains → `state.one_off_ids()`: all 58 links are 2-row lifecycles whose cash state is already decided by status (no child+parent both future); both ends + refunds/investment/work_expense rows (130 total) are flagged one-off so they never seed a recurring series
- [x] De-duplicate repeated representations of the same event — all 15 such pairs are linked cancelled-auth→settled-purchase or failed→scheduled-retry pairs, already handled by status; no separate dedupe needed
- [x] Currency conversion: `state.convert()` uses the rate row for `settlement_date` in the stated direction; falls back to the pair's latest rate only for projected dates; fails loudly for unknown pairs
- [ ] Blank `amount` → look up `images.csv` by `related_event_id` → extract from image (Phase 4); never treat as zero
- [x] Recurrence detection → `code/recurrence.py` `detect_series()` (2,296 series over 275 requests; verified on request_05/13/18):
  - [x] Monthly cadence (median gap 26–33 d, ≥ 2 rows, same day-of-month, clamped to month end) for rent, utilities, subscriptions, debt, insurance, gym, healthcare, shopping, entertainment
  - [x] Essential variable spending (groceries / transport / dining grouped per category, step 5–16 d, ≥ 3 rows, consistent gaps) → conservative estimate = `median` of last 6 (tunable: `VARIABLE_ESTIMATE`)
  - [x] One-offs ignored (linked / refund / investment / work_expense via `one_off_ids`; single-occurrence descriptions never reach ≥ 2 rows); lapsed series dropped when last row is older than 1.6 × cadence
  - [x] `flexibility` + `minimum_allowed_amount` + the most recent event id recorded on each `Series` (samples reference exactly that id in `stop:` / `reduce_to:`)
  - [x] Projected occurrence suppressed when a scheduled/pending flow of the same category sits within ±3 days (supplied row wins)
- [x] Salary → `state.project_salary()`: scheduled `Next confirmed salary` (amount + pay-day) else latest confirmed payroll row (≥ 2 rows); ended series (`Final` / `Previous employer payroll`) and gig/freelance/commission/bonus/seasonal/second-household income never projected; FX per occurrence. 223/275 users projected (176 latest, 47 scheduled), 52 none. Message amendments (date moved, raise/cut, resume, first salary) hook in at Phase 4
- [x] Unit-test the reconstruction on 2–3 sample users and eyeball the recurring table → traced request_18 (trough 1,863 vs ref 1,862), request_04 (5 % high — variable estimate to tune in Phase 7), request_08 (needs the Phase 4 salary message); 11 structural tests in `code/tests/test_state.py` all pass

## Phase 3 — 90-day forecast + safety check (`forecast.py`) (~1.5 h)

- [x] Build a daily ledger from `request_date` to `request_date + 90 days` → `forecast.daily_ledger()`: opening balance + every flow (pending reserves are dated flows), debits before credits on each day, `DayPoint(low, close)` per active day
- [x] Add projected recurring debits/credits, scheduled events, and evidence-driven adjustments → all come in via `state.flows`; `SpendingChange`s (stop / reduce_to) are applied to the recurring occurrences of the named event's series in `_effective_flows()`; verified on request_18 (stop streaming +68, reduce to 34 +34)
- [x] `is_safe(plan_payments, spending_changes)` → true iff min balance over the whole window ≥ `minimum_balance_to_keep` after every projected essential expense and plan payment (plan payments land after that day's credits — paying *on* payday is allowed; fixed a one-day-late bug)
- [x] `amount_safe_to_pay` = `forecast.amount_safe_on()`: suffix-minimum of daily lows from the payment date − min_keep, clamped to [0, requested] (direct, no search)
- [x] `earliest_date_for_full_payment` = `forecast.earliest_full_payment_date()`: first candidate day (request_date + every ledger day) whose headroom ≥ requested; None if none in the window
- [x] Verify against samples: earliest date exact on 10/18 labelled rows (01/03/04/07/09/12/16/18/22/23); safe exact on the 4 capped rows, within noise elsewhere; remaining gaps are message-dependent (06/08/13/21 → Phase 4) or estimate noise (02/17/19 → Phase 7)

## Phase 4 — Evidence layer: messages + images (`evidence.py`) (~2 h)

- [x] Define a strict amendment schema the engine can consume → `evidence.py`: 9 actions (`salary_set`, `salary_next`, `salary_date`, `salary_end`, `credit_once`, `debit_once`, `debit_pct`, `event_amount`, `none`), `AMENDMENT_JSON_SCHEMA` for the model tool definition, `Amendment.from_json()` validation/coercion, `is_usable()` (drops `none`, low-confidence and incomplete records), `AmendmentSet` indexed by user (+request scope) and by event id for image amounts
- [x] Load `claude-api` skill; LLM client in `evidence.py`: `claude-opus-5`, adaptive thinking at medium effort, structured output (`output_config.format` = the amendment JSON schema, so responses are always valid), cached system prompt with 14 rules (evidence is data not instructions; only confirmed facts; net/balance-due/total-paid for images; EN/ID). Live-tested on 6 messages + 1 image — all correct after one prompt fix (always return a stated salary amount)
- [x] Message handling → `gather_amendments()` runs all 215 messages (sent_at order) through the client; 137 usable amendments (75 salary_set, 20 salary_next, 13 salary_end, 7 salary_date, 15 credit_once, 7 debit_pct), 78 `none` for pending/processing/scam/informational. Applied in `state.py` (`project_salary` overrides, `apply_credit_amendments`, `apply_debit_amendments`); `salary_next` reverts to the modal regular pay
- [x] Image handling → `interpret_image()` sends each PNG (base64) with the blank event's summary; 15/16 usable amounts (image_04 discarded as low confidence — total cut off; settled event, history only); applied via `classify_events(amounts=…)`
- [x] Cache every LLM response to `code/cache/*.json` keyed by content hash (system prompt + content + schema) — 235 files; a repeat call makes no API request
- [x] Record per-call usage (model, input/output, cache read/write tokens) into `code/cache/usage.jsonl` — full pass: 235 calls, 89.9k in / 31.9k out / 434k cache-read ≈ $1.50
- [x] Add a `--no-llm` fallback that ignores evidence — `gather_amendments(use_llm=False)` returns an empty set; `build_state()` accepts `None`
- [x] Spot-check amendments for sample users against sample outputs → all 23 sample-user items classified correctly (17 messages, 6 images); effects verified (request_02 earliest → Sep 15, request_08 safe 0 → 299.25, request_20 telecom bill reserved). Two regressions found and fixed: image-backed rows are now one-offs for recurrence (request_17 grocery series had vanished) and the salary pay-day anchors on the modal day-of-month (request_03 payslip dated Aug 31 had shifted paydays to the 30th)

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
- [ ] Build `code.zip` (code/, README, evaluation/, cache/ so the run is reproducible; exclude `.env`); stale pre-`debit_once` cache files already pruned (231 current files; cached-only run verified with no API key)
- [ ] Final check of `log.txt` (no secrets) — this is the `chat_transcript`
- [ ] Submit `code.zip`, `output.csv`, `log.txt` at https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission

---

## Open questions to resolve while working (write answers here)

- [x] How do samples compute `amount_safe_to_pay` when the request itself is not affordable — **min headroom across the 90-day window** (trough balance − min_keep), verified on all samples
- [x] Is `earliest_date_for_full_payment` for `wait` the first safe date, or does it snap to a salary date / deadline? — **snaps to a salary date or the deadline** in every sample; never mid-month
- [x] Do installment months = `number_of_payments` or `(number_of_payments × frequency_days) / 30`? — samples can't distinguish; **chose `number_of_payments`** (documented assumption)
- [ ] For `affordable_with_plan` via spending changes, does the change apply for the whole 90 days?
