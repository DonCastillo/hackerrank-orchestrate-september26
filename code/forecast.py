"""Phase 3 — daily balance projection + safety checks over the forecast window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

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


def daily_balances(
    state: FinancialState,
    payments: list[Payment] = (),
    changes: list[SpendingChange] = (),
) -> list[tuple[date, Decimal]]:
    """Projected end-of-day balance for every day in the window."""
    raise NotImplementedError("Phase 3")


def is_safe(state: FinancialState, payments: list[Payment], changes: list[SpendingChange] = ()) -> bool:
    """True iff balance never drops below minimum_balance_to_keep across the window."""
    raise NotImplementedError("Phase 3")


def amount_safe_on(state: FinancialState, on: date) -> Decimal:
    """Largest single payment on `on` (no spending changes) that keeps the window safe, floored at 0."""
    raise NotImplementedError("Phase 3")


def earliest_full_payment_date(state: FinancialState, amount: Decimal) -> Optional[date]:
    """First date in the window where a single payment of `amount` is safe, or None."""
    raise NotImplementedError("Phase 3")
