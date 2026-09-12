"""Phase 7 — output contract checks for output.csv (AGENTS.md §6.2)."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from config import AFFORDABILITY_STATUSES, MAX_SPENDING_CHANGES, OUTPUT_COLUMNS, PAYMENT_METHODS
from loader import Dataset


def _parse_plan(plan: str) -> list[tuple[date, Decimal]]:
    if plan == "none":
        return []
    out = []
    for part in plan.split("|"):
        d, a = part.split(":", 1)
        out.append((date.fromisoformat(d), Decimal(a)))
    return out


def validate_output(ds: Dataset, path: Path) -> list[str]:
    """Return a list of human-readable problems; empty list means the file is valid."""
    problems: list[str] = []
    if not path.exists():
        return [f"{path} does not exist"]

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != OUTPUT_COLUMNS:
            problems.append(f"header mismatch: {reader.fieldnames}")
            return problems
        rows = list(reader)

    expected_ids = [r.request_id for r in ds.requests]
    got_ids = [r["request_id"] for r in rows]
    if got_ids != expected_ids:
        missing = sorted(set(expected_ids) - set(got_ids))
        extra = sorted(set(got_ids) - set(expected_ids))
        problems.append(f"request_id set/order mismatch (missing={missing[:5]}, extra={extra[:5]}, "
                        f"count={len(got_ids)} vs {len(expected_ids)})")

    requests = {r.request_id: r for r in ds.requests}
    options = ds.payment_options

    for row in rows:
        rid = row["request_id"]
        req = requests.get(rid)
        if req is None:
            continue
        tag = f"[{rid}]"

        # amount_safe_to_pay
        try:
            safe = Decimal(row["amount_safe_to_pay"])
        except InvalidOperation:
            problems.append(f"{tag} amount_safe_to_pay not numeric: {row['amount_safe_to_pay']!r}")
            continue
        if not (Decimal(0) <= safe <= req.requested_amount):
            problems.append(f"{tag} amount_safe_to_pay {safe} outside [0, {req.requested_amount}]")

        status = row["affordability_status"]
        method = row["recommended_payment_method"]
        if status not in AFFORDABILITY_STATUSES:
            problems.append(f"{tag} bad affordability_status {status!r}")
        if method not in PAYMENT_METHODS:
            problems.append(f"{tag} bad recommended_payment_method {method!r}")

        # payment_plan
        try:
            plan = _parse_plan(row["payment_plan"])
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{tag} unparsable payment_plan {row['payment_plan']!r}: {exc}")
            plan = []
        dates = [d for d, _ in plan]
        if dates != sorted(dates):
            problems.append(f"{tag} payment_plan not chronological")
        if plan and sum(a for _, a in plan) != req.requested_amount and method != "installments":
            problems.append(f"{tag} payment_plan total {sum(a for _, a in plan)} != requested {req.requested_amount}")

        earliest = row["earliest_date_for_full_payment"]
        if status == "affordable_now" and earliest != req.request_date.isoformat():
            problems.append(f"{tag} affordable_now but earliest_date {earliest!r} != request_date")
        if status == "not_affordable" and method != "not_recommended":
            problems.append(f"{tag} not_affordable must pair with not_recommended (got {method})")

        if method == "full_payment":
            if plan != [(req.request_date, req.requested_amount)]:
                problems.append(f"{tag} full_payment plan must be request_date:requested_amount")
        elif method == "partial_payment":
            if not req.allows_partial_payment:
                problems.append(f"{tag} partial_payment but request disallows partial payment")
            if len(plan) != 2:
                problems.append(f"{tag} partial_payment needs exactly two payments")
            else:
                (d1, a1), (d2, a2) = plan
                if d1 != req.request_date or a1 != safe:
                    problems.append(f"{tag} first partial payment must be {req.request_date}:{safe}")
                if earliest != d2.isoformat():
                    problems.append(f"{tag} second partial payment date must equal earliest_date_for_full_payment")
                if d2 > req.desired_completion_date:
                    problems.append(f"{tag} second partial payment after desired_completion_date")
                if not (Decimal(0) < safe < req.requested_amount):
                    problems.append(f"{tag} partial_payment requires 0 < amount_safe_to_pay < requested_amount")
        elif method == "installments":
            if not _matches_supplied_option(plan, options.get(rid, [])):
                problems.append(f"{tag} installment plan does not match any supplied option")
        elif method == "wait":
            if len(plan) != 1 or plan[0][1] != req.requested_amount:
                problems.append(f"{tag} wait plan must be one full payment on a future date")
            elif plan[0][0].isoformat() != earliest:
                problems.append(f"{tag} wait plan date must equal earliest_date_for_full_payment")
        elif method == "not_recommended":
            if plan:
                problems.append(f"{tag} not_recommended must have payment_plan=none")

        # spending_changes_needed
        sc = row["spending_changes_needed"]
        if sc != "none":
            actions = sc.split("|")
            if len(actions) > MAX_SPENDING_CHANGES:
                problems.append(f"{tag} more than {MAX_SPENDING_CHANGES} spending changes")
            seen: set[str] = set()
            for act in actions:
                parts = act.split(":")
                if parts[0] == "stop" and len(parts) == 2:
                    eid = parts[1]
                elif parts[0] == "reduce_to" and len(parts) == 3:
                    eid = parts[1]
                    try:
                        Decimal(parts[2])
                    except InvalidOperation:
                        problems.append(f"{tag} reduce_to amount not numeric in {act!r}")
                else:
                    problems.append(f"{tag} malformed spending change {act!r}")
                    continue
                if eid in seen:
                    problems.append(f"{tag} event {eid} changed twice")
                seen.add(eid)
                ev = ds.events_by_id.get(eid)
                if ev is None:
                    problems.append(f"{tag} spending change references unknown event {eid}")
                elif ev.user_id != req.user_id:
                    problems.append(f"{tag} spending change references another user's event {eid}")

        if not row["decision_explanation"].strip():
            problems.append(f"{tag} empty decision_explanation")

    return problems


def _matches_supplied_option(plan: list[tuple[date, Decimal]], opts) -> bool:
    from datetime import timedelta
    for o in opts:
        if o.payment_method != "installments":
            continue
        step = timedelta(days=o.payment_frequency_days or 0)
        expected = [(o.first_payment_date + step * k, o.payment_amount) for k in range(o.number_of_payments)]
        if plan == expected:
            return True
    return False
