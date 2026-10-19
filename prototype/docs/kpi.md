# KPI Framework — Agentic Loan Lifecycle
## Validated Against Codebase · Updated with Measured Baselines

**Baseline source:** 39-case golden evaluation set (GS-001 – GS-039)
**Mock LLM baseline:** deterministic, 0.15s/case, $0/case
**Live LLM baseline:** Claude Opus via OpenRouter, 36s/case, $0.073/case

---

## Original vs Validated KPIs

| # | KPI | Original Target | ✅ Validated Target | Measured Baseline | How Measured | Change & Reason |
|---|-----|----------------|-------------------|-------------------|-------------|-----------------|
| 1 | **Critical field extraction accuracy** | 85%+ on priority fields | **90%+ on critical fields** | 91.3% (mock) | 17 critical fields scored in `evals/run_evals.py` against golden set | Raised: system already at 91.3%; "priority fields" renamed "critical fields" to match code definition |
| 2 | **All-field extraction accuracy** | *(not separately tracked)* | **88%+ across all 35+ fields** | 91.6% (mock) | All extracted fields vs golden values | **New KPI** — split from above; critical vs general fields have different thresholds |
| 3 | **Citation accuracy** | *(not tracked)* | **99%+ citations include line reference** | 99.6% (mock) | `clause.cite()` format checked per field | **New KPI** — citations are the evidence basis for regulatory traceability; near-perfect in tests |
| 4 | **Missing-document detection recall** | 90%+ | **95%+** | 100% (mock) | `hit_missing / exp_missing` across golden set | Raised: system achieves 100% in tests; 95% allows for edge cases in production |
| 5 | **Policy-rule retrieval precision** | 85%+ | **88%+ exception recall · 95%+ exception precision** | Recall 88.9%, Precision 100% | Exception flags vs SME labels in golden set | Split into recall + precision — both matter; recall ensures no missed risk flags |
| 6 | **Eligibility-rule accuracy vs SME labels** | 90%+ | **90%+ policy clause exact match** | 92.2% exact match (39 cases) | Policy status (PASS/FLAG/FAIL) per clause vs golden labels | Confirmed achievable; metric now explicitly "exact match on all 13 clauses" |
| 7 | **End-to-end pipeline processing time** | 50%+ reduction vs manual | **Pipeline ≤ 60s (real LLM) · Total cycle ≤ 5 days** | 36s pipeline (Claude), 0.15s (mock) | `avg_seconds_per_case` in evals | **Split into two metrics:** (a) technical pipeline time — already far exceeds target; (b) total cycle time (inc. human gates) — 5 days vs 22-day manual baseline = 77% reduction |
| 8 | **Manual touches** | 40%+ reduction | **8 agent-automatable steps fully automated · human touches ≤ 3** | 8 agents run without human input; HITL gates = 1–3 touches | Count of human approvals per case in `gate_events` | Redefined: "manual touches" = human gate decisions. 3 gates max vs unlimited manual steps = measurable. Target: avg 1.5 touches/case (most cases skip Gate 1) |
| 9 | **Credit-memo drafting time** | 40%+ reduction | **90%+ reduction — decision_summary.md auto-generated** | Auto-generated in `report.py` (includes all 13 policy checks, risk scorecard, conditions) | Presence of decision_summary.md with all required sections | Raised significantly: memo is fully automated — LLM drafts narrative, system populates all data fields; human only reviews, not drafts |
| 10 | **Human override rate** | Tracked; < 20% after tuning | **< 20% after 30-day tuning period** | Not yet measured in production | `override=True` entries in `gate_events` / total credit decisions | Confirmed measurable — override flag stored per decision in orchestrator |
| 11 | **Audit completeness** | 100% traceable | **100% — SHA-256 hash chain verified** | 39/39 chains verified · 42/42 SoD blocks enforced | `verify_chain()` on every case + daily automated job | **Already achieved.** KPI met at POC stage. Production adds WORM storage for immutability |
| 12 | **Cost per processed case** | Measured vs manual | **< $0.50/case (LLM cost) · Measure total vs manual** | $0.073/case (Claude Opus) · $0/case (mock) | `decision_record.json` → `controls.llm_cost_usd` | Target set: $0.073 measured gives comfortable headroom. Total cost (infra + LLM) at 500 cases/month ≈ $1.66/case vs est. $180/case manual |

