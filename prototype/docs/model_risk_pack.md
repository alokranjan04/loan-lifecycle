# Model risk pack

How the prototype splits into parts that model risk management (MRM) **validates** and parts that are **monitored**, with a short card per agent. Written for SR 11-7 style governance; map to the bank's own MRM standard in discovery.

## What is validated and what is monitored

| Component | Type | Treatment | Why |
|---|---|---|---|
| Ratio calculations, 14 policy checks, NOT_EVALUATED rules | Deterministic code | **Validated** like any rules model: clause-by-clause tests, replay on historical cases | It decides eligibility, so it must be exact and reproducible |
| Risk scorecard (rating 1 to 10) | Deterministic code | **Validated**: factor weights, rank-ordering against historical outcomes, fairness test on any scored segment | It feeds pricing and authority |
| Recommendation, conditions, routing under delegated authority (incl. POL-6.1 escalation) | Deterministic code | **Validated** against the DoA matrix | Routing below authority is a control failure |
| Human gate controls (SoD, authority, override rationale) | Deterministic code | **Validated** as an IT control | These keep the decision with people |
| Field extraction with citations | Language model | **Monitored**: field accuracy and citation correctness on a golden set and on analyst corrections | Errors are caught by the citation check and the analyst; it never decides |
| Drafted text (RM request, risk narrative, rationale) | Language model | **Monitored**: sampled human review; no numbers in drafts that are not in the cited facts | Read by people before use |
| Injection screen, PII masking | Deterministic code | **Validated** as security controls; red-team each release | Protects the model input |

## Agent cards

| Agent | Uses a model? | Inputs | Output | Known limits | Fallback when the model is down |
|---|---|---|---|---|---|
| Intake | No | Application form | Checklist, form gaps | Product rules must be kept current | Not affected |
| Document Intelligence | Yes, extraction | Masked, line-numbered documents | Fields with citations; withheld unverified values; conflicts; security flags | Unusual layouts (mock reads 0 of 4 varied layouts; Claude Opus 5.5 reads all 4 after the extract-v3 fixes); citation proves the value is on the line, not that it is the right value | Case queued; analyst keys the spread manually in the workbench |
| Completeness | Drafting only | Checklist, documents found | Missing items, drafted RM email | | Template email |
| Due Diligence | No (reads screening results) | Extracted parties, screening feed | KYC validity, sanctions/PEP/adverse media, conduct | Depends on the bank's screening tool | Not affected |
| Policy & Eligibility | No | Verified fields, policy version in force | PASS / FLAG / FAIL / NOT_EVALUATED per clause, `POL-x@version` | Encoding errors are the main risk; mitigated by SME sign-off per clause | Not affected |
| Risk | Drafting only | Facts, checks | Rating, observations, narrative | Scorecard is illustrative until calibrated | Template narrative |
| Approval & Workflow | Drafting only | Checks, findings, DoA | Recommendation, conditions, route, escalation | | Template rationale |
| Disbursement | No | Approval, conditions | CP tracker, readiness gate | | Not affected |

## Evidence held for each release

- Golden-set report (`evals/results/REPORT.md`) with the release gate in `tests/test_evidence.py::GoldenSetGate`: 0 unsafe recommendations, 0 fail-open checks, 0 approvals without the required authority, 100% agreement on standard cases.
- Decision record per case with model id, prompt version (`extract-v3`), policy version, effective date and sha256; hash-chained audit log.
- Replay: `python run_demo.py --replay output/<case>` re-runs a past decision on its recorded extraction and pinned policy and reports any difference.

## Change control

| Change | What must be re-run before release |
|---|---|
| New model version or prompt | Full golden set with `--llm claude`; compare to the last recorded run; no regression on safety metrics |
| Policy text or parameter change | New version in `registry.json` with an effective date; clause tests; policy-change replay on recent cases |
| Rule or scorecard code change | Unit tests, golden set, MRM sign-off on the changed component |

## Open items for MRM
- Real-model accuracy is recorded only on the first 30 of the 39 synthetic golden cases (Claude Opus 5.5: 28/30 first run, 30/30 after fixes made on the same cases). Production thresholds are the POC KPIs in SOLUTION.md section 6.6, measured on held-out historical cases.
- Scorecard calibration on the bank's own default history.
- Fairness testing applies if the scope extends to sole traders or individuals.
