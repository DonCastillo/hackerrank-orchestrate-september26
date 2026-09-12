"""Phase 2 — per-user financial-state reconstruction.

Turns raw events (+ evidence amendments) into:
  * an opening balance on request_date with pending debits reserved,
  * a list of dated future cash flows inside the forecast window
    (scheduled events + detected recurring commitments + salary),
  * the set of flexible debits the planner may stop/reduce.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from loader import Dataset, Event, Profile, Request
from money import q


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


@dataclass
class FinancialState:
    user_id: str
    profile: Profile
    request: Request
    opening_balance: Decimal                  # current_available_balance - reserved pending debits
    flows: list[CashFlow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # human-readable audit trail


def build_state(ds: Dataset, request: Request, amendments: Optional[dict] = None) -> FinancialState:
    """Reconstruct the user's position on `request.request_date`.

    `amendments` is the structured output of evidence.py (may be None for --no-llm).
    """
    raise NotImplementedError("Phase 2")


def convert(ds: Dataset, amount: Decimal, currency: str, to_currency: str, on: date) -> Decimal:
    """Convert a foreign-currency cash event using the fixed rate for `on`.

    Fails loudly if no rate row exists for (on, currency, to_currency).
    """
    if currency == to_currency:
        return amount
    key = (on, currency, to_currency)
    if key not in ds.rates:
        raise KeyError(f"no exchange rate for {currency}->{to_currency} on {on}")
    return q(amount * ds.rates[key])
