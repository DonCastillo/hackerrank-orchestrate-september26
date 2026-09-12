"""Phase 2 — per-user financial-state reconstruction.

Turns raw events (+ evidence amendments) into:
  * an opening balance on request_date with pending debits reserved,
  * a list of dated future cash flows inside the forecast window
    (scheduled events + detected recurring commitments + salary),
  * the set of flexible debits the planner may stop/reduce.

Cash-effect classification (see plan/FINDINGS.md, "Event inventory"):
  settled     -> already inside current_available_balance; used only as history
  pending     -> debit: reserve on settlement_date; credit: ignore until settled
  scheduled   -> dated future flow on settlement_date
  failed / cancelled / unrealized -> no cash effect
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from config import FORECAST_DAYS
from loader import Dataset, Event, Profile, Request
from money import q
from recurrence import Series, detect_series


NO_CASH_STATUSES = {"failed", "cancelled", "unrealized"}
NON_CASH_TYPES = {"investment_valuation"}

# Event types / categories that are one-off by nature and must never seed a recurring series.
ONE_OFF_TYPES = {"refund", "investment_purchase", "investment_sale", "investment_valuation"}
ONE_OFF_CATEGORIES = {"work_expense", "investment"}

# Step 7 — which salary rows count as *confirmed* monthly payroll (plan/FINDINGS.md, salary rules).
PAYROLL_DESCRIPTIONS = {
    "Payroll credit", "International employer payroll", "Base salary", "Primary household salary",
    "Previous employer payroll", "New employer payroll", "First-job payroll",
    "Payroll before leave", "Payroll after returning from leave",
    "Prorated first salary", "Final employer payroll", "Next confirmed salary",
    "August 2019 net salary",
}
# A series whose latest row is one of these has ended unless a scheduled row / message says otherwise.
PAYROLL_ENDING = {"Final employer payroll", "Previous employer payroll"}
# Everything else under category=salary is variable / unconfirmed income and is never projected:
# gig payouts, freelance invoices, commissions, bonuses, arrears, second household income,
# seasonal / temporary pay, prize proceeds.


@dataclass(frozen=True)
class CashFlow:
    """One projected cash movement inside the forecast window, in home currency."""
    on: date
    amount: Decimal          # positive = credit, negative = debit
    source_event_id: str     # event this flow was derived from (for spending changes)
    category: str
    essential: bool          # protected / fixed => cannot be changed
    flexibility: str
    minimum_allowed_amount: Optional[Decimal]
    kind: str                # scheduled | recurring | salary | pending_reserve


@dataclass(frozen=True)
class HistoryEvent:
    """A settled event expressed in the user's home currency (recurrence input)."""
    event: Event
    on: date                 # settlement_date, or event_date when blank
    amount: Decimal          # home currency, signed (+credit / -debit)


@dataclass
class FinancialState:
    user_id: str
    profile: Profile
    request: Request
    opening_balance: Decimal                  # current_available_balance (pending debits are dated flows)
    window_end: date
    history: list[HistoryEvent] = field(default_factory=list)
    flows: list[CashFlow] = field(default_factory=list)
    unresolved: list[Event] = field(default_factory=list)   # blank amounts with no amendment yet
    one_off_ids: set[str] = field(default_factory=set)      # events excluded from recurrence detection
    series: list[Series] = field(default_factory=list)       # detected recurring debit series
    salary: Optional[dict] = None                            # projected salary summary (amount, currency, day)
    notes: list[str] = field(default_factory=list)          # human-readable audit trail


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #

def convert(ds: Dataset, amount: Decimal, currency: str, to_currency: str, on: date) -> Decimal:
    """Convert a foreign-currency cash event using the fixed rate for `on`.

    Uses the row for (on, currency -> to_currency). Every supplied foreign event has such a row;
    for *projected* dates without one, fall back to the pair's latest known rate (rates are
    constant per pair in this dataset). Fails loudly if the pair is unknown altogether.
    """
    if currency == to_currency:
        return amount
    key = (on, currency, to_currency)
    if key in ds.rates:
        return q(amount * ds.rates[key])
    candidates = [(d, r) for (d, f, t), r in ds.rates.items() if f == currency and t == to_currency]
    if not candidates:
        raise KeyError(f"no exchange rate for {currency}->{to_currency} (needed on {on})")
    earlier = [(d, r) for d, r in candidates if d <= on]
    _, rate = max(earlier) if earlier else min(candidates)
    return q(amount * rate)


