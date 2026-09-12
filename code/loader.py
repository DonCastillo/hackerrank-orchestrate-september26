"""Read every dataset/*.csv into typed, immutable records.

All money is parsed as Decimal (never float) so downstream arithmetic is exact.
Blank numeric cells become None; blank list cells become empty tuples.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from config import DATASET_DIR


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: tuple[str, ...]
    expense_categories_to_protect: tuple[str, ...]
    expense_categories_user_is_willing_to_reduce: tuple[str, ...]
    expense_categories_user_is_willing_to_stop: tuple[str, ...]
    payment_methods_user_will_consider: tuple[str, ...]
    max_installment_months: Optional[int]  # None => user will not consider installments


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str  # debit | credit
    amount: Optional[Decimal]  # None => amount must come from an image
    currency: str
    event_date: date
    settlement_date: Optional[date]
    status: str  # settled | pending | scheduled | failed | cancelled | unrealized ...
    linked_event_id: Optional[str]
    flexibility: str  # fixed | flexible | ...
    minimum_allowed_amount: Optional[Decimal]


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class SampleRequest(Request):
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str
    decision_explanation: str


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str  # full_payment | installments | ...
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int]
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: datetime
    source_type: str
    message_text: str


@dataclass(frozen=True)
class Image:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]

    @property
    def path(self) -> Path:
        from config import IMAGES_DIR
        return IMAGES_DIR / f"{self.image_id}.png"


@dataclass(frozen=True)
class Dataset:
    profiles: dict[str, Profile]                     # user_id -> Profile
    events: dict[str, list[Event]]                   # user_id -> events (sorted by event_date)
    events_by_id: dict[str, Event]
    rates: dict[tuple[date, str, str], Decimal]      # (date, from, to) -> rate
    requests: list[Request]
    samples: list[SampleRequest]
    payment_options: dict[str, list[PaymentOption]]  # request_id -> options
    messages: list[Message]
    images: list[Image]


# --------------------------------------------------------------------------- #
# Cell parsers
# --------------------------------------------------------------------------- #

def _dec(cell: str) -> Optional[Decimal]:
    cell = cell.strip()
    return Decimal(cell) if cell else None


def _int(cell: str) -> Optional[int]:
    cell = cell.strip()
    return int(Decimal(cell)) if cell else None


def _date(cell: str) -> Optional[date]:
    cell = cell.strip()
    return date.fromisoformat(cell) if cell else None


def _dt(cell: str) -> datetime:
    return datetime.fromisoformat(cell.strip().replace("Z", "+00:00"))


def _list(cell: str) -> tuple[str, ...]:
    cell = cell.strip()
    return tuple(p.strip() for p in cell.split("|") if p.strip()) if cell else ()


def _bool(cell: str) -> bool:
    return cell.strip().lower() == "true"


def _opt(cell: str) -> Optional[str]:
    cell = cell.strip()
    return cell or None


def _rows(name: str) -> list[dict[str, str]]:
    with open(DATASET_DIR / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #

def _request_fields(r: dict[str, str]) -> dict:
    return dict(
        request_id=r["request_id"],
        user_id=r["user_id"],
        request_date=_date(r["request_date"]),
        request_type=r["request_type"],
        requested_amount=_dec(r["requested_amount"]),
        desired_completion_date=_date(r["desired_completion_date"]),
        allows_partial_payment=_bool(r["allows_partial_payment"]),
        request_text=r["request_text"],
    )


def load_dataset() -> Dataset:
    profiles = {
        r["user_id"]: Profile(
            user_id=r["user_id"],
            home_currency=r["home_currency"],
            current_available_balance=_dec(r["current_available_balance"]),
            minimum_balance_to_keep=_dec(r["minimum_balance_to_keep"]),
            financial_priorities=_list(r["financial_priorities"]),
            expense_categories_to_protect=_list(r["expense_categories_to_protect"]),
            expense_categories_user_is_willing_to_reduce=_list(r["expense_categories_user_is_willing_to_reduce"]),
            expense_categories_user_is_willing_to_stop=_list(r["expense_categories_user_is_willing_to_stop"]),
            payment_methods_user_will_consider=_list(r["payment_methods_user_will_consider"]),
            max_installment_months=_int(r["max_installment_months"]),
        )
        for r in _rows("financial_profiles.csv")
    }

    events: dict[str, list[Event]] = {}
    events_by_id: dict[str, Event] = {}
    for r in _rows("financial_events.csv"):
        ev = Event(
            event_id=r["event_id"],
            user_id=r["user_id"],
            event_type=r["event_type"],
            description=r["description"],
            category=r["category"],
            direction=r["direction"],
            amount=_dec(r["amount"]),
            currency=r["currency"],
            event_date=_date(r["event_date"]),
            settlement_date=_date(r["settlement_date"]),
            status=r["status"],
            linked_event_id=_opt(r["linked_event_id"]),
            flexibility=r["flexibility"],
            minimum_allowed_amount=_dec(r["minimum_allowed_amount"]),
        )
        events.setdefault(ev.user_id, []).append(ev)
        events_by_id[ev.event_id] = ev
    for lst in events.values():
        lst.sort(key=lambda e: (e.event_date, e.event_id))

    rates = {
        (_date(r["rate_date"]), r["from_currency"], r["to_currency"]): _dec(r["rate"])
        for r in _rows("exchange_rates.csv")
    }

    requests = [Request(**_request_fields(r)) for r in _rows("requests.csv")]

    samples = [
        SampleRequest(
            **_request_fields(r),
            amount_safe_to_pay=_dec(r["amount_safe_to_pay"]),
            affordability_status=r["affordability_status"],
            recommended_payment_method=r["recommended_payment_method"],
            payment_plan=r["payment_plan"],
            earliest_date_for_full_payment=_date(r["earliest_date_for_full_payment"]),
            spending_changes_needed=r["spending_changes_needed"],
            decision_explanation=r["decision_explanation"],
        )
        for r in _rows("sample_requests.csv")
    ]

    payment_options: dict[str, list[PaymentOption]] = {}
    for r in _rows("request_payment_options.csv"):
        po = PaymentOption(
            payment_option_id=r["payment_option_id"],
            request_id=r["request_id"],
            payment_method=r["payment_method"],
            payment_amount=_dec(r["payment_amount"]),
            number_of_payments=_int(r["number_of_payments"]),
            first_payment_date=_date(r["first_payment_date"]),
            payment_frequency_days=_int(r["payment_frequency_days"]),
            financing_fee=_dec(r["financing_fee"]) or Decimal("0"),
            total_payable_amount=_dec(r["total_payable_amount"]),
        )
        payment_options.setdefault(po.request_id, []).append(po)

    messages = [
        Message(
            message_id=r["message_id"],
            user_id=r["user_id"],
            request_id=_opt(r["request_id"]),
            related_event_id=_opt(r["related_event_id"]),
            sent_at=_dt(r["sent_at"]),
            source_type=r["source_type"],
            message_text=r["message_text"],
        )
        for r in _rows("messages.csv")
    ]

    images = [
        Image(
            image_id=r["image_id"],
            user_id=r["user_id"],
            request_id=_opt(r["request_id"]),
            related_event_id=_opt(r["related_event_id"]),
        )
        for r in _rows("images.csv")
    ]

    return Dataset(
        profiles=profiles,
        events=events,
        events_by_id=events_by_id,
        rates=rates,
        requests=requests,
        samples=samples,
        payment_options=payment_options,
        messages=messages,
        images=images,
    )
