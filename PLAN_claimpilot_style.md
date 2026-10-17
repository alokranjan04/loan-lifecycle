> **Superseded on 2026-10-16** by [PLAN_evidence_first.md](PLAN_evidence_first.md). Alok chose the evidence-first direction; see [CRITIQUE_claimpilot_approach.md](CRITIQUE_claimpilot_approach.md) for why.

# Plan: Rebuild the Loan Lifecycle Prototype in the ClaimPilot Style (Azure-native)

**Status:** Draft for approval · **Scope:** plan only, nothing built yet · **Source of style:** `Azure-claimpilot/docs/ClaimPilot_Project_Spec.md` (Deployment Spec v1.0) · **Source of content:** `loan-lifecycle/SOLUTION.md` and `loan-lifecycle/prototype/`

Working name for the rebuilt project: **LoanPilot**.

---

## 0. What I found

### 0.1 ClaimPilot

The ClaimPilot folder contains a single document, `docs/ClaimPilot_Project_Spec.md` (about 18 KB). There is no code yet. It is the Azure deployment spec and it refers to a "main spec" (FastAPI surface, Pydantic contracts, LangGraph topology, agent design) that is not in the folder. Its structure is:

1. Component to Azure service mapping table (Primary, Alternatives, Why)
2. Azure-native architecture diagram (ASCII)
3. Layer-by-layer detail (models, intake, RAG, orchestration, MCP tools, async and state, evaluation, observability, security)
4. CI/CD and IaC (Azure Pipelines, ACR, Bicep, eval gate, revision canary)
5. Cost and footprint notes
6. What changes in the codebase (implied repo layout)
7. Interview talking points
8. Build order

**Tech stack:** Python, FastAPI, Pydantic contracts, LangGraph (on Azure Container Apps, or Azure AI Foundry Agent Service), Azure OpenAI GPT-4o and GPT-4o mini with model routing, `text-embedding-3-large`, Azure AI Search (hybrid plus semantic ranker), Azure AI Document Intelligence, Service Bus with KEDA, Cosmos DB checkpointer, Azure Cache for Redis, Azure SQL audit, Blob Storage, AI Foundry Evaluation, AI Content Safety, AI Language PII, Application Insights and OpenTelemetry, Key Vault, Entra ID and Managed Identities, Private Endpoints, Bicep, Azure DevOps Pipelines.

**Implied repo layout** (from section 6 of the spec): `agents/`, `graph/`, `rag/`, `evals/`, `observability/`, `infra/llm/`, `infra/queue/`, `infra/bicep/`, `azure-pipelines.yml`, `Dockerfile(s)`, plus a FastAPI app and MCP servers.

### 0.2 Existing loan work

`SOLUTION.md` already covers the assignment write-up (lifecycle map, 8-agent ecosystem, target architecture, before vs. after, 8-week POC, demo script). `prototype/` is a standard-library Python app with 7 working agents, a case state machine with human gates (segregation of duties, delegated authority, override reasons), BM25 RAG over a clause-ID policy, PII tokenisation, a hash-chained audit log, and two sample cases (APP-2026-0142 flagged, APP-2026-0157 clean) with 9 tests.

**The core idea stays:** the model reads and writes, code computes and applies policy, people decide. The rebuild changes implementations and packaging, not the agent design, the policy logic, or the controls.

---

## 1. Decisions I'm proposing (please confirm or change)

| # | Decision | My default | Why |
|---|---|---|---|
| D1 | Where the code lives | New folder `/mnt/project-files/loan-lifecycle/loanpilot/`, existing `prototype/` left untouched as the v1 reference | Keeps a working fallback demo for the interview |
| D2 | LLM provider | Azure OpenAI GPT-4o (decisions and drafting) plus GPT-4o mini (extraction, classification), matching ClaimPilot. Behind one `LLMClient` interface that also keeps the offline mock and a Claude option (Claude is available through Azure AI Foundry) | Same story as ClaimPilot; the offline mock means the demo still runs with no Azure subscription or network |
| D3 | Must it run without Azure? | Yes. Two profiles: `local` (mock LLM, in-memory or SQLite stand-ins, docker-compose emulators) and `azure` (real services). Same code, swapped by config | The interview room may have no network; Azure costs stay near zero until needed |
| D4 | Actually deploy to Azure? | Write the Bicep and pipeline, deploy once to a personal subscription for screenshots if you want, then tear down | Deployment is optional; the IaC is what shows design maturity |
| D5 | Spec document | Write `docs/LoanPilot_Project_Spec.md` in exactly ClaimPilot's 8-section format, plus a short `docs/LoanPilot_Main_Spec.md` covering the contracts, graph and API (the part ClaimPilot's spec refers to but doesn't include) | Gives you a matching pair to talk through |
| D6 | UI | A minimal reviewer workbench (FastAPI plus HTMX or a small Streamlit page) for the human gates. Optional, built last | The gates are the strongest demo moment; a CLI fallback stays |

