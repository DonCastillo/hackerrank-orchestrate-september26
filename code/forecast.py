"""Phase 3 — daily balance projection + safety checks over the forecast window.

Same-day ordering (SAME_DAY_ORDER):
  "credits_first" (default, tuned on the samples — plan/SAMPLE_DIFF.md): salary and other credits
      land before that day's spending clears, so the day's low point is its closing balance.
  "debits_first": the stricter reading — projected debits hit before credits, so a payday has a
      dip before the salary arrives.
In both cases the user's own plan payment is applied last (after credits): "wait until payday"
pays after the salary lands.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from money import fmt_plan
from state import FinancialState


SAME_DAY_ORDER = "credits_first"   # credits_first | debits_first


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
    low: Decimal        # min(balance after the day's debits, balance at close)
    close: Decimal      # balance at end of day (after credits and plan payments)


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
    paid: dict[date, Decimal] = defaultdict(Decimal)
    for p in payments:
        paid[p.on] += p.amount
    rd, end = state.request.request_date, state.window_end
    bal = state.opening_balance
    points: list[DayPoint] = [DayPoint(rd, bal, bal)]
    for d in sorted(set(byday) | set(paid)):
        if d < rd or d > end:
            continue
        amts = byday.get(d, ())
        debits = sum((a for a in amts if a < 0), Decimal(0))
        credits = sum((a for a in amts if a > 0), Decimal(0))
        after_debits = bal + debits
        bal = after_debits + credits - paid.get(d, Decimal(0))
        low = bal if SAME_DAY_ORDER == "credits_first" else min(after_debits, bal)
        points.append(DayPoint(d, low, bal))
    return points


def minimum_balance(state: FinancialState, payments: Iterable[Payment] = (),
                    changes: Iterable[SpendingChange] = ()) -> tuple[Decimal, date]:
    pts = daily_ledger(state, payments, changes)
    worst = min(pts, key=lambda p: (p.low, p.on))
    return worst.low, worst.on


# --------------------------------------------------------------------------- #
# Step 3–5: safety, safe amount, earliest full-payment date
# --------------------------------------------------------------------------- #

def is_safe(state: FinancialState, payments: Iterable[Payment] = (), changes: Iterable[SpendingChange] = ()) -> bool:
    """True iff the balance never drops below minimum_balance_to_keep across the window."""
    low, _ = minimum_balance(state, payments, changes)
    return low >= state.profile.minimum_balance_to_keep


def headroom_on(state: FinancialState, on: date, changes: Iterable[SpendingChange] = ()) -> Decimal:
    """Largest single payment on `on` that keeps every later day (and `on` itself) at or above the
    minimum. A payment on `on` lowers every balance from `on` onward by the same amount, so the
    answer is the suffix-minimum of the daily lows from `on` minus the minimum to keep."""
    pts = daily_ledger(state, [Payment(on, Decimal(0))], changes)   # zero payment => a point on `on`
    # On `on` itself the payment lands after that day's credits, so only the close matters there.
    suffix_low = min(p.close if p.on == on else p.low for p in pts if p.on >= on)
    return suffix_low - state.profile.minimum_balance_to_keep


def amount_safe_on(state: FinancialState, on: Optional[date] = None) -> Decimal:
    """`amount_safe_to_pay`: headroom on request_date with no spending changes, clamped to
    [0, requested_amount]."""
    on = on or state.request.request_date
    room = headroom_on(state, on)
    return max(Decimal(0), min(state.request.requested_amount, room))


def earliest_full_payment_date(state: FinancialState, amount: Optional[Decimal] = None,
                               changes: Iterable[SpendingChange] = (),
                               not_before: Optional[date] = None) -> Optional[date]:
    """First date in the window on which a single payment of `amount` is safe, or None.

    Headroom is non-decreasing in the payment date (a later payment skips earlier dips), and it
    only changes on days with movement, so it suffices to test request_date plus every day that
    follows a ledger point.
    """
    amount = state.request.requested_amount if amount is None else amount
    rd, end = state.request.request_date, state.window_end
    candidates = {rd} | {p.on for p in daily_ledger(state, (), changes)}
    for on in sorted(d for d in candidates if d <= end):
        if not_before and on < not_before:
            continue
        if headroom_on(state, on, changes) >= amount:
            return on
    return None
