# Agentic Loan Lifecycle Management (USTech Assignment 1)

The model reads and writes, code computes and applies policy, people decide. The prototype is measured: a 39-case golden set (real cases, corner cases and jailbreak scenarios) is the release gate.

**Overall completion: ~95%** — all core engineering requirements met.

| Requirement | Status |
|---|---|
| Lifecycle map — current process + 5 high-value AI areas | ✅ |
| 8-agent ecosystem (Intake → Disbursement) | ✅ |
| Working pipeline: intake → extraction → policy → HITL → audit | ✅ |
| Architecture: RAG (vector + BM25), security, HITL, auditability | ✅ |
| Before vs. after with quantified impact | ✅ |
| 6–8 week POC plan with milestones and KPIs | ✅ |
| Policy Library (browser-editable, RAG auto re-index) | ✅ |
| Case Report with confidence + reliability % | ✅ |
| Credential management — `.env.local`, `.gitignore`, key isolation | ✅ |

---

## What is built

### Pipeline — 8 agents in sequence

| # | Agent | What it does |
|---|---|---|
| 1 | **Origination & Intake** | Parses application form; identifies required document types |
| 2 | **Document Intelligence** | Extracts 35+ fields from 7 document types; confidence scores; line-level citations |
| 3 | **Completeness** | Identifies missing documents; drafts RM request email |
| 4 | **Due Diligence** | Screens directors, UBOs and entity against sanctions + PEP lists |
| 5 | **Policy & Eligibility** | 13 policy checks (POL-2.1 – POL-5.2) against versioned credit policy |
| 6 | **Risk** | 8-factor scorecard (30 pts), internal rating (1–10), indicative 1-yr PD |
| 7 | **Approval & Workflow** | Recommendation, conditions, delegated authority gates |
| 8 | **Disbursement & Monitoring** | Blocks disbursement until conditions precedent cleared; schedules covenants |

### Knowledge layer — Hybrid RAG

- **9 policy documents**, 143 named clauses (POL, DOA, KYC, EDD, SAN, COL, RRM, RAS, PPG)
- **Hybrid search**: 40% BM25 keyword + 60% Qdrant vector cosine (`openai/text-embedding-3-small` via OpenRouter, 1536-dim)
- **Auto re-index**: edit any clause in the browser → SHA-256 changes → Qdrant rebuilds on next server start

### Web UI (FastAPI + Alpine.js)

- **Dashboard** — live case list, RAG status badge, eval runner
- **Case Report tab** (default) — reliability %, avg confidence, decision pipeline flow, grounded evidence table with `source:line` citations, policy flag detail
- **Policy Library** — browse and edit all 9 policy documents in the browser
- **Decision Log** — full audit trail with hash-chain verification
- **Human-in-the-loop gate** — triggered when avg field confidence < 75%

### Demo case — APP-2026-0201 (Sunrise Cold Chain Logistics Ltd)

- USD 3,800,000 secured term loan · 60 months
- 12 PASS / 1 FLAG (DSCR 1.39× — POL-2.3 threshold 1.40×)
- Escalated to Regional Credit Committee
- **APPROVED WITH CONDITIONS**: C01 (DSRA pre-disbursement) + C02 (annual DSCR covenant)
- Risk grade BBB · score 8/30 · PD 0.10%
- 35/35 fields verified · 100% reliability · 98% avg confidence

### Security controls

- API keys in `.env.local` (git-ignored); `.gitignore` blocks all `*.env` files
- PII tokenised before any model call; unmasked only in final outputs
- SHA-256 hash-chained audit log — tampering breaks the chain
- Prompt injection quarantined before model call; role-based segregation of duties

---

## Quick start

```bash
cd prototype

# Start the web server (loads .env.local automatically)
double-click start_web.bat          # Windows
# OR:
python -m uvicorn web.app:app --host 0.0.0.0 --port 8000

# Open http://localhost:8000
# Login: amara.osei / demo123
```

**Prerequisites**: Python 3.10+, Docker for Qdrant

```bash
# Start Qdrant (vector DB)
docker run -p 6333:6333 qdrant/qdrant

# Install dependencies
pip install fastapi uvicorn qdrant-client
```

**Environment** — copy `.env` to `.env.local` and fill in your OpenRouter key:

```bash
cp prototype/.env prototype/.env.local
# Edit .env.local:
# OPENROUTER_API_KEY=sk-or-v1-...
```

### CLI commands