---

## 2. Component mapping: loan prototype to Azure

| Loan component (today) | Azure primary (LoanPilot) | Local stand-in | Notes |
|---|---|---|---|
| `llm.py` MockLLM / ClaudeLLM | Azure OpenAI GPT-4o + GPT-4o mini, model router, structured outputs, Entra auth | MockLLM (kept) | Router: mini for extraction/classification, 4o for risk narrative, rationale, memo |
| Document ingestion (`.txt` docs) | Blob Storage + Azure AI Document Intelligence (prebuilt layout + custom model for financials) | Plain-text loader with line numbers (kept) | Citations become `document:page:line` from DI layout output; add PDF versions of the sample docs |
| `knowledge.py` BM25 over policy | Azure AI Search (vector + hybrid + semantic ranker), `text-embedding-3-large`, clause-level chunks with IDs, effective dates, versions | BM25 (kept) | Policy citations still return the exact clause ID and text |
| `orchestrator.py` state machine | LangGraph `StateGraph` on Container Apps worker | LangGraph in-process with `MemorySaver` | Human gates become LangGraph `interrupt()` nodes; resume via API |
| Case state | Cosmos DB LangGraph checkpointer | SQLite checkpointer | A case can wait days for an approver |
| Async intake | Service Bus queue `loan-applications` + DLQ, KEDA scaler | In-process queue | Event Grid on Blob upload can trigger intake |
| `security.py` PII vault | Azure AI Language PII detection + token vault in Key Vault-protected store | Regex vault (kept) | Masking still happens before any model call |
| Screening watchlist JSON | MCP server `screening` on Container Apps | Same MCP server, local | Stand-in for sanctions/PEP/adverse media API |
| Other system tools | MCP servers: `los` (application record), `bureau`, `collateral-registry`, `core-banking` | Local MCP servers over JSON fixtures | Typed tools, scoped Managed Identity per server |
| `audit.py` hash chain | Azure SQL append-only table (hash chained) + immutable Blob (WORM) export | JSONL (kept) | Tamper demo still works |
| `audit.py` Tracer | OpenTelemetry → Application Insights, AI Foundry tracing | OTel console exporter | Spans per agent node with tokens and cost |
| Guardrails | AI Content Safety: Prompt Shields on documents, groundedness detection on narratives | Local schema validation + citation checker | Documents treated as data; prompt injection defence is a demo point |
| Tests | pytest unit + golden-set evals in AI Foundry Evaluation as a pipeline gate | pytest + local eval runner | Custom evaluators: extraction accuracy, citation correctness, exception recall |
| Secrets / identity | Key Vault, Entra ID, Managed Identities, Private Endpoints | `.env` | No keys in code |
| CI/CD | Azure DevOps Pipelines + ACR + Container Apps revisions (canary) | `make test` | Option: GitHub Actions with OIDC |
| IaC | Bicep in `infra/bicep/` | docker-compose | |
| Dashboard | Power BI or Azure Workbook over audit/metrics | Static HTML report | Cycle time, exceptions found at intake, cost per case |

---

## 3. Target repo layout

