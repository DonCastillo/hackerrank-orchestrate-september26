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
            # image-backed rows are one-off documents (bulk buys, invoices, a payslip copy):
            # they count toward cash, never toward recurrence detection
            st.one_off_ids.add(e.event_id)
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
    amends = list(amendments.for_user(profile.user_id, request.request_id)) if amendments else []
    st = classify_events(ds, profile, request, amounts=amendments.event_amounts if amendments else None)
    project_recurring_debits(ds, st)
    apply_debit_amendments(ds, st, amends)
    project_salary(ds, st, amends)
    apply_credit_amendments(ds, st, amends)
    st.flows.sort(key=lambda f: (f.on, f.source_event_id))
    return st


# --------------------------------------------------------------------------- #
# Phase 4 — applying evidence amendments
# --------------------------------------------------------------------------- #

def apply_debit_amendments(ds: Dataset, st: FinancialState, amends: list) -> None:
    """debit_pct: scale every projected occurrence of that category's series (lease renewal)."""
    for a in amends:
        if a.action != "debit_pct":
            continue
        factor = (Decimal(100) + a.percent) / Decimal(100)
        n = 0
        new_flows = []
        for f in st.flows:
            if f.kind == "recurring" and f.category == a.category:
                f = CashFlow(**{**f.__dict__, "amount": q(f.amount * factor)})
                n += 1
            new_flows.append(f)
        st.flows = new_flows
        st.notes.append(f"{a.source}: {a.category} scaled by {a.percent:+}% on {n} projected occurrences")


def apply_credit_amendments(ds: Dataset, st: FinancialState, amends: list) -> None:
    """credit_once / debit_once: one confirmed one-off movement on a stated date.

    A credit outside the window is dropped (never counted early). A confirmed loss dated
    before the request is still owed against today's balance, so it is reserved on request_date
    — the financially safer reading."""
    rd, end = st.request.request_date, st.window_end
    for a in amends:
        if a.action not in ("credit_once", "debit_once"):
            continue
        on = a.on
        if a.action == "credit_once" and not (rd <= on <= end):
            st.notes.append(f"{a.source}: one-off credit {a.amount} {a.currency} on {on} is outside the window")
            continue
        if a.action == "debit_once":
            if on > end:
                st.notes.append(f"{a.source}: one-off loss {a.amount} {a.currency} on {on} is beyond the window")
                continue
            on = max(on, rd)
        home = convert(ds, a.amount, a.currency, st.profile.home_currency, on)
        st.flows.append(CashFlow(
            on=on, amount=home if a.action == "credit_once" else -home,
            source_event_id=a.source, category="salary" if a.action == "credit_once" else "loss",
            essential=True, flexibility="fixed", minimum_allowed_amount=None, kind=a.action,
        ))
        st.notes.append(f"{a.source}: one-off {'credit' if a.action == 'credit_once' else 'loss'} {a.amount} {a.currency} on {on}")


def _regular_salary(payroll: list) -> tuple[Decimal, str]:
    """Regular pay = the most common recent payroll amount (ties -> latest). Used after a temporary
    reduction expires: a `salary_next` message means the latest row is the exception, not the rule."""
    from collections import Counter
    recent = payroll[-6:]
    counts = Counter((h.event.amount, h.event.currency) for h in recent)
    best = max(counts.values())
    for h in reversed(recent):
        if counts[(h.event.amount, h.event.currency)] == best:
            return h.event.amount, h.event.currency
    raise ValueError("no payroll rows")


def project_salary(ds: Dataset, st: FinancialState, amends: list = ()) -> None:
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

    salary_amends = [a for a in amends if a.action.startswith("salary_")]

    if any(a.action == "salary_end" for a in salary_amends):
        # employment / contract ended: drop the scheduled row too if the message post-dates it
        st.flows = [f for f in st.flows if not (f.kind == "scheduled" and f.category == "salary")]
        st.notes.append("salary: not projected — employer message says employment ended")
        return

    if sched_event is not None:
        amount, currency = sched_event.amount, sched_event.currency
        anchor = cash_date(sched_event)
        basis = f"scheduled {sched_event.event_id}"
    elif len(payroll) >= 2 and payroll[-1].event.description not in PAYROLL_ENDING:
        last = payroll[-1].event
        amount, currency = last.amount, last.currency
        # pay-day = the dominant day-of-month of recent payroll rows (a stray off-cycle row must
        # not move the anchor); anchor on the latest row that falls on that day
        from collections import Counter
        recent = payroll[-6:]
        day = Counter(h.on.day for h in recent).most_common(1)[0][0]
        anchor = next(h.on for h in reversed(recent) if h.on.day == day)
        basis = f"latest payroll {last.event_id}"
    elif payroll or salary_amends:
        # single row / ended series: only an explicit message can restart the series
        starts = [a for a in salary_amends if a.action == "salary_set" and a.on]
        if not starts:
            reason = ("no payroll history" if not payroll
                      else f"series ended ({payroll[-1].event.description})" if payroll[-1].event.description in PAYROLL_ENDING
                      else "single payroll row without a scheduled successor")
            st.notes.append(f"salary: not projected — {reason}")
            return
        a = starts[-1]
        amount, currency, anchor, basis = a.amount, a.currency, a.on, f"message {a.source}"
        anchor = a.on
        # the message's date is itself the first occurrence
        anchor_is_first = True
    else:
        st.notes.append("salary: not projected — no payroll history")
        return
    anchor_is_first = locals().get("anchor_is_first", False)

    # --- amendments on an existing series -------------------------------------------------
    regular = (amount, currency)
    next_only: list[tuple[Decimal, str]] = []
    for a in salary_amends:
        if a.action == "salary_set":
            amount, currency = a.amount, a.currency
            regular = (amount, currency)
            if a.on and a.on >= rd and not anchor_is_first:
                anchor, anchor_is_first = a.on, True
            basis += f" +{a.source}:set"
        elif a.action == "salary_next":
            next_only = [(a.amount, a.currency)] * (a.count or 1)
            regular = _regular_salary(payroll) if payroll else regular
            basis += f" +{a.source}:next"
        elif a.action == "salary_date":
            anchor, anchor_is_first = a.on, True
            # the scheduled row (if any) moves with it
            st.flows = [f for f in st.flows if not (f.kind == "scheduled" and f.category == "salary")]
            basis += f" +{a.source}:date"

    from recurrence import add_months
    src = sched_event.event_id if sched_event is not None else (payroll[-1].event.event_id if payroll else "message")
    dates = []
    k = 0 if anchor_is_first else 1
    while True:
        d = add_months(anchor, k)
        if d > end:
            break
        if d >= rd and not any(f.kind == "scheduled" and f.category == "salary" and f.on == d for f in st.flows):
            dates.append(d)
        k += 1
    for i, d in enumerate(dates):
        amt, cur = (next_only[i] if i < len(next_only) else regular)
        st.flows.append(CashFlow(
            on=d, amount=convert(ds, amt, cur, st.profile.home_currency, d),
            source_event_id=src, category="salary", essential=True, flexibility="fixed",
            minimum_allowed_amount=None, kind="salary",
        ))
    st.salary = {"amount": regular[0], "currency": regular[1], "day": anchor.day, "basis": basis, "dates": dates}
    st.notes.append(f"salary: {regular[0]} {regular[1]} on day {anchor.day} from {basis} -> {len(dates)} projected"
                    + (f" (next {len(next_only)} at {next_only[0][0]})" if next_only else ""))


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
