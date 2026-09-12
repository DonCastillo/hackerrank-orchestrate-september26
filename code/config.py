"""Paths, constants, and the output contract. Stdlib only."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
DATASET_DIR = ROOT / "dataset"
IMAGES_DIR = DATASET_DIR / "media" / "images"
CACHE_DIR = CODE_DIR / "cache"
USAGE_LOG = CACHE_DIR / "usage.jsonl"
EVALUATION_DIR = CODE_DIR / "evaluation"
USAGE_REPORT = EVALUATION_DIR / "usage_report.md"
OUTPUT_CSV = ROOT / "output.csv"

# Forecast horizon used by the samples ("over the next 90 days").
FORECAST_DAYS = 90

OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

AFFORDABILITY_STATUSES = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
}

PAYMENT_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}

# Max spending-change actions allowed in `spending_changes_needed`.
MAX_SPENDING_CHANGES = 3

ZERO = Decimal("0")