```
loanpilot/
├── docs/
│   ├── LoanPilot_Project_Spec.md      # Azure deployment spec, same 8 sections as ClaimPilot
│   └── LoanPilot_Main_Spec.md         # contracts, graph topology, API, agent design
├── app/
│   ├── api/                           # FastAPI: POST /applications, GET /cases/{id}, POST /cases/{id}/decisions
│   ├── contracts/                     # Pydantic models (Evidence, ExtractedField, Finding, PolicyCheck, Condition, CaseState, HumanAction)
│   ├── agents/                        # intake, document_intelligence, completeness, due_diligence, policy, risk, approval, disbursement
│   ├── graph/                         # LangGraph StateGraph, nodes, interrupts, checkpointer factory
│   ├── controls/                      # SoD, delegation of authority, override rules (pure code, unit tested)
│   ├── rules/                         # ratios, policy thresholds, scorecard (deterministic, no LLM)
│   ├── rag/                           # chunker, embeddings, AI Search / BM25 retrievers
│   ├── audit/                         # hash-chained audit writer + verifier (SQL / JSONL)
│   └── reporting/                     # decision summary, decision record, CP tracker
├── infra/
│   ├── llm/                           # LLMClient interface, AzureOpenAI, Mock, Claude; model router; Content Safety wrapper
│   ├── queue/                         # Service Bus publisher/consumer, local queue
│   ├── docintel/                      # Document Intelligence client, text loader fallback
│   ├── pii/                           # AI Language PII + local vault
│   ├── bicep/                         # main.bicep + modules (aoai, search, aca, servicebus, cosmos, sql, kv, storage, monitor)
│   └── settings.py                    # profile switch: local | azure
├── mcp_servers/                       # screening, los, bureau, collateral_registry, core_banking
├── observability/                     # OpenTelemetry setup → App Insights / console
├── evals/                             # golden set, custom evaluators, Foundry eval job, local runner
├── data/                              # policy, sample applications (txt + pdf), fixtures (ported from prototype/data)
├── ui/                                # reviewer workbench (optional)
├── tests/                             # pytest: controls, rules, graph paths, audit chain, API
├── docker-compose.yml                 # local profile: api, worker, mcp servers, azurite, redis
├── Dockerfile.api / Dockerfile.worker
├── azure-pipelines.yml                # lint → mypy → tests → build → ACR → eval gate → deploy (canary)
├── pyproject.toml
└── README.md
```

---

## 4. LangGraph topology

```
START
  → intake (checklist)
  → document_intelligence (DI extract, PII mask, citations)
  → completeness ──(missing items)──▶ draft_rm_request ──▶ interrupt: rm_resubmission (optional loop)
  → [parallel] due_diligence ‖ policy_eligibility
  → risk (scorecard + narrative)
  → approval_workflow (recommendation, conditions, route by DoA)
  → edd_required? ──yes──▶ interrupt: compliance_gate ──▶ validate (SoD) ──┐
                                                                          ▼
  → interrupt: credit_gate ──▶ validate (SoD, authority, override reason) ─┘ retry on violation
  → disbursement_conditions (CP tracker, readiness)
  → report (summary, decision record, audit head)
END
```

Every node writes an audit entry (actor, inputs hash, outputs, clause IDs, model and prompt version). Invalid human actions are recorded and the interrupt is re-raised, so the existing "blocked approval" demo carries over unchanged.

---

## 5. Step by step build plan

Each phase ends with something runnable and a test or eval that proves it. Phases 1 to 5 run fully offline; Azure arrives in phase 6.

### Phase 1: Spec and skeleton
1. Write `docs/LoanPilot_Main_Spec.md`: contracts, graph, API endpoints, agent cards (purpose, inputs, tools, outputs, autonomy level, "never allowed to"), lifted from `SOLUTION.md` section 2.
2. Write `docs/LoanPilot_Project_Spec.md` in ClaimPilot's 8 sections, using the table in section 2 of this plan.
3. Create the repo skeleton, `pyproject.toml` (FastAPI, Pydantic v2, LangGraph, pytest, ruff, mypy), `settings.py` with `local` and `azure` profiles.
**Exit:** `pytest` runs (empty), `ruff` and `mypy` pass.

### Phase 2: Contracts, rules and controls (no LLM)
4. Port `models.py` dataclasses to Pydantic contracts.
5. Move ratio maths, the 14 policy checks and the scorecard into `app/rules/`; move SoD, DoA and override validation into `app/controls/`.
6. Port the 9 existing tests to pytest and add clause-level tests.
**Exit:** the same policy results as v1 on both sample cases, asserted in tests.

### Phase 3: LLM, RAG and document layer (local profile)
7. Build `infra/llm/` with the `LLMClient` interface, MockLLM port, model router, and structured-output schemas per document type.
8. Build `app/rag/` with the BM25 retriever behind a `Retriever` interface.
9. Build `infra/docintel/` text loader and `infra/pii/` local vault behind interfaces.
**Exit:** 33 cited fields extracted on APP-2026-0142, identical to v1 output.

