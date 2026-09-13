# Buy or Wait? — decision engine

Solution for the HackerRank Orchestrate (September 2026) challenge. For every row in
`dataset/requests.csv` it decides whether the user should pay in full, pay partially, use a
seller installment option, wait, or not proceed — and writes `output.csv` in the required format.

## How it works

```
dataset/*.csv ──► loader ──► evidence (Claude, cached) ──► state ──► forecast ──► planner ──► explain ──► output.csv
```

| Stage | File | What it does |
|---|---|---|
| Load | `loader.py` | every CSV → typed records; all money as `Decimal` |
| Evidence | `evidence.py` | each message / image is classified **once** by Claude Opus 5 (structured output) into one of 9 actions: `salary_set`, `salary_next`, `salary_date`, `salary_end`, `credit_once`, `debit_once`, `debit_pct`, `event_amount`, `none`. Message text is treated as untrusted data; only confirmed facts survive. Responses are cached under `cache/` |
| State | `state.py`, `recurrence.py` | reconstruct the user's position on `request_date`: settled rows are history, pending debits are reserved, scheduled rows are dated flows; recurring commitments (rent, loans, subscriptions, weekly groceries…) and confirmed monthly salary are projected 90 days ahead; evidence amendments applied; foreign amounts converted at the settlement-date rate |
| Forecast | `forecast.py` | day-by-day balance path; `amount_safe_to_pay` = lowest projected balance − `minimum_balance_to_keep`; earliest safe full-payment date; safety check for any candidate plan |
| Plan | `planner.py` | candidates = full today · full + fewest permitted spending cuts · partial (safe now + rest on the earliest safe date) · every seller installment option · wait; each must be offered by the seller, accepted by the user, finish by the deadline and keep the minimum intact; ranked by no-cuts → lowest cost → earlier start → fewer payments |
| Explain | `explain.py` | template sentences built only from the computed numbers (no model call) |

All money math is deterministic Python (stdlib only). The model is used solely to read messages and images.

## Setup

Requires Python ≥ 3.10. Unzip anywhere — `bootstrap.py`, `code/` and `dataset/` sit side by side inside the archive:

```text
.
├── bootstrap.py        # creates ./.venv, installs pinned deps, runs code/main.py
├── pyproject.toml
├── REPRODUCE.md        # step-by-step reproduction guide
├── .env.example
├── code/               # this package (+ cache/, evaluation/, tests/)
└── dataset/            # the challenge data (included in code.zip; replace with your copy if you have one)
```

Optional — only needed to interpret evidence that is **not** already cached:

```bash
cp .env.example .env      # then set ANTHROPIC_API_KEY=...
```

## Run

```bash
python3 bootstrap.py                 # full run -> ./output.csv  (+ code/evaluation/usage_report.md)
python3 bootstrap.py --validate      # check ./output.csv against the output contract
python3 bootstrap.py --score-samples # compare the engine with dataset/sample_requests.csv
python3 bootstrap.py --no-llm        # ignore messages/images entirely (safer, lower-scoring baseline)
python3 bootstrap.py --limit 10 -v   # first 10 requests, verbose
python3 bootstrap.py --request-ids request_26 request_40
```

Equivalent without the launcher: `python3 -m venv .venv && .venv/bin/pip install -r code/requirements.lock.txt && .venv/bin/python code/main.py`.

## Reproducibility

- `code/cache/*.json` holds every model response keyed by a hash of prompt + content + schema. With the cache
  present the full run makes **zero API calls** and completes in about a second, with or without an API key.
- `code/cache/usage.jsonl` records the calls that produced the cache; `code/evaluation/usage_report.md` summarises them
  (231 calls to `claude-opus-5`, ≈ $1.46 total, ≈ $0.006 per request).
- Deleting `code/cache/` and re-running re-interprets all 215 messages and 16 images (~12 minutes, needs a key).
  Classifications were identical across two independent passes.
- Secrets are read from environment variables (`.env` via `python-dotenv`) only; nothing is hard-coded.

## Tools

`code/tools/` holds the scripts behind the analysis: `dump_request.py` (inspect one request end to end),
`tune_samples.py` and `tune_structural.py` (the grid searches that set `SHORT_CADENCE_SCALE` and `SAME_DAY_ORDER`).
Run them from the repo root with the venv Python; they need no API key.

## Tests

```bash
.venv/bin/python -m unittest discover -s code/tests
```

11 structural checks on sample users (salary rules, pending/scheduled flows, recurrence, spending-change ids, trough).

## Accuracy on the public samples

`--score-samples`: 118 of 150 scored cells exact (status 22/25, method 23/25, plan 20/25, changes 22/25, earliest 22/25);
`amount_safe_to_pay` is within ~5 % of the user's headroom on average. Details and the reasons behind the remaining
differences are in `plan/SAMPLE_DIFF.md` and `plan/FINDINGS.md` (the reference's variable-spend constants are not
recoverable exactly; two documented settings — `recurrence.SHORT_CADENCE_SCALE`, `forecast.SAME_DAY_ORDER` — were tuned on the samples).

## Key assumptions

- Forecast window: 90 days from `request_date` (per the sample explanations).
- Only confirmed salary is projected (constant monthly payroll or a scheduled/confirmed next salary); gig, freelance,
  bonus and commission income count as zero until settled. After a temporary reduction the regular pay resumes.
- Completing by `desired_completion_date` is required for every plan; installment "months" = `number_of_payments`.
- An event may be stopped/reduced only if its `flexibility` allows it **and** its category is in the user's permitted list;
  `reduce_to` never goes below `minimum_allowed_amount`.
- Unverified claims in messages (prizes, "pay now", suspected theft) never change the numbers.
