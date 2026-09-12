"""Phase 2 (steps 5–6) — detect recurring debit series in settled history and project them.

Rules (plan/FINDINGS.md):
  * A series is (category, description) for fixed-type categories and (category) for the
    variable essentials groceries / transport / dining, which rotate descriptions.
  * Recurrence needs history: >= MIN_OCCURRENCES rows with a consistent gap, and the last
    occurrence no older than STALE_FACTOR x cadence before request_date (else it has lapsed).
  * Monthly series repeat on the same day-of-month; shorter cadences repeat every `step` days
    from the last occurrence.
  * Amount: constant series use their exact amount; variable series use a conservative
    central estimate of recent history (VARIABLE_ESTIMATE), quantised to 2 dp.
  * One-off rows (links, refunds, investments, work expenses) never seed a series.
  * A projected occurrence is suppressed when a real scheduled/pending flow of the same
    category already sits within SUPPRESS_DAYS of it (the supplied row wins).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median, mean
from typing import Optional

from loader import Event
from money import q

VARIABLE_CATEGORIES = {"groceries", "transport", "dining"}
MIN_OCCURRENCES = 2          # monthly series (rent, subscriptions) show 5–6 rows; 2 is the floor
MIN_OCCURRENCES_SHORT = 3    # weekly / biweekly series need a bit more support
STALE_FACTOR = Decimal("1.6")
SUPPRESS_DAYS = 3
RECENT_N = 6                 # how many recent rows feed the variable estimate
VARIABLE_ESTIMATE = "median" # median | mean | max  (tunable via score_samples)


@dataclass(frozen=True)
class Series:
    key: tuple[str, str]               # (category, description or '*')
    category: str
    cadence: str                       # 'monthly' | 'days'
    step_days: Optional[int]           # for 'days'
    amount: Decimal                    # projected per-occurrence amount (positive)
    constant: bool
    last_on: date
    last_event: Event                  # id used for stop:/reduce_to:
    flexibility: str
    minimum_allowed_amount: Optional[Decimal]
    occurrences: tuple[date, ...]      # projected dates inside the window


def _estimate(amounts: list[Decimal]) -> Decimal:
    recent = amounts[-RECENT_N:]
    if VARIABLE_ESTIMATE == "mean":
        v = mean(recent)
    elif VARIABLE_ESTIMATE == "max":
        v = max(recent)
    else:
        v = median(recent)
    return q(Decimal(v))


def add_months(d: date, k: int) -> date:
    m = d.month + k
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def _cadence(dates: list[date]) -> Optional[tuple[str, Optional[int]]]:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    if not gaps:
        return None
    g = median(gaps)
    if 26 <= g <= 33:
        return ("monthly", None)
    if 5 <= g <= 16 and len(dates) >= MIN_OCCURRENCES_SHORT:
        step = int(round(g))
        # gaps must be reasonably consistent (weekly shopping is never exactly regular)
        if all(abs(x - step) <= 3 for x in gaps[-4:]):
            return ("days", step)
    return None


def detect_series(history: list, one_off_ids: set[str], request_date: date, window_end: date,
                  existing_flows: list) -> list[Series]:
    """`history` is a list of state.HistoryEvent (settled, home currency). Returns projected series."""
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for h in history:
        e = h.event
        if e.direction != "debit" or e.event_id in one_off_ids or h.on > request_date:
            continue
        key = (e.category, "*" if e.category in VARIABLE_CATEGORIES else e.description)
        groups[key].append(h)

    covered = [(f.category, f.on) for f in existing_flows if f.kind in ("scheduled", "pending_reserve")]
    out: list[Series] = []
    for key, rows in groups.items():
        rows.sort(key=lambda h: (h.on, h.event.event_id))
        dates = [h.on for h in rows]
        if len(dates) < MIN_OCCURRENCES:
            continue
        cad = _cadence(dates)
        if cad is None:
            continue
        step = 30 if cad[0] == "monthly" else cad[1]
        if (request_date - dates[-1]).days > STALE_FACTOR * step:
            continue  # lapsed series
        amounts = [-h.amount for h in rows]
        constant = len(set(amounts[-3:])) == 1
        amount = amounts[-1] if constant else _estimate(amounts)

        occ: list[date] = []
        if cad[0] == "monthly":
            k = 1
            while True:
                d = add_months(dates[-1], k)
                if d > window_end:
                    break
                if d >= request_date:
                    occ.append(d)
                k += 1
        else:
            d = dates[-1] + timedelta(days=step)
            while d <= window_end:
                if d >= request_date:
                    occ.append(d)
                d += timedelta(days=step)
        occ = [d for d in occ if not any(c == key[0] and abs((d - on).days) <= SUPPRESS_DAYS for c, on in covered)]
        if not occ:
            continue
        last = rows[-1].event
        out.append(Series(
            key=key, category=key[0], cadence=cad[0], step_days=cad[1], amount=amount, constant=constant,
            last_on=dates[-1], last_event=last, flexibility=last.flexibility,
            minimum_allowed_amount=last.minimum_allowed_amount, occurrences=tuple(occ),
        ))
    out.sort(key=lambda s: (s.occurrences[0], s.category))
    return out
