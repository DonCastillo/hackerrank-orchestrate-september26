"""Phase 3 — daily balance projection + safety checks over the forecast window.

Ordering rule (plan/FINDINGS.md #6): on any given day, debits are applied before credits, so
the day's low point is `balance_before + debits`. This is the financially safer reading and
matches the samples (dining on payday counted before the salary lands).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from money import fmt_plan
from state import FinancialState


@dataclass(frozen=True)
class Payment:
    on: date
    amount: Decimal


@dataclass(frozen=True)
class SpendingChange:
    """stop:<event_id>  or  reduce_to:<event_id>:<new_amount>"""
    action: str                 # stop | reduce_to
    event_id: str
    new_amount: Optional[Decimal] = None

    def render(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{fmt_plan(self.new_amount)}"


@dataclass(frozen=True)
class DayPoint:
    on: date
    low: Decimal        # balance after the day's debits, before its credits
    close: Decimal      # balance at end of day


# --------------------------------------------------------------------------- #
# Step 1–2: daily ledger
# --------------------------------------------------------------------------- #

def _effective_flows(state: FinancialState, changes: Iterable[SpendingChange]) -> list[tuple[date, Decimal]]:
    """Apply spending changes to the projected recurring occurrences of the named event's series."""
    by_event = {c.event_id: c for c in changes}
    out: list[tuple[date, Decimal]] = []
    for f in state.flows:
        amt = f.amount
        c = by_event.get(f.source_event_id)
        if c is not None and f.kind == "recurring":
            if c.action == "stop":
                continue
            amt = -c.new_amount
        out.append((f.on, amt))
    return out


def daily_ledger(state: FinancialState, payments: Iterable[Payment] = (),
                 changes: Iterable[SpendingChange] = ()) -> list[DayPoint]:
    """Balance path over [request_date, window_end], one point per day that has any movement.

    Days with no movement are omitted; the balance is flat between points, so the minimum of
    `low` over the returned points is the true minimum over the window.
    """
    byday: dict[date, list[Decimal]] = defaultdict(list)
    for on, amt in _effective_flows(state, changes):
        byday[on].append(amt)
    for p in payments:
        byday[p.on].append(-p.amount)
    rd, end = state.request.request_date, state.window_end
    bal = state.opening_balance
    points: list[DayPoint] = [DayPoint(rd, bal, bal)]
    for d in sorted(byday):
        if d < rd or d > end:
            continue
        amts = byday[d]
        debits = sum((a for a in amts if a < 0), Decimal(0))
        credits = sum((a for a in amts if a > 0), Decimal(0))
        low = bal + debits
        bal = low + credits
        points.append(DayPoint(d, low, bal))
    return points


def minimum_balance(state: FinancialState, payments: Iterable[Payment] = (),
                    changes: Iterable[SpendingChange] = ()) -> tuple[Decimal, date]:
    pts = daily_ledger(state, payments, changes)
    worst = min(pts, key=lambda p: (p.low, p.on))
    return worst.low, worst.on


# --------------------------------------------------------------------------- #
# Step 3–5: safety, safe amount, earliest full-payment date  (next step)
# --------------------------------------------------------------------------- #

def is_safe(state: FinancialState, payments: list[Payment], changes: list[SpendingChange] = ()) -> bool:
    """True iff balance never drops below minimum_balance_to_keep across the window."""
    raise NotImplementedError("Phase 3 step 3")


def amount_safe_on(state: FinancialState, on: date) -> Decimal:
    """Largest single payment on `on` (no spending changes) that keeps the window safe, floored at 0."""
    raise NotImplementedError("Phase 3 step 4")


def earliest_full_payment_date(state: FinancialState, amount: Decimal) -> Optional[date]:
    """First date in the window where a single payment of `amount` is safe, or None."""
    raise NotImplementedError("Phase 3 step 5")
