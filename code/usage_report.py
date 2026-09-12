"""Phase 8 — build code/evaluation/usage_report.md from cache/usage.jsonl.

Never includes keys or configuration; only aggregate counts and estimated cost.
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal

from config import USAGE_LOG, USAGE_REPORT

# USD per 1M tokens (input, output). Update if the provider's list price changes.
PRICING_USD_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("15"), Decimal("75")),
    "claude-sonnet-5": (Decimal("3"), Decimal("15")),
    "claude-haiku-4-5-20251001": (Decimal("1"), Decimal("5")),
}


def write_usage_report(num_requests: int) -> None:
    calls = 0
    per_model: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0})
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            m = per_model[rec["model"]]
            m["calls"] += 1
            m["in"] += int(rec.get("input_tokens", 0))
            m["out"] += int(rec.get("output_tokens", 0))
            calls += 1

    total_in = sum(m["in"] for m in per_model.values())
    total_out = sum(m["out"] for m in per_model.values())
    total_tokens = total_in + total_out
    total_cost = Decimal("0")
    lines = [
        "# Usage Report — final full-dataset run",
        "",
        f"Requests processed: **{num_requests}**  ",
        f"Provider: **Anthropic**  ",
        f"Model calls: **{calls}**",
        "",
        "| Model | Calls | Input tokens | Output tokens | Est. cost (USD) |",
        "|---|---:|---:|---:|---:|",
    ]
    for model, m in sorted(per_model.items()):
        pin, pout = PRICING_USD_PER_MTOK.get(model, (Decimal("0"), Decimal("0")))
        cost = (Decimal(m["in"]) * pin + Decimal(m["out"]) * pout) / Decimal(1_000_000)
        total_cost += cost
        lines.append(f"| {model} | {m['calls']} | {m['in']:,} | {m['out']:,} | {cost:.4f} |")
    if not per_model:
        lines.append("| (no LLM calls — run used --no-llm or a fully warm cache) | 0 | 0 | 0 | 0.0000 |")

    avg_tokens = Decimal(total_tokens) / num_requests if num_requests else Decimal("0")
    avg_cost = total_cost / num_requests if num_requests else Decimal("0")
    lines += [
        "",
        f"- Total input tokens: **{total_in:,}**",
        f"- Total output tokens: **{total_out:,}**",
        f"- Total tokens: **{total_tokens:,}**",
        f"- Average tokens per request: **{avg_tokens:.1f}**",
        f"- Estimated total cost: **${total_cost:.4f}**",
        f"- Estimated cost per request: **${avg_cost:.5f}**",
        "",
        "Cost uses the list prices in `code/usage_report.py`. Cached LLM responses under "
        "`code/cache/` are counted once, on the run that produced them. No credentials or "
        "configuration are included in this file.",
        "",
    ]
    USAGE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    USAGE_REPORT.write_text("\n".join(lines), encoding="utf-8")
