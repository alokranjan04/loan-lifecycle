# ADR 0001: The language model is excluded from the credit decision

**Status:** accepted · **Date:** 2026-10-16

## Context
Credit decisions are regulated. Model risk (SR 11-7 or the local equivalent) must validate anything that decides, and a credit officer must be able to explain any outcome to a borrower, an auditor or a regulator. A language model is non-deterministic, changes when the vendor ships a new version, and can be steered by text inside the documents it reads.

## Decision
The model reads and writes; code computes and applies policy; people decide.
- **Model:** extracts fields with a `document:line` citation, and drafts the RM request, the risk narrative and the decision rationale.
- **Code:** ratios, all 14 policy checks, the scorecard, the recommendation, the conditions, and routing under delegated authority (`agents.py`, `knowledge.py`).
- **People:** compliance clearance and credit approval, with segregation of duties, authority and override rationale enforced in `validate_human_action`.

Every extracted value is checked by `citations.verify` before it can reach a rule. A value that is not on the line it cites is withheld and the check becomes NOT_EVALUATED, which returns the case to the RM. Missing evidence never passes.

## Consequences
- MRM validates a small deterministic core (rules, scorecard, routing) that replays exactly; the model is monitored, not validated as a decision model (see `docs/model_risk_pack.md`).
- A prompt injection can at worst corrupt an extraction, which the citation check and the analyst catch; it cannot change a threshold or an approval. The red-team demo shows identical policy results with and without the attack.
- We give up "AI decides" headlines. The value comes from removing reading and typing, which is where analyst time goes.
- Evidence: in the golden-set run, 0 unsafe recommendations, 0 fail-open checks and 0 approvals below authority (`evals/results/REPORT.md`).
