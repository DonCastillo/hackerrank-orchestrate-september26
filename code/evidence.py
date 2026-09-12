"""Phase 4 — turn messages and images into structured amendments the engine can apply.

Design constraints (from AGENTS.md §1 / §6.3):
  * Message/image content is UNTRUSTED. Embedded instructions never override the rules.
  * Only facts that clarify, amend, delay, cancel, or confirm a supplied event are used.
  * Every LLM call is cached under code/cache/ by a content hash so re-runs are
    deterministic and make zero network calls. Usage is appended to cache/usage.jsonl.
  * With --no-llm, `gather_amendments` returns an empty AmendmentSet and the engine
    falls back to the financially safer interpretation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from config import CACHE_DIR, USAGE_LOG
from loader import Dataset, Request


@dataclass(frozen=True)
class Amendment:
    """A single evidence-backed change to the supplied financial facts."""
    action: str                       # cancel | amend_amount | amend_date | confirm | pending | new_flow
    event_id: Optional[str] = None    # target event, when one-to-one
    amount: Optional[Decimal] = None
    on: Optional[date] = None
    currency: Optional[str] = None
    source: str = ""                  # message_id / image_id
    confidence: str = "high"          # high | medium | low
    note: str = ""


@dataclass
class AmendmentSet:
    by_event: dict[str, list[Amendment]] = field(default_factory=dict)
    by_request: dict[str, list[Amendment]] = field(default_factory=dict)

    def for_event(self, event_id: str) -> list[Amendment]:
        return self.by_event.get(event_id, [])

    def for_request(self, request_id: str) -> list[Amendment]:
        return self.by_request.get(request_id, [])


# --------------------------------------------------------------------------- #
# Cache + usage accounting (stdlib only; anthropic imported lazily)
# --------------------------------------------------------------------------- #

def _cache_key(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _cache_get(key: str) -> Optional[dict]:
    p = CACHE_DIR / f"{key}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _cache_put(key: str, value: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


def _record_usage(model: str, input_tokens: int, output_tokens: int, request_id: Optional[str], kind: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(USAGE_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "provider": "anthropic",
            "model": model,
            "kind": kind,
            "request_id": request_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }) + "\n")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def gather_amendments(ds: Dataset, use_llm: bool) -> AmendmentSet:
    """Interpret every message and image once, up front, and index the results."""
    if not use_llm:
        return AmendmentSet()
    raise NotImplementedError("Phase 4")