---

## New KPIs (not in original list — required for production)

| # | KPI | Target | Measured | Rationale |
|---|-----|--------|----------|-----------|
| 13 | **Segregation of Duties enforcement** | 100% of invalid attempts blocked | 42/42 blocked in tests | Regulatory requirement — SoD cannot have partial compliance |
| 14 | **Data validation gate (Gate 0) fire rate** | < 30% of cases after LLM tuning | Not yet measured in production | High fire rate = poor extraction quality; track to guide model selection |
| 15 | **Hybrid RAG lift vs BM25-only** | ≥ +5% policy clause recall | Not yet A/B tested | Justifies Qdrant Cloud cost; measure on golden set with/without vector layer |
| 16 | **API availability** | 99.95% | Not yet measured | SLO required before client handover |
| 17 | **Gate turnaround time** | SCM < 4h · Committee < 24h · Board < 48h | Not yet measured | Defines the human SLA component of total cycle time |
| 18 | **False positive rate — sanctions/PEP screening** | < 10% of hits are false positives | Not yet measured | High false positives = unnecessary compliance gate triggers and analyst time waste |
| 19 | **Pipeline error rate** | < 1% of cases fail with unhandled exception | Not yet measured in production | Reliability SLO |
| 20 | **Unsafe recommendation rate** | 0 — system never recommends approve on a hard-fail case | 0/39 in golden set | Safety-critical: must remain 0 after every model change |

---

## KPI Dashboard — What Is Measurable Today

| KPI | Measurable now? | Data source |
|-----|----------------|-------------|
| Critical field accuracy | ✅ | `evals/run_evals.py` on golden set |
| Citation accuracy | ✅ | `evals/run_evals.py` |
| Missing-doc recall | ✅ | `evals/run_evals.py` |
| Policy clause exact match | ✅ | `evals/run_evals.py` |
| Exception recall / precision | ✅ | `evals/run_evals.py` |
| Pipeline processing time | ✅ | `avg_seconds_per_case` in eval results |
| LLM cost per case | ✅ | `decision_record.json → controls.llm_cost_usd` |
| Override rate | ✅ (production) | `gate_events` table → `override=True` |
| Audit completeness | ✅ | `verify_chain()` + daily job |
| SoD enforcement | ✅ | `human_action_blocked` audit entries |
| Unsafe recommendation rate | ✅ | `evals/run_evals.py` → unsafe_cases |
| Gate turnaround time | ⚠️ Production only | `gate_events.decided_at - gate_events.created_at` |
| API availability | ⚠️ Production only | Cloud Monitoring uptime check |
| Hybrid RAG lift | ⚠️ Needs A/B test | Run evals with/without `QDRANT_URL` |
| Gate 0 fire rate | ⚠️ Production only | `gate_events WHERE gate='data_validation'` |
| Sanctions false positive rate | ⚠️ Manual review | Compliance officer feedback on overrides |

---

## POC vs Production Targets

| KPI | POC Target | Production Target | Gap |
|-----|-----------|-------------------|-----|
| Critical field accuracy | 90%+ | 95%+ | Needs real-document testing with OCR |
| Missing-doc recall | 95%+ | 98%+ | Edge cases: expired docs, alternate formats |
| Policy clause accuracy | 90%+ | 95%+ | Hybrid RAG lift expected to close gap |
| Total cycle time | ≤ 5 days | ≤ 3 days | Faster human gate SLAs + notification automation |
| Cost per case (LLM) | < $0.50 | < $0.25 | Switch to claude-sonnet-4-5 (3× cheaper, similar accuracy) |
| Override rate | < 20% | < 15% | 6-month model tuning on production decisions |
| API availability | N/A | 99.95% | Multi-region deployment (Week 7) |
| Unsafe recommendations | 0 | 0 | Non-negotiable — enforced by golden set regression on every deploy |

---

## Measurement Cadence

| Frequency | What is measured |
|-----------|-----------------|
| Every deploy | Golden set regression (39 cases) — must pass before merge |
| Daily | Audit chain integrity verification |
| Weekly | Override rate, gate turnaround time, cost per case |
| Monthly | Full eval run on expanded case set, hybrid RAG lift A/B |
| Quarterly | SME re-labelling of golden set, policy threshold review, model upgrade assessment |
