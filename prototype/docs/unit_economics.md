# Unit economics

**Status:** measured on the golden set with Claude Opus 5.5 (`evals/results/claude-opus-5-5/results.json`): **7,320 tokens and USD 0.073 per case on average**, about 8 model calls per case, 36 seconds per case run sequentially. A real commercial pack is much larger than a golden case, so the real-pack figures below are scaled estimates, to be measured in the POC.

```bash
ANTHROPIC_API_KEY=... python evals/run_evals.py --llm claude --label claude-opus-5-5 --report
```

## Model calls per case

| Step | Calls | Notes |
|---|---|---|
| Extraction, one call per document | 5 to 6 (sample cases); 15 to 20 in a real pack | Structured JSON with citations; one retry on a schema failure |
| RM request draft | 0 or 1 | Only when documents are missing |
| Risk narrative | 1 | |
| Decision rationale | 1 | |
| **Total** | **about 7 to 9** on the sample cases | Policy checks, rating and routing make no model calls |

## Cost per case

Prices used by `llm.py` (USD per million tokens, input / output): Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50.

| Scenario | Input tokens | Output tokens | Opus 5.5 | Sonnet 5.5 |
|---|---|---|---|---|
| Golden-set case, **measured** (5 to 6 short documents) | ~4.5k | ~2.8k | **$0.073** | ~$0.037 (estimate) |
| Real commercial pack, estimate (15 to 20 documents, ~150k tokens, as assumed in SOLUTION.md) | ~170k | ~25k | ~$1.18 | ~$0.59 |

Output tokens dominate the measured cost (about 75%), because every extracted value is returned with its citation.

## Against analyst cost

| | Per case |
|---|---|
| Analyst reading, spreading and memo time saved (SOLUTION.md section 5: 24 h down to 7 h) | 17 h × $85 = **$1,445** |
| Model cost, golden-set case, Opus 5.5 (measured) | **$0.073** |
| Model cost, real pack, Opus 5.5 (estimate) | **~$1.20** |
| Platform cost at ~8 cases a day on scale-to-zero services | small; to be measured in the POC |

Model cost is around a thousandth of the analyst time it replaces, so the choice of model should be made on accuracy, not price. If a golden-set run shows Sonnet 5.5 or Haiku 5.5 meets the extraction targets on some document types, the gateway can route those types to the cheaper model; the golden set decides, per document type.

## What would change this
- Scanned documents need OCR first (Azure AI Document Intelligence or equivalent), priced per page.
- Retries and long tables raise output tokens; the harness records actuals.
- Prompt caching of the system prompt and schema reduces input cost when documents of the same type are processed together.
