# Usage Report — final full-dataset run

Requests processed: **250**  
Provider: **Anthropic**  
Model calls: **466**

| Model | Calls | Input tokens | Output tokens | Est. cost (USD) |
|---|---:|---:|---:|---:|
| claude-opus-5 | 466 | 175,945 | 63,366 | 7.3916 |

- Total input tokens: **175,945**
- Total output tokens: **63,366**
- Total tokens: **239,311**
- Average tokens per request: **957.2**
- Estimated total cost: **$7.3916**
- Estimated cost per request: **$0.02957**

Cost uses the list prices in `code/usage_report.py`. Cached LLM responses under `code/cache/` are counted once, on the run that produced them. No credentials or configuration are included in this file.
