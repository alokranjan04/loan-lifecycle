# ADR 0005: Demos run offline on a deterministic mock; real-model quality is measured and recorded

**Status:** accepted · **Date:** 2026-10-16

## Context
A live demo that depends on network access and a model endpoint can fail in the room. A demo that only runs on a mock proves the plumbing but says nothing about how well a real model reads documents.

## Decision
- `MockLLM` is a deterministic, rule-based reader of the sample layouts. It makes every demo, test and the golden-set gate reproducible with no network or key.
- `ClaudeLLM` (`llm.py`) is the real back end: Claude Opus 5.5 by default (`claude-opus-5-5`, overridable with `LOAN_AGENT_MODEL`), structured JSON output with a schema, documents wrapped as untrusted data, and a refusal check. It goes through the same citation verification as the mock.
- Real-model results are produced by `python evals/run_evals.py --llm claude --label claude-opus-5-5` and saved under `evals/results/<label>/` with tokens and cost per case. The workbench Evaluation tab and `REPORT.md` compare runs side by side.
- Past decisions can be replayed exactly with `ReplayLLM`, which feeds back the recorded extraction.

## Consequences
- The demo cannot fail on connectivity, and the numbers shown for the mock are honest about what the mock is: it reads the 22 standard layouts perfectly and fails safe (returns to the RM) on the 4 varied layouts.
- Real-model runs are recorded: `claude-opus-5-5-extract-v2` (first run, 28 of 30, both misses safe) and `claude-opus-5-5` (after fixes, 30 of 30, USD 0.073 per case). Both stay in the report so the improvement, and the risk that the fixes are tuned to these cases, are visible.
- The mock must never be presented as model quality; `REPORT.md` labels every run with its back end.
