"""Phase 5 — enumerate candidate plans, rank them, and derive the output row.

Candidate plans (plan/FINDINGS.md, decision-layer patterns):
  full           requested_amount on request_date                     user accepts full_payment
  full+changes   same, plus <= 3 stop:/reduce_to: on flexible series   changes in permitted categories
  partial        safe today + remainder on the next payday             request allows it, user accepts it, 0 < safe < requested, 2nd date <= deadline
  installments   each supplied option, expanded to its schedule        user accepts installments, n <= max_installment_months
  wait           full amount on earliest_date_for_full_payment         that date <= deadline
Every candidate is checked with forecast.is_safe() (its own payments inserted) and must complete
by desired_completion_date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
from typing import Optional

from config import MAX_SPENDING_CHANGES
from forecast import (Payment, SpendingChange, amount_safe_on, earliest_full_payment_date,
                      is_safe, headroom_on)
from loader import Dataset, PaymentOption
from money import fmt_plan, fmt_safe
from state import FinancialState


@dataclass
class Candidate:
    method: str                                  # full_payment | partial_payment | installments | wait
    payments: list[Payment]
    changes: list[SpendingChange] = field(default_factory=list)
    option: Optional[PaymentOption] = None
    safe: bool = False
    reason: str = ""                             # why it was rejected, if it was

    @property
    def total_cost(self) -> Decimal:
        return sum((p.amount for p in self.payments), Decimal(0))

    @property
    def start(self) -> date:
        return self.payments[0].on

    @property
    def end(self) -> date:
        return self.payments[-1].on


@dataclass
class Decision:
    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payments: list[Payment] = field(default_factory=list)
    earliest_date_for_full_payment: Optional[date] = None
    spending_changes: list[SpendingChange] = field(default_factory=list)
    option: Optional[PaymentOption] = None      # chosen supplied option, if any
    decision_explanation: str = ""
    candidates: list[Candidate] = field(default_factory=list)   # everything considered (audit)

    # ---- rendering helpers used by main.py ---------------------------------
    def payment_plan(self) -> str:
        if not self.payments:
            return "none"
        return "|".join(f"{p.on.isoformat()}:{fmt_plan(p.amount)}" for p in self.payments)

    def spending_changes_needed(self) -> str:
        return "|".join(c.render() for c in self.spending_changes) if self.spending_changes else "none"

    def to_row(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": fmt_safe(self.amount_safe_to_pay),
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan(),
            "earliest_date_for_full_payment": (
                self.earliest_date_for_full_payment.isoformat()
                if self.earliest_date_for_full_payment else ""
            ),
            "spending_changes_needed": self.spending_changes_needed(),
            "decision_explanation": self.decision_explanation,
        }


# --------------------------------------------------------------------------- #
# Step 1: candidate enumeration
# --------------------------------------------------------------------------- #

def _mildest_change(series) -> Optional[SpendingChange]:
    """The least disruptive permitted action for a flexible series."""
    e = series.last_event
    if series.flexibility in ("reducible", "reducible_or_stoppable") and series.minimum_allowed_amount is not None \
            and series.minimum_allowed_amount < series.amount:
        return SpendingChange("reduce_to", e.event_id, series.minimum_allowed_amount)
    if series.flexibility in ("stoppable", "reducible_or_stoppable"):
        return SpendingChange("stop", e.event_id)
    return None


def _changeable_series(state: FinancialState):
    """Series the user permits changing (flexibility != fixed AND category in the matching list)."""
    p = state.profile
    out = []
    for s in state.series:
        ok = ((s.flexibility in ("reducible", "reducible_or_stoppable") and s.category in p.expense_categories_user_is_willing_to_reduce)
              or (s.flexibility in ("stoppable", "reducible_or_stoppable") and s.category in p.expense_categories_user_is_willing_to_stop))
        if ok and _mildest_change(s) is not None:
            out.append(s)
    return out


def enumerate_candidates(ds: Dataset, state: FinancialState) -> tuple[list[Candidate], Decimal, Optional[date]]:
    """Return (candidates, amount_safe_to_pay, earliest_date_for_full_payment)."""
    req, prof = state.request, state.profile
    rd, deadline, amount = req.request_date, req.desired_completion_date, req.requested_amount
    methods = set(prof.payment_methods_user_will_consider)
    safe_today = amount_safe_on(state)
    earliest = earliest_full_payment_date(state)
    cands: list[Candidate] = []

    def add(c: Candidate) -> None:
        if c.end > deadline:
            c.safe, c.reason = False, f"completes {c.end} after deadline {deadline}"
        elif not c.reason:
            c.safe = is_safe(state, c.payments, c.changes)
            if not c.safe:
                c.reason = "balance would fall below the minimum"
        cands.append(c)

    # 1. full payment today
    full = Candidate("full_payment", [Payment(rd, amount)])
    if "full_payment" not in methods:
        full.reason = "user does not consider full_payment"
    add(full)

    # 2. full payment today + fewest spending changes that make it safe
    if "full_payment" in methods and not full.safe and full.reason == "balance would fall below the minimum":
        series = _changeable_series(state)
        found = None
        for k in range(1, min(MAX_SPENDING_CHANGES, len(series)) + 1):
            options = []
            for combo in combinations(series, k):
                changes = [_mildest_change(s) for s in combo]
                if is_safe(state, full.payments, changes):
                    # tie-break: smallest total monthly reduction (least disruption), then event ids
                    disruption = sum((s.amount - (c.new_amount or Decimal(0)) for s, c in zip(combo, changes)), Decimal(0))
                    options.append((disruption, [c.event_id for c in changes], changes))
            if options:
                found = min(options)[2]
                break
        if found:
            add(Candidate("full_payment", [Payment(rd, amount)], changes=found))
        else:
            cands.append(Candidate("full_payment", [Payment(rd, amount)], changes=[], safe=False,
                                   reason="no combination of <= 3 permitted spending changes makes full payment safe"))

    # 3. partial payment: amount_safe_to_pay today + remainder on earliest_date_for_full_payment (§6.2)
    if req.allows_partial_payment and "partial_payment" in methods and Decimal(0) < safe_today < amount:
        if earliest is None:
            cands.append(Candidate("partial_payment", [Payment(rd, safe_today)], safe=False,
                                   reason="no safe full-payment date within 90 days for the second payment"))
        else:
            add(Candidate("partial_payment", [Payment(rd, safe_today), Payment(earliest, amount - safe_today)]))
    elif "partial_payment" in methods and req.allows_partial_payment:
        cands.append(Candidate("partial_payment", [Payment(rd, safe_today)], safe=False,
                               reason="partial needs 0 < amount_safe_to_pay < requested_amount"))

    # 4. supplied installment options
    for o in ds.payment_options.get(req.request_id, []):
        if o.payment_method != "installments":
            continue
        step = timedelta(days=o.payment_frequency_days or 30)
        pays = [Payment(o.first_payment_date + step * i, o.payment_amount) for i in range(o.number_of_payments)]
        c = Candidate("installments", pays, option=o)
        if "installments" not in methods:
            c.reason = "user does not consider installments"
        elif prof.max_installment_months is None or o.number_of_payments > prof.max_installment_months:
            c.reason = f"{o.number_of_payments} payments exceeds max_installment_months={prof.max_installment_months}"
        add(c)

    # 5. wait for the earliest safe full-payment date
    if earliest is not None and earliest > rd:
        w = Candidate("wait", [Payment(earliest, amount)])
        if "full_payment" not in methods:
            w.reason = "user does not consider full_payment"
        add(w)
    elif earliest is None:
        cands.append(Candidate("wait", [Payment(deadline, amount)], safe=False, reason="no safe full-payment date within 90 days"))

    return cands, safe_today, earliest


# --------------------------------------------------------------------------- #
# Step 2–3: ranking, status derivation, fallback
# --------------------------------------------------------------------------- #

def rank_key(c: Candidate) -> tuple:
    """§6.3 preference order among safe, on-time plans:
    avoids spending changes → lowest total payment cost → starts earlier → fewer payments →
    lowest payment_option_id (deterministic tie-break)."""
    return (
        1 if c.changes else 0,
        c.total_cost,
        c.start,
        len(c.payments),
        c.option.payment_option_id if c.option else "",
    )


def status_for(c: Candidate, request_date: date) -> str:
    if c.method == "full_payment" and not c.changes and c.start == request_date:
        return "affordable_now"
    if c.method == "wait":
        return "affordable_later"
    return "affordable_with_plan"   # partial schedule, installments, or permitted spending changes


def decide(ds: Dataset, state: FinancialState) -> Decision:
    """Produce the full decision for one request."""
    req = state.request
    cands, safe_today, earliest = enumerate_candidates(ds, state)
    survivors = sorted((c for c in cands if c.safe), key=rank_key)

    if not survivors:
        return Decision(
            request_id=req.request_id, amount_safe_to_pay=safe_today,
            affordability_status="not_affordable", recommended_payment_method="not_recommended",
            payments=[], earliest_date_for_full_payment=earliest, spending_changes=[], candidates=cands,
        )

    best = survivors[0]
    status = status_for(best, req.request_date)
    return Decision(
        request_id=req.request_id,
        amount_safe_to_pay=safe_today,
        affordability_status=status,
        recommended_payment_method=best.method,
        payments=list(best.payments),
        earliest_date_for_full_payment=req.request_date if status == "affordable_now" else earliest,
        spending_changes=list(best.changes),
        option=best.option,
        candidates=cands,
    )
