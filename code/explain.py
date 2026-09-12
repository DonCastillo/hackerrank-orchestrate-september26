"""Phase 6 — `decision_explanation` text, template-first, mirroring sample phrasing."""
from __future__ import annotations

from planner import Decision
from state import FinancialState


def explain(state: FinancialState, decision: Decision) -> str:
    """Return a concise, grounded explanation for the chosen plan."""
    raise NotImplementedError("Phase 6")