### Phase 4: LangGraph orchestration and human gates
10. Port each agent to a LangGraph node; build the graph from section 4 with a SQLite checkpointer.
11. Implement compliance and credit gates as `interrupt()` with validation and retry; port scripted approvers from `demo_approvals.json`.
12. Port the hash-chained audit log and the tamper demo; port reporting.
**Exit:** both cases produce the same decision, conditions and blocked attempts as v1; a case can be paused, the process killed, and resumed from the checkpoint.

### Phase 5: API, MCP tools, queue, local stack
13. FastAPI endpoints: submit application, get case, list pending gates, post a human decision, verify audit chain.
14. MCP servers for screening, LOS, bureau, collateral registry, core banking over JSON fixtures; agents call them as tools with an allowlist per agent.
15. Worker consuming a local queue; `docker-compose.yml` with API, worker, MCP servers, Azurite, Redis.
16. Local eval runner over a golden set (start with the 2 cases plus 6 to 8 synthetic variants: injected prompt text in a document, missing KYC, high LTV, clean fast path).
**Exit:** `docker compose up` then a curl walkthrough reproduces the demo end to end.

### Phase 6: Azure wiring
17. Bicep modules: AOAI (gpt-4o, gpt-4o-mini, text-embedding-3-large), AI Search, Document Intelligence, Storage, Service Bus, Cosmos DB, Azure SQL, Key Vault, Container Apps environment, App Insights, Content Safety, Language. Managed Identities and RBAC assignments.
18. Azure implementations behind the existing interfaces: AzureOpenAI client with Entra auth and Content Safety, AI Search retriever (index clause chunks, hybrid + semantic ranker), Document Intelligence (PDF samples), Language PII, Service Bus, Cosmos checkpointer, SQL audit writer, OTel to App Insights.
19. Smoke test: one grounded policy answer with citation, one DI extraction from PDF, one full case on Azure.
**Exit:** the same case runs in `azure` profile with identical decisions to `local`.

### Phase 7: Evaluation, CI/CD, observability
20. Foundry Evaluation job: groundedness on narratives, plus custom evaluators for field accuracy, citation correctness, exception recall, and "no decision without an authorised human".
21. `azure-pipelines.yml`: ruff → mypy → pytest → build → ACR → eval gate (fail on regression) → deploy Container Apps revision at 10% then 100%.
22. App Insights alerts (escalation rate, p95 latency, cost per case, errors) and a Workbook or Power BI page.
**Exit:** pipeline green; a deliberately broken prompt fails the eval gate.

### Phase 8: Workbench, docs and demo
23. Reviewer workbench page: case view with each value next to its citation, gate actions with SoD/authority feedback.
24. README, architecture diagram, updated demo script mapped to the existing 6-step script, interview talking points in ClaimPilot's style (why Azure OpenAI, how you orchestrate, cost, evals, security, scaling to N loans a day).
25. Update `SOLUTION.md` section 4 so the target architecture names the Azure services, and add a pointer to LoanPilot.
**Exit:** a 5-minute demo runs offline and, optionally, on Azure.

---

## 6. Cost and footprint (if deployed)

GPT-4o mini for everything except risk narrative and rationale; AI Search Basic tier; Container Apps scale-to-zero; Cosmos serverless; Azure SQL serverless with auto-pause; DI and Foundry Evaluation pay per use; a Cost Management budget alert. Tear down with one `az group delete` after screenshots.

## 7. Risks

| Risk | Mitigation |
|---|---|
| ClaimPilot's "main spec" isn't in the folder, so its contracts and API shape are inferred | I'll mirror the deployment spec and section 6 layout; if you have the main spec elsewhere, share it and I'll align to it |
| Azure quotas or model availability in your region | Local profile is complete on its own; Azure is additive |
| LangGraph port changes behaviour | v1 outputs become regression fixtures in phase 2 to 4 |
| Scope too large for interview timing | Phases 1 to 5 are a complete, demoable result; 6 to 8 can be cut to IaC plus spec only |

## 8. What I need from you

1. Approve or change decisions D1 to D6 in section 1.
2. Tell me if you have ClaimPilot's main spec (contracts, graph, API) somewhere else.
3. Tell me whether you want a real Azure deployment (needs your subscription) or IaC and spec only.
4. Your interview date, so I can cut phases if needed.