# --------------------------------------------------------------------------- #
# Step 1–2: filter, sort, classify
# --------------------------------------------------------------------------- #

def cash_date(e: Event) -> date:
    return e.settlement_date or e.event_date


def one_off_ids(events: list[Event]) -> set[str]:
    """Step 3 — linked_event_id chains and intrinsically one-off rows.

    Every link in the dataset is a 2-row lifecycle (purchase→refund, original→duplicate charge,
    failed→retry, work expense→reimbursement, contribution→sale/valuation, charge→reversal,
    cancelled auth→settled purchase). The link itself never changes a row's cash state — that is
    decided by status in classify_events() — but both ends are one-off transactions, so they are
    excluded from recurrence detection. Same for refunds / investment moves / work expenses.
    """
    ids: set[str] = set()
    by_id = {e.event_id: e for e in events}
    for e in events:
        if e.event_type in ONE_OFF_TYPES or e.category in ONE_OFF_CATEGORIES:
            ids.add(e.event_id)
        if e.linked_event_id:
            ids.add(e.event_id)
            if e.linked_event_id in by_id:
                ids.add(e.linked_event_id)
    return ids


def _is_changeable(profile: Profile, e: Event) -> bool:
    """flexibility != fixed AND category in the matching permitted list (FINDINGS: profile inventory)."""
    if e.flexibility == "reducible":
        return e.category in profile.expense_categories_user_is_willing_to_reduce
    if e.flexibility == "stoppable":
        return e.category in profile.expense_categories_user_is_willing_to_stop
    if e.flexibility == "reducible_or_stoppable":
        return (e.category in profile.expense_categories_user_is_willing_to_reduce
                or e.category in profile.expense_categories_user_is_willing_to_stop)
    return False


def _flow_from_event(ds: Dataset, profile: Profile, e: Event, amount: Decimal, kind: str) -> CashFlow:
    on = cash_date(e)
    home = convert(ds, amount, e.currency, profile.home_currency, on)
    signed = home if e.direction == "credit" else -home
    return CashFlow(
        on=on,
        amount=signed,
        source_event_id=e.event_id,
        category=e.category,
        essential=not _is_changeable(profile, e),
        flexibility=e.flexibility,
        minimum_allowed_amount=e.minimum_allowed_amount,
        kind=kind,
    )


def classify_events(ds: Dataset, profile: Profile, request: Request,
                    amounts: Optional[dict[str, tuple[Decimal, str]]] = None) -> FinancialState:
    """Build the base state: history + pending reserves + scheduled flows. No recurrence yet.

    `amounts` optionally supplies (amount, currency) for blank-amount events (from images).
    """
    rd = request.request_date
    st = FinancialState(
        user_id=profile.user_id,
        profile=profile,
        request=request,
        opening_balance=profile.current_available_balance,
        window_end=rd + timedelta(days=FORECAST_DAYS),
    )
    events = sorted(ds.events.get(profile.user_id, []), key=lambda e: (cash_date(e), e.event_id))
    st.one_off_ids = one_off_ids(events)

    for e in events:
        amount, currency = e.amount, e.currency
        if amount is None and amounts and e.event_id in amounts:
            amount, currency = amounts[e.event_id]
            e = Event(**{**e.__dict__, "amount": amount, "currency": currency})
        if amount is None:
            st.unresolved.append(e)
            st.notes.append(f"{e.event_id}: blank amount ({e.status} {e.direction} {e.category}) — awaiting image evidence")
            continue

        if e.status in NO_CASH_STATUSES or e.event_type in NON_CASH_TYPES or e.direction == "non_cash":
            continue  # no cash effect

        if e.status == "settled":
            if cash_date(e) > rd:
                # settled but dated after the request: treat as a known future flow
                st.flows.append(_flow_from_event(ds, profile, e, amount, "scheduled"))
                st.notes.append(f"{e.event_id}: settled with future settlement {cash_date(e)} — projected as a dated flow")
            else:
                home = convert(ds, amount, currency, profile.home_currency, cash_date(e))
                st.history.append(HistoryEvent(e, cash_date(e), home if e.direction == "credit" else -home))
            continue

        if e.status == "pending":
            if e.direction == "debit":
                flow = _flow_from_event(ds, profile, e, amount, "pending_reserve")
                # a pending debit whose settlement date already passed is still owed: reserve it today
                if flow.on < rd:
                    flow = CashFlow(**{**flow.__dict__, "on": rd})
                st.flows.append(flow)
            else:
                st.notes.append(f"{e.event_id}: pending credit {amount} {currency} ignored until settled")
            continue

        if e.status == "scheduled":
            on = cash_date(e)
            if rd <= on <= st.window_end:
                st.flows.append(_flow_from_event(ds, profile, e, amount, "scheduled"))
            elif on < rd:
                st.notes.append(f"{e.event_id}: scheduled {on} is before request_date — assumed already reflected")
            continue

        st.notes.append(f"{e.event_id}: unhandled status {e.status!r} ignored")

    st.flows.sort(key=lambda f: (f.on, f.source_event_id))
    return st


