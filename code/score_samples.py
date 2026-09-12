"""Phase 7 — run the engine on dataset/sample_requests.csv and diff every column."""
from __future__ import annotations

from loader import Dataset
from planner import Decision

COMPARE_COLUMNS = [
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
]


def score_samples(ds: Dataset, decisions: dict[str, Decision]) -> tuple[int, int, list[str]]:
    """Return (matched_columns, total_columns, mismatch_lines)."""
    matched = total = 0
    lines: list[str] = []
    for s in ds.samples:
        d = decisions.get(s.request_id)
        if d is None:
            lines.append(f"{s.request_id}: no decision produced")
            total += len(COMPARE_COLUMNS)
            continue
        got = d.to_row()
        expected = {
            "amount_safe_to_pay": str(s.amount_safe_to_pay),
            "affordability_status": s.affordability_status,
            "recommended_payment_method": s.recommended_payment_method,
            "payment_plan": s.payment_plan,
            "earliest_date_for_full_payment": (
                s.earliest_date_for_full_payment.isoformat() if s.earliest_date_for_full_payment else ""
            ),
            "spending_changes_needed": s.spending_changes_needed,
        }
        for col in COMPARE_COLUMNS:
            total += 1
            if _norm(got[col]) == _norm(expected[col]):
                matched += 1
            else:
                lines.append(f"{s.request_id}.{col}: expected {expected[col]!r}, got {got[col]!r}")
    return matched, total, lines


def _norm(v: str) -> str:
    """Compare numbers by value (25256 == 25256.00) and everything else verbatim."""
    from decimal import Decimal, InvalidOperation
    try:
        return format(Decimal(v).normalize(), "f")
    except (InvalidOperation, ValueError):
        return v
