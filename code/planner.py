"""Phase 5 — enumerate candidate plans, rank them, and derive the output row."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from forecast import Payment, SpendingChange
from loader import Dataset, PaymentOption
from money import fmt_plan, fmt_safe
from state import FinancialState


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


def decide(ds: Dataset, state: FinancialState) -> Decision:
    """Produce the full decision for one request."""
    raise NotImplementedError("Phase 5")