```bash
python run_demo.py                                    # both sample cases, offline, scripted approvers
python run_demo.py --app APP-2026-0201 --interactive  # you are the credit officer and approver
python evals/run_evals.py --report                    # golden set (39 cases) → evals/results/REPORT.md
python evals/run_evals.py --llm openrouter --report   # live LLM run via OpenRouter
python run_demo.py --redteam-demo                     # prompt injection quarantined; results unchanged
python run_demo.py --policy-change-demo               # LTV limit cut in v3.3; old decision still replays
python run_demo.py --replay output/APP-2026-0157      # re-run a recorded decision and compare
python run_demo.py --tamper-demo                      # audit log detects an edited approval
python -m unittest discover -s tests                  # 20 tests, including the golden-set release gate
```

---

## Repository layout

```
loan-lifecycle/
├── README.md
├── SOLUTION.md                     Write-up: lifecycle map, agent ecosystem, architecture, POC plan
├── prototype/
│   ├── .env                        Template — non-secret defaults (commit this)
│   ├── .env.local                  Real keys — NEVER commit (git-ignored)
│   ├── .gitignore
│   ├── start_web.bat               Start web server on Windows (loads .env.local)
│   ├── run_demo.py                 CLI entry point
│   ├── loanagent/
│   │   ├── agents.py               8 agent classes and document schemas
│   │   ├── orchestrator.py         Case state machine, HITL gates, SoD / authority controls
│   │   ├── llm.py                  MockLLM · OpenRouterLLM · ClaudeLLM
│   │   ├── rag.py                  HybridPolicyKB — BM25 + Qdrant vector search
│   │   ├── knowledge.py            Versioned policy KB: clause lookup, BM25, parameters
│   │   ├── citations.py            Verifies each extracted value is on the cited line
│   │   ├── security.py             PII tokenisation; prompt-injection quarantine
│   │   ├── replay.py               Deterministic replay of a recorded decision
│   │   ├── audit.py                Hash-chained audit log: write, verify, trace
│   │   └── report.py               Decision summary and decision record
│   ├── web/
│   │   ├── app.py                  FastAPI server (REST API + static files)
│   │   └── static/index.html       Alpine.js single-page UI
│   ├── evals/
│   │   ├── generate_cases.py       Builds the 39-case golden set
│   │   ├── run_evals.py            Scores a run; writes REPORT.md
│   │   └── results/                Recorded runs (mock, openrouter, claude)
│   ├── docs/
│   │   ├── video_script.md         12-part video walkthrough script (22–25 min)
│   │   ├── test_scenarios.md       All test scenarios by category
│   │   ├── architecture.md         Component diagram + layers
│   │   ├── data_flow.md            Data transformation diagram
│   │   ├── model_risk_pack.md      SR 11-7 style agent cards + MRM governance
│   │   ├── unit_economics.md       Cost per case vs. analyst time
│   │   ├── deployment_mapping.md   Azure primary, AWS + GCP alternatives
│   │   ├── first_two_weeks.md      Stakeholders, 20-case replay, kill criteria
│   │   └── adr/                    5 Architecture Decision Records
│   ├── data/
│   │   ├── policy/                 Credit policy v3.2 + v3.3; registry.json
│   │   ├── applications/           4 fictional applications with supporting documents
│   │   └── screening_watchlist.json
│   ├── tests/
│   │   ├── test_workflow.py        End-to-end pipeline + golden-set gate
│   │   └── test_evidence.py        Citation accuracy + PII controls
│   └── output/                     Decision summaries, audit logs, traces (last run)
```

---

## Eval results

| Run | Cases | Pass | Unsafe recs | Policy fails open | Auth violations |
|---|---|---|---|---|---|
| Mock (baseline) | 39 | 39 | 0 | 0 | 0 |
| OpenRouter (claude-sonnet-4-5) | 30 | 30 | 0 | 0 | 0 |

Cost on the live model: **≈ USD 0.05–0.07 per case** via OpenRouter.

---

## LLM + Embedding providers

| Setting | Default | Override |
|---|---|---|
| LLM | `anthropic/claude-sonnet-4-5` via OpenRouter | `LOAN_AGENT_MODEL` in `.env.local` |
| Embeddings | `openai/text-embedding-3-small` via OpenRouter | `LOAN_AGENT_EMBED_MODEL` |
| Vector DB | Qdrant at `http://localhost:6333` | `QDRANT_URL` |

All providers fall back gracefully: OpenRouter → Anthropic direct → MockLLM (offline). Vector search falls back to BM25-only if Qdrant is unreachable.

---

*All borrowers, people, documents and the policy are fictional.*
