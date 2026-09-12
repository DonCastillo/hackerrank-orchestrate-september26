# REPRODUCE.md — Running Buy or Wait? on any machine

This document is the exact, verified recipe for reproducing `output.csv` from a fresh clone
on macOS, Linux, or Windows. Follow it top to bottom; every step is deterministic.

---

## 1. Prerequisites

| Requirement | Version | How to check |
|---|---|---|
| Python | **3.10 or newer** | `python3 --version` (macOS/Linux) · `py --version` (Windows) |
| `venv` + `pip` modules | bundled with CPython | `python3 -m venv --help` |
| Internet access | first run only | needed once to download the pinned packages |
| Anthropic API key | any active key | only for the LLM evidence layer (see §4) |

Nothing else is required. No global `pip install`, no Conda, no Docker.

If Python is missing, install it from <https://www.python.org/downloads/> (tick
**"Add python.exe to PATH"** on Windows). Homebrew, `apt`, `pyenv`, and `uv`-managed
interpreters all work; the launcher only needs a 3.10+ interpreter on your `PATH`.

---

## 2. Get the code

```bash
git clone <this-repository-url> buy-or-wait
cd buy-or-wait
```

If you received `code.zip` instead, unzip it and `cd` into the folder that contains
`bootstrap.py`, `code/`, and `dataset/`.

Expected layout:

```text
.
├── bootstrap.py                 # one-command launcher (stdlib only)
├── pyproject.toml               # requires-python >= 3.10, pinned deps
├── .env.example                 # template for secrets
├── code/
│   ├── main.py                  # entry point (invoked by bootstrap.py)
│   ├── requirements.txt         # direct deps, exact pins
│   ├── requirements.lock.txt    # full transitive lock (what actually gets installed)
│   └── evaluation/usage_report.md
├── dataset/                     # provided input CSVs + media/images/
└── output.csv                   # produced by the run
```

---

## 3. Configure secrets

```bash
cp .env.example .env            # macOS / Linux
copy .env.example .env          # Windows (cmd)
```

Open `.env` and set your key:

```text
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is git-ignored and is never read by anything except the LLM evidence layer.
Secrets are read **only** from environment variables; the program never hardcodes them.

---

## 4. Run

### 4.1 One command (recommended)

```bash
python3 bootstrap.py            # macOS / Linux
py bootstrap.py                 # Windows
```

`bootstrap.py` is pure standard library and performs, in order:

1. Verifies the interpreter is Python ≥ 3.10 (exits with a clear message otherwise).
2. Creates an isolated virtual environment at `./.venv` if it does not exist.
3. Installs the **exact** versions listed in `code/requirements.lock.txt`
   (skipped on later runs unless that file's SHA-256 changes).
4. Executes `code/main.py` inside `.venv`, forwarding any extra arguments.

The result is written to `./output.csv` (250 rows + header).

### 4.2 Useful flags

All flags are passed straight through to `code/main.py`:

```bash
python3 bootstrap.py --no-llm                    # deterministic engine only; skips messages/images interpretation
python3 bootstrap.py --limit 10                  # first 10 requests only (smoke test)
python3 bootstrap.py --request-ids request_01 request_19
```

### 4.3 Manual alternative (if you prefer not to use the launcher)

```bash
python3 -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r code/requirements.lock.txt
python code/main.py
```

---

## 5. Determinism and reproducibility guarantees

- **Money math is pure Python** — no floating-point RNG, no time-of-day dependence;
  the same `dataset/` always yields the same numbers.
- **LLM calls are cached.** Every request to the Anthropic API is keyed by a hash of its
  full input and stored under `code/cache/`. A second run with the same dataset makes
  **zero** API calls and reproduces the identical `output.csv`. Ship `code/cache/` with
  `code.zip` and graders can reproduce the file without an API key.
- **`--no-llm`** produces a valid, financially safer `output.csv` with no network access
  at all (message/image evidence is ignored).
- **Dependency versions are locked** to the byte in `code/requirements.lock.txt`.
- **No organizer-only files** are read; only `dataset/*.csv` and `dataset/media/images/`.

---

## 6. Verify the output

```bash
python3 bootstrap.py --validate           # checks header order, enums, row count, plan sums, etc.
python3 bootstrap.py --score-samples      # compares engine output against dataset/sample_requests.csv
```

`output.csv` must have exactly this header:

```text
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

---

## 7. Token usage report

After a full run, `code/evaluation/usage_report.md` is regenerated from
`code/cache/usage.jsonl` and lists model providers/names, call counts, input/output tokens,
total and per-request averages, and estimated cost. It contains no secrets.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `Buy or Wait? needs Python >= 3.10` | Install a newer Python; run with `python3.12 bootstrap.py` if several are installed |
| `externally-managed-environment` from pip | You bypassed the launcher and used the system pip. Use `bootstrap.py` or the venv in §4.3 |
| `ANTHROPIC_API_KEY` missing / 401 | Check `.env` in the repo root, or run with `--no-llm` |
| Want a clean rebuild | Delete `.venv/` and rerun `bootstrap.py` |
| Want to force fresh LLM calls | Delete `code/cache/` (this will spend tokens again) |
