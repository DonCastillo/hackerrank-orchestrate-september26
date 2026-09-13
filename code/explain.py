"""Phase 6 — `decision_explanation` text, template-first, mirroring sample phrasing.

Deterministic on purpose: every number and date comes from the Decision / FinancialState,
so the explanation can never contradict the other output columns.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from money import q
from planner import Decision
from state import FinancialState


def money(cur: str, x: Decimal) -> str:
    """'ZAR 25,256' / 'EUR 620.40' / 'IDR 15,952,906.67' — 2 dp only when there are cents."""
    x = q(x)
    if x == x.to_integral_value():
        return f"{cur} {int(x):,}"
    return f"{cur} {x:,.2f}"


def longdate(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def _change_phrase(state: FinancialState, change) -> str:
    ev = next((s.last_event for s in state.series if s.last_event.event_id == change.event_id), None)
    name = f"the {ev.description.lower()}" if ev else f"the {change.event_id} expense"
    if change.action == "stop":
        return f"stop {name}"
    return f"reduce {name} to {money(state.profile.home_currency, change.new_amount)}"


def explain(state: FinancialState, d: Decision) -> str:
    """Return a concise, grounded explanation for the chosen plan."""
    req, prof = state.request, state.profile
    cur, mn = prof.home_currency, prof.minimum_balance_to_keep
    amount = req.requested_amount
    m = d.recommended_payment_method

    if m == "full_payment" and d.spending_changes:
        steps = " and ".join(_change_phrase(state, c) for c in d.spending_changes)
        steps = steps[0].upper() + steps[1:]
        return f"{steps}, then pay {money(cur, amount)} today. This leaves at least {money(cur, mn)} available."

    if m == "full_payment":
        return (f"Pay {money(cur, amount)} today. This leaves at least {money(cur, mn)} available "
                f"over the next 90 days.")

    if m == "wait":
        return (f"Pay {money(cur, amount)} in full on {longdate(d.payments[0].on)}. "
                f"Paying earlier would take the balance below the {money(cur, mn)} minimum.")

    if m == "partial_payment":
        first, second = d.payments
        return (f"Pay {money(cur, first.amount)} today and the remaining {money(cur, second.amount)} on "
                f"{longdate(second.on)}. This completes the full request and keeps the {money(cur, mn)} "
                f"minimum protected.")

    if m == "installments":
        n = len(d.payments)
        return (f"Use {n} installments of {money(cur, d.payments[0].amount)}, starting "
                f"{longdate(d.payments[0].on)}. This leaves at least {money(cur, mn)} available.")

    # not_recommended
    only_partial = set(prof.payment_methods_user_will_consider) == {"partial_payment"}
    if only_partial and d.amount_safe_to_pay > 0:
        return (f"Do not proceed with the {money(cur, amount)} request. Although {money(cur, d.amount_safe_to_pay)} "
                f"is available today, the full amount cannot be completed safely within 90 days.")
    return (f"Do not make this payment by {longdate(req.desired_completion_date)}. None of the available "
            f"options keeps the {money(cur, mn)} minimum protected.")