def build_state(ds: Dataset, request: Request, amendments: Optional[dict] = None) -> FinancialState:
    """Reconstruct the user's position on `request.request_date`.

    `amendments` is the structured output of evidence.py (may be None for --no-llm).
    Recurrence projection (steps 4–7) is added in later steps.
    """
    profile = ds.profiles[request.user_id]
    st = classify_events(ds, profile, request)
    project_recurring_debits(ds, st)
    project_salary(ds, st)
    st.flows.sort(key=lambda f: (f.on, f.source_event_id))
    return st


def project_salary(ds: Dataset, st: FinancialState) -> None:
    """Step 7 — project confirmed monthly salary through the window.

    Amount and pay-day come from the scheduled `Next confirmed salary` row when present, otherwise
    from the latest settled payroll row (a raise/cut carries forward; a one-off reduced payroll is
    corrected by the employer message in Phase 4). Requires history support: >= 2 payroll rows, or
    a scheduled row. Ended series (`Final employer payroll`, or a `Previous employer payroll` with no
    successor) and non-payroll income are never projected.
    """
    rd, end = st.request.request_date, st.window_end
    payroll = [h for h in st.history
               if h.event.category == "salary" and h.event.direction == "credit"
               and h.event.description in PAYROLL_DESCRIPTIONS and h.event.event_id not in st.one_off_ids]
    payroll.sort(key=lambda h: h.on)
    scheduled = [f for f in st.flows if f.kind == "scheduled" and f.category == "salary" and f.amount > 0]
    sched_event = ds.events_by_id[scheduled[-1].source_event_id] if scheduled else None

    if sched_event is not None:
        amount, currency = sched_event.amount, sched_event.currency
        anchor = cash_date(sched_event)
        basis = f"scheduled {sched_event.event_id}"
    elif len(payroll) >= 2 and payroll[-1].event.description not in PAYROLL_ENDING:
        last = payroll[-1].event
        amount, currency = last.amount, last.currency
        anchor = payroll[-1].on
        basis = f"latest payroll {last.event_id}"
    else:
        reason = ("no payroll history" if not payroll
                  else f"series ended ({payroll[-1].event.description})" if payroll[-1].event.description in PAYROLL_ENDING
                  else "single payroll row without a scheduled successor")
        st.notes.append(f"salary: not projected — {reason}")
        return

    from recurrence import add_months
    src = sched_event.event_id if sched_event is not None else payroll[-1].event.event_id
    k, dates = 1, []
    while True:
        d = add_months(anchor, k)
        if d > end:
            break
        if d >= rd:
            dates.append(d)
        k += 1
    for d in dates:
        st.flows.append(CashFlow(
            on=d, amount=convert(ds, amount, currency, st.profile.home_currency, d),
            source_event_id=src, category="salary", essential=True, flexibility="fixed",
            minimum_allowed_amount=None, kind="salary",
        ))
    st.salary = {"amount": amount, "currency": currency, "day": anchor.day, "basis": basis, "dates": dates}
    st.notes.append(f"salary: {amount} {currency} on day {anchor.day} from {basis} -> {len(dates)} projected")


def project_recurring_debits(ds: Dataset, st: FinancialState) -> None:
    """Step 5–6 — detect recurring debit series and add their occurrences as flows."""
    st.series = detect_series(st.history, st.one_off_ids, st.request.request_date, st.window_end, st.flows)
    for s in st.series:
        e = s.last_event
        for on in s.occurrences:
            st.flows.append(CashFlow(
                on=on, amount=-s.amount, source_event_id=e.event_id, category=s.category,
                essential=not _is_changeable(st.profile, e), flexibility=s.flexibility,
                minimum_allowed_amount=s.minimum_allowed_amount, kind="recurring",
            ))
    st.flows.sort(key=lambda f: (f.on, f.source_event_id))
