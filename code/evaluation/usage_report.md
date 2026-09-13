# Usage Report — final full-dataset run

Requests processed: **250**  
Provider: **Anthropic** (Claude API, `anthropic` Python SDK)  
Model calls: **231** — one structured-output call per message (215) and per image (16); every request then reuses these cached interpretations, so the deterministic engine makes no further calls.

| Model | Calls | Input tokens | Output tokens | Cache-read tokens | Cache-write tokens | Est. cost (USD) |
|---|---:|---:|---:|---:|---:|---:|
| claude-opus-5 | 231 | 86,045 | 31,479 | 464,370 | 2,019 | 1.4620 |

- Total input tokens (uncached): **86,045**
- Total output tokens: **31,479**
- Cache-read / cache-write input tokens: **464,370** / **2,019** (the shared system prompt)
- Total tokens: **583,913**
- Average tokens per request: **2335.7**
- Estimated total cost: **$1.4620**
- Estimated cost per request: **$0.00585**

Cost uses the list prices in `code/usage_report.py` (Opus 5: $5 / $25 per 1M input / output tokens; $0.50 cache read, $6.25 cache write). Evidence is interpreted once and cached under `code/cache/`; the numbers above are the calls that produced the cache used by the final run. Explanations are template-generated (no model calls). No credentials or configuration are included in this file.
