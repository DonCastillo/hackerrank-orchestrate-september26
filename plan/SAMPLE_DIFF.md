# SAMPLE_DIFF.md — engine vs `dataset/sample_requests.csv`

Run: `python3 bootstrap.py --score-samples` (cache-only, no API key needed).

## Score

| Setting | Columns exact (of 150) | Status exact (of 25) | Mean \|error\| in `amount_safe_to_pay` (% of headroom) |
|---|---:|---:|---:|
| untuned (median of last 6, debits before credits) | 102 | 18 | 4.9 % |
| **tuned** (weekly/biweekly variable × 0.9, credits before debits) | **118** | **22** | **4.7 %** |

Tuning grid: statistic {median, mean, trimmed mean, p75, max} × recent rows {3…12} × scale {0.7…1.1} × staleness
{1.6, 2.2} × same-day order × request-date inclusion. The two adopted settings (`recurrence.SHORT_CADENCE_SCALE`,
`forecast.SAME_DAY_ORDER`) were the only ones that raised exact matches without raising the average error; every
other knob was flat. They are documented constants, not hidden behaviour.

## What still differs (tuned)

| Sample | Columns off | Cause |
|---|---|---|
| 06 | status, method, plan, changes | engine gap to full payment 79 vs reference 17; the single 19-unit `stop` the label uses is not enough in our forecast |
| 11 | status, earliest, changes | engine finds full payment safe today; reference needs `reduce_to` (its spend estimate ≈ 2 % higher) |
| 21 | status, earliest, changes | same as 11 (31 units on a 2,111 headroom) |
| 19 | plan amounts | right method and dates (partial, remainder Sep 15); `safe` 26,608 vs 28,820 |
| 21 other rows | `amount_safe_to_pay` only | within a few % of headroom; the reference's variable-spend estimates are not reproducible exactly (see FINDINGS.md) |

`earliest_date_for_full_payment` matches on 15/18 labelled rows; `payment_plan` on 20/25; `spending_changes_needed` on 22/25;
`decision_explanation` is byte-identical on 14 rows and differs elsewhere only by the organisers' alternate phrasing or the amount.

## Not tuned on purpose

- Categorical logic (candidate set, ranking, status mapping) was not changed to fit the samples; the misses above all
  trace to the numeric estimate crossing a threshold.
- `--no-llm` (evidence ignored) scores lower (request_02/08/14 depend on employer messages); the shipped run uses the cache.
