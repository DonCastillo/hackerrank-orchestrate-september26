"""Phase 8 — build code/evaluation/usage_report.md from cache/usage.jsonl.

Never includes keys or configuration; only aggregate counts and estimated cost.
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal

from config import USAGE_LOG, USAGE_REPORT

# USD per 1M tokens (input, output, cache read, cache write). Anthropic list prices, Sept 2026.
PRICING_USD_PER_MTOK: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5"), Decimal("25"), Decimal("0.50"), Decimal("6.25")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10"), Decimal("0.20"), Decimal("2.50")),
    "claude-haiku-4-5": (Decimal("1"), Decimal("5"), Decimal("0.10"), Decimal("1.25")),
}


def write_usage_report(num_requests: int) -> None:
    calls = 0
    per_model: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cr": 0, "cw": 0})
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            m = per_model[rec["model"]]
            m["calls"] += 1
            m["in"] += int(rec.get("input_tokens", 0))
            m["out"] += int(rec.get("output_tokens", 0))
            m["cr"] += int(rec.get("cache_read_input_tokens", 0) or 0)
            m["cw"] += int(rec.get("cache_creation_input_tokens", 0) or 0)
            calls += 1

    total_in = sum(m["in"] for m in per_model.values())
    total_out = sum(m["out"] for m in per_model.values())
    total_cr = sum(m["cr"] for m in per_model.values())
    total_cw = sum(m["cw"] for m in per_model.values())
    total_tokens = total_in + total_out + total_cr + total_cw
    total_cost = Decimal("0")
    lines = [
        "# Usage Report — final full-dataset run",
        "",
        f"Requests processed: **{num_requests}**  ",
        f"Provider: **Anthropic** (Claude API, `anthropic` Python SDK)  ",
        f"Model calls: **{calls}** — one structured-output call per message (215) and per image (16); "
        f"every request then reuses these cached interpretations, so the deterministic engine makes no further calls.",
        "",
        "| Model | Calls | Input tokens | Output tokens | Cache-read tokens | Cache-write tokens | Est. cost (USD) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model, m in sorted(per_model.items()):
        pin, pout, pcr, pcw = PRICING_USD_PER_MTOK.get(model, (Decimal("0"),) * 4)
        cost = (Decimal(m["in"]) * pin + Decimal(m["out"]) * pout + Decimal(m["cr"]) * pcr + Decimal(m["cw"]) * pcw) / Decimal(1_000_000)
        total_cost += cost
        lines.append(f"| {model} | {m['calls']} | {m['in']:,} | {m['out']:,} | {m['cr']:,} | {m['cw']:,} | {cost:.4f} |")
    if not per_model:
        lines.append("| (no LLM calls — run used --no-llm or a fully warm cache) | 0 | 0 | 0 | 0 | 0 | 0.0000 |")

    avg_tokens = Decimal(total_tokens) / num_requests if num_requests else Decimal("0")
    avg_cost = total_cost / num_requests if num_requests else Decimal("0")
    lines += [
        "",
        f"- Total input tokens (uncached): **{total_in:,}**",
        f"- Total output tokens: **{total_out:,}**",
        f"- Cache-read / cache-write input tokens: **{total_cr:,}** / **{total_cw:,}** (the shared system prompt)",
        f"- Total tokens: **{total_tokens:,}**",
        f"- Average tokens per request: **{avg_tokens:.1f}**",
        f"- Estimated total cost: **${total_cost:.4f}**",
        f"- Estimated cost per request: **${avg_cost:.5f}**",
        "",
        "Cost uses the list prices in `code/usage_report.py` (Opus 5: $5 / $25 per 1M input / output tokens; "
        "$0.50 cache read, $6.25 cache write). Evidence is interpreted once and cached under `code/cache/`; "
        "the numbers above are the calls that produced the cache used by the final run. Explanations are "
        "template-generated (no model calls). No credentials or configuration are included in this file.",
        "",
    ]
    USAGE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    USAGE_REPORT.write_text("\n".join(lines), encoding="utf-8")
