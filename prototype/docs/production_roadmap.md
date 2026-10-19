# 8-Week Production Readiness Roadmap
## Agentic Loan Lifecycle Management

**Start date:** 2026-10-26 · **Target go-live:** 2026-12-21

---

## Realigned Plan — Current State vs Remaining Work

| Week | Theme | Original Deliverable | ✅ Built | Remaining to Production |
|------|-------|---------------------|----------|------------------------|
| **1** | Foundation & DevOps | Discovery, lifecycle map, policy corpus, evaluation dataset, success criteria | 8-agent pipeline · Hybrid RAG · 3-gate HITL · Docker · GitHub Actions · Cloud Run deployed · Qdrant Cloud live | `/health` readiness probe · fix bare `except` clauses |
| **2** | Auth & Identity | Architecture, data model, security design, agent definitions, UX wireframes | Architecture finalised · all agents defined · Web UI live · SoD enforced | OAuth2/OIDC login · JWT cookies · remove `demo123` · backend RBAC per endpoint |
| **3** | Persistence | Intake + Document Intelligence Agent: OCR, extraction, validation, missing-doc detection | IntakeAgent + DocumentIntelligenceAgent complete · 35+ fields · avg_extraction_confidence | PostgreSQL schema · Redis session store · no data lost on container restart |
| **4** | Durable Workflow | Policy & Eligibility Agent: RAG corpus, retrieval, rule evaluation, citations | PolicyEligibilityAgent · 13 clauses · BM25 40% + Qdrant 60% · citations verified | Temporal/Step Functions · cases survive crash · approval timeout escalation |
| **5** | Security Hardening | Due-Diligence + Risk Agent: watchlist checks, financial ratios, risk narrative | DueDiligenceAgent + RiskAgent · 8-factor scorecard · PII vault · prompt injection screening | Vault/Secret Manager for all keys · AES-256 field encryption · file upload scanning |
| **6** | Observability | Approval/Workflow Agent: routing, HITL console, audit trail, decision summary | ApprovalWorkflowAgent · 3-tier routing · 3-gate HITL console · SHA-256 audit trail · case report UI | structlog → ELK · OpenTelemetry traces · Prometheus + Grafana · 5 alert rules |
| **7** | Compliance & Governance | End-to-end testing, evaluation, accuracy tuning, dashboard, security review | 26 unit + integration tests · 39-case golden set · audit chain verification · policy library UI | WORM audit log · 7-year activity log · compliance-pack export · SR 11-7 model card |
| **8** | UAT & Go-Live | UAT, demo, business-case validation, production roadmap | Demo live on GCP Cloud Run · Qdrant Cloud hybrid RAG · GitHub Actions CI/CD | Load test (Locust) · OWASP ZAP pen test · chaos engineering · runbooks · client sign-off |

---

## Summary

---

## Week 1 — DevOps Foundation
**Goal:** Reproducible builds, automated tests on every commit, health checks.

### Tasks

**1.1 Containerise the application**
- Write `Dockerfile` (Python 3.11 slim, non-root user, multi-stage build)
- Write `docker-compose.yml` with services: `api`, `qdrant`, `redis`, `postgres`
- Replace `start_web.bat` with `docker compose up`
- Test: `docker build` succeeds, all 20+ existing tests pass inside the container

**1.2 CI/CD pipeline (GitHub Actions)**
- Workflow triggers on every PR and merge to `main`
- Steps: lint (ruff) → unit tests → integration tests → docker build
- Fail-fast on any test failure; block merge if red
- Add `.github/workflows/ci.yml`

**1.3 Health & readiness endpoints**
- `GET /health` — returns `{"status":"ok","version":"...","qdrant":"ok","db":"ok"}`
- `GET /ready` — returns 200 only when KB is loaded and DB is reachable
- Used by Kubernetes liveness and readiness probes

**1.4 Environment configuration**
- Replace all hardcoded values (`AS_OF`, `BASE_DIR`, port) with env vars
- Add `config.py` with a Pydantic `Settings` model (reads `.env`)
- Document every required env var in `.env.example`

**1.5 Fix bare except clauses**
- Replace 8+ `except Exception: pass` blocks in `web/app.py` with proper logging
- Add `import logging` and a module-level logger to every file

**Deliverables:** `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `config.py`, `GET /health`

---

## Week 2 — Authentication & RBAC
**Goal:** Every API call is authenticated; role gates are enforced by the backend, not just the frontend.

### Tasks

**2.1 Identity provider integration**
- Integrate OAuth2/OIDC (Azure AD, Keycloak, or Auth0)
- Issue short-lived JWT access tokens (15 min) + refresh tokens (8 h)
- Add `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`
- Remove hardcoded `demo123` password from `web/app.py`

**2.2 Backend RBAC middleware**
- Define roles: `rm`, `senior_analyst`, `compliance_officer`, `credit_manager`, `credit_committee`, `board`, `admin`
- Add FastAPI dependency `require_role(*roles)` — returns 403 if caller lacks role
- Protect every `/api/*` endpoint with `require_role`
- Approver gate validation in `orchestrator.validate_human_action` cross-checks JWT role (not just the form field)

**2.3 Per-case access control**
- RMs can only see their own cases (filter by `rm_id` from JWT)
- Approvers see only cases pending their role
- Admins see all cases
- Add `case_id` → `authorized_roles` mapping in the session store

**2.4 Frontend updates**
- Replace the username dropdown with a real login page
- Store JWT in `httpOnly` cookie (not localStorage — prevents XSS theft)
- Remove client-side role logic — trust backend responses instead

**2.5 API key support for system integrations**
- `POST /admin/api-keys` — generate scoped API key for downstream systems (e.g., core banking)
- Keys stored hashed in DB; never returned after creation
- Rate-limited to 60 req/min per key

**Deliverables:** Auth middleware, RBAC dependency, login/logout endpoints, JWT cookie flow

---

## Week 3 — Persistence Layer
**Goal:** Zero data loss on server restart; decision records are queryable.

### Tasks

**3.1 Database schema (PostgreSQL)**

```
cases            (case_id, app_id, rm_id, status, created_at, updated_at)
agents_steps     (step_id, case_id, agent_name, result_json, started_at, completed_at)
gate_events      (event_id, case_id, gate_type, role, decision, rationale, actor_id, decided_at)
decision_records (record_id, case_id, final_decision, summary_md, record_json, created_at)
audit_entries    (entry_id, case_id, seq, event_type, payload_json, sha256, prev_sha256)
extracted_fields (field_id, case_id, field_name, value, confidence, citation, created_at)
```

- Add Alembic for schema migrations (version-controlled, never manual `ALTER TABLE`)
- Connection pool via `asyncpg` + SQLAlchemy async

**3.2 Migrate session store to Redis**
- Replace `_sessions: dict` in `app.py` with Redis hash per `case_id`
- TTL of 30 days on each key
- On server restart: sessions reload from Redis, no pending approvals lost
- Use `redis-py` async client

**3.3 Migrate file outputs to database**
- `decision_summary.md`, `decision_record.json`, `conditions_tracker.json` → write to `decision_records` table
- `audit_log.jsonl` entries → write to `audit_entries` table (file remains as backup)
- `extracted_fields.json` → write to `extracted_fields` table
- Keep file writing as secondary output for CLI compatibility

**3.4 Case query API**
- `GET /api/cases?status=pending&role=senior_analyst` — paginated list (cursor-based)
- `GET /api/cases/{case_id}/history` — full agent step + gate event timeline
- `GET /api/cases/{case_id}/fields` — extracted fields with confidence + citations
- These replace the current file-based output reads

**3.5 Data migration utility**
- Script `tools/migrate_file_cases.py` to bulk-import existing `output/APP-*/` into DB
- Idempotent (safe to run twice)

**Deliverables:** PostgreSQL schema + Alembic, Redis session store, case query API, migration script

---

## Week 4 — Durable Workflow & State Management
**Goal:** Pipeline survives server crash; approvals never time out silently; no race conditions.

### Tasks

**4.1 Durable task engine**
- Integrate **Temporal** (self-hosted) or **AWS Step Functions** (managed)
- Wrap `orchestrator.run_case()` as a Temporal Workflow; each agent becomes an Activity
- On server restart, Temporal replays the workflow from the last checkpoint — no orphaned cases
- Human gates become `workflow.wait_for_signal()` — the workflow sleeps until an approval arrives

**4.2 Approval timeout enforcement**
- Current: 30-min timeout exists in `app.py` but is never enforced (no background job)
- With Temporal: set `start_to_close_timeout=timedelta(days=3)` on gate activities
- On timeout: escalate to next authority tier; notify RM by email; log in audit

**4.3 Concurrency locking**
- Add optimistic locking to `gate_events` table: `version` column + `WHERE version = :expected` on insert
- Return 409 Conflict if two approvers submit simultaneously; frontend retries

**4.4 Idempotency on pipeline start**
- `POST /api/run` checks DB for existing case with same `app_id` — returns existing case ID if already running
- Prevents duplicate pipeline runs from double-clicks or retries

**4.5 Dead-letter queue**
- Cases that fail after 3 retries go to a `cases_failed` table
- Alert fires to on-call; case can be restarted manually with `POST /api/cases/{id}/restart`

**Deliverables:** Temporal workflow wrapper, approval signals, timeout escalation, optimistic locking

---

## Week 5 — Security Hardening
**Goal:** No secrets on disk; PII encrypted at rest; HTTPS enforced; inputs validated.

### Tasks

**5.1 Secrets management**
- Migrate all API keys from `.env.local` to **HashiCorp Vault** (or AWS Secrets Manager / Azure Key Vault)
- App fetches secrets at startup via Vault Agent; secrets never written to disk
- Rotate OpenRouter API key every 90 days; rotation is automated via Vault lease renewal
- Each service (API, worker) gets its own Vault role with least-privilege policy

**5.2 Encryption at rest**
- Encrypt `decision_records.record_json`, `extracted_fields.value` using AES-256-GCM (envelope encryption)
- Master key in Vault; per-record data encryption keys (DEKs) rotated per case
- PII Vault (`security.py`) persisted to DB encrypted; token → real-value map survives restarts
- Encrypt `audit_log.jsonl` backup files at rest (S3 SSE-KMS or equivalent)

**5.3 HTTPS enforcement**
- Add `nginx` reverse proxy to `docker-compose.yml` with TLS termination
- `app.py` adds HSTS header (`Strict-Transport-Security: max-age=31536000`)
- Redirect all HTTP → HTTPS (301)
- Certificate via Let's Encrypt (Certbot) or internal PKI

**5.4 Input validation**
- Add document upload endpoint `POST /api/cases/{id}/documents` (currently docs are sent as text)
- Validate: file type whitelist (PDF, DOCX, PNG, JPEG), max size 10 MB, MIME sniff check
- Scan uploaded files with ClamAV before processing
- Reject filenames with path traversal patterns (extend existing `app.py:89–97` check)

**5.5 Content Security Policy & headers**
- Add `SecurityHeadersMiddleware` to FastAPI:
  - `Content-Security-Policy: default-src 'self'; script-src 'self' cdn.tailwindcss.com`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
- Run OWASP ZAP scan; fix all HIGH/MEDIUM findings

**Deliverables:** Vault integration, field-level encryption, nginx+TLS, file upload endpoint, security headers

---

## Week 6 — Observability & Monitoring
**Goal:** Full visibility into what the system is doing; alerts fire before users notice problems.

### Tasks

**6.1 Structured logging**
- Replace all `print()` with `structlog` (JSON format)
- Every log line includes: `case_id`, `agent`, `trace_id`, `user_id`, `duration_ms`, `level`
- Ship logs to **Elasticsearch** via Filebeat → Kibana dashboards
- Log retention: 90 days hot, 1 year cold (S3/Azure Blob)

**6.2 OpenTelemetry tracing**
- Instrument FastAPI with `opentelemetry-instrumentation-fastapi`
- Each agent step creates a child span under the case trace
- LLM calls include token count + cost as span attributes
- Export to **Jaeger** (self-hosted) or **Datadog APM**
- `trace_id` propagated in HTTP headers for cross-service tracing

**6.3 Prometheus metrics**
- Add `/metrics` endpoint (Prometheus format)
- Key metrics:
  - `loan_pipeline_duration_seconds{agent}` — histogram
  - `loan_gate_decision_total{gate,decision}` — counter
  - `loan_llm_tokens_total{provider,model}` — counter
  - `loan_llm_cost_usd_total{provider}` — counter
  - `loan_cases_pending{gate}` — gauge
  - `loan_cases_total{status}` — counter

**6.4 Grafana dashboards**
- Dashboard 1: **Operations** — active cases, pipeline throughput, error rate, p95 latency
- Dashboard 2: **LLM Cost** — daily spend by provider/model, cost per case, budget burn rate
- Dashboard 3: **HITL Gates** — time-to-decision per gate, approval rates, override rates
- Dashboard 4: **Compliance** — PEP hits, blocked actions, audit chain verification status

**6.5 Alerting rules**
- `PipelineErrorRate > 5%` for 5 min → PagerDuty P2
- `GatePendingCount > 10` for 30 min → Slack #loan-ops
- `LLMCostDaily > $50` → Slack #finops
- `AuditChainBroken` (any case) → PagerDuty P1
- `ApprovalTimeoutExpired` (any case) → Slack #loan-ops + RM email

**Deliverables:** structlog, OpenTelemetry, `/metrics`, 4 Grafana dashboards, 5 alert rules

---

## Week 7 — Compliance & Governance
**Goal:** Meet bank-grade regulatory requirements; model risk governance documented.

### Tasks

**7.1 Immutable audit log**
- Move audit entries to a PostgreSQL `UNLOGGED` table with `WORM`-style constraints:
  - No UPDATE, no DELETE (enforce via row-level trigger)
  - INSERT only by the `audit_writer` DB role
- File backup: `audit_log.jsonl` streamed to S3 with Object Lock (Compliance mode, 7-year retention)
- Verify hash chain daily via scheduled job; alert on any break

**7.2 Activity log (access audit)**
- Log every API call: `actor_id`, `role`, `endpoint`, `case_id`, `ip_address`, `user_agent`, `timestamp`, `response_code`
- Separate `activity_log` table — never commingled with case audit log
- Supports regulator query: "show all actions taken by user X on case Y between date A and B"
- Retention: 7 years (SOX / MAS TRM requirement)

**7.3 Compliance evidence export**
- `GET /admin/cases/{id}/compliance-pack` — ZIP containing:
  - `decision_record.json` (signed with server private key)
  - `audit_log.jsonl` (with hash chain verification proof)
  - `extracted_fields.json` (with citations)
  - `gate_decisions.json` (all HITL approvals with actor, role, timestamp, rationale)
  - `policy_clauses_checked.json` (which RAG clauses were retrieved and their scores)
- Used for regulator inspection or internal audit

**7.4 Model risk governance (SR 11-7 / MAS MG-14)**
- Write `docs/model_risk/model_card.md`:
  - Model purpose, inputs, outputs, performance metrics
  - Known limitations (MockLLM vs real LLM divergence, RAG recall rate)
  - Validation results (39-case golden set pass rates)
  - Monitoring plan (drift detection, quarterly revalidation)
- Write `docs/model_risk/change_log.md` — version history of policy thresholds and agent logic
- Identify Model Owner, Model Validator, and Model Risk Officer roles

**7.5 Data retention & deletion**
- Policy: case data retained 7 years after decision date
- Implement `POST /admin/cases/{id}/purge` — hard-delete PII fields; retain decision record skeleton
- GDPR/PDPA right-to-erasure: PII fields nulled, audit log entries kept (only metadata)
- Scheduled job: auto-purge cases older than 7 years

**Deliverables:** WORM audit log, activity log, compliance-pack endpoint, model card, data retention policy

---

## Week 8 — Testing & Go-Live
**Goal:** System handles production load; security validated; team knows how to operate it.

### Tasks

**8.1 Performance & load testing**
- Tool: **Locust** or **k6`
- Scenario A: 50 concurrent users submitting applications — target p95 < 30s per pipeline
- Scenario B: 200 concurrent users viewing case status — target p95 < 500ms
- Scenario C: 10 simultaneous HITL approvals — no race conditions, no lost votes
- Baseline: document throughput, LLM cost per case, DB query p95

**8.2 Chaos engineering**
- Kill Qdrant mid-pipeline → verify BM25 fallback activates, case resumes
- Kill Redis mid-approval → verify session recovers from DB
- Simulate OpenRouter timeout → verify retry + exponential backoff + circuit breaker
- Kill Temporal worker mid-workflow → verify workflow replays correctly from checkpoint
- Disconnect DB → verify health endpoint returns 503 and no silent data loss

**8.3 Security penetration test**
- Run **OWASP ZAP** full active scan against staging environment
- Manual test: IDOR (can RM A see RM B's case by guessing case ID?)
- Manual test: privilege escalation (can `rm` role call `/api/approve`?)
- Manual test: prompt injection via application fields (borrower name contains jailbreak)
- Fix all HIGH findings before go-live; track MEDIUM in backlog

**8.4 Runbooks & documentation**
- `docs/ops/runbook_approval_timeout.md` — what to do when a case times out
- `docs/ops/runbook_audit_chain_break.md` — incident response for tampered audit
- `docs/ops/runbook_llm_outage.md` — how to switch to MockLLM and back
- `docs/ops/runbook_scaling.md` — how to add more workers
- `docs/api_contract.md` — OpenAPI spec exported from FastAPI (`/openapi.json`)
- Update architecture diagram to reflect all production components

**8.5 Staging → Production promotion**
- Deploy to staging (identical to production); run full regression suite
- Smoke test checklist:
  - [ ] New application submits via Web UI
  - [ ] Pipeline runs end-to-end with real LLM
  - [ ] All 3 HITL gates fire and resolve correctly
  - [ ] Audit chain verifies after full run
  - [ ] Compliance pack downloads and validates
  - [ ] Metrics visible in Grafana
  - [ ] Alert fires when approval times out
- Sign-off required from: Tech Lead, Model Risk Officer, Head of Compliance, CISO

**Deliverables:** Load test report, pen test findings + fixes, 4 runbooks, API contract, go-live sign-off

---

## Dependency Map

```
Week 1 (DevOps) ──► Week 2 (Auth) ──► Week 3 (Persistence) ──► Week 4 (Workflow)
                                                │
                                                ▼
Week 5 (Security) ◄──────────────────── Week 3 (Persistence)
       │
       ▼
Week 6 (Observability) ──► Week 7 (Compliance) ──► Week 8 (Go-Live)
```

Weeks 1–4 are strictly sequential. Weeks 5 and 6 can run in parallel after Week 3.

---

## Team Sizing

| Role | Weeks Active | Responsibility |
|------|-------------|----------------|
| Backend Engineer (×2) | All 8 weeks | API, persistence, workflow |
| DevOps / Platform Engineer | Weeks 1, 4, 6, 8 | Docker, CI/CD, Temporal, Grafana |
| Security Engineer | Weeks 2, 5, 8 | Auth, encryption, pen test |
| Data Engineer | Week 3 | Schema design, migrations, query API |
| Compliance / Risk Analyst | Week 7 | Model card, SR 11-7, activity log spec |
| QA Engineer | Week 8 | Load test, chaos, regression |

---

## What Is NOT Changing

The following components are **production-grade today** and require no rework:

- **8-agent pipeline logic** — sound architecture, independently testable
- **Hybrid RAG** — BM25 + Qdrant with graceful fallback
- **Segregation of Duties enforcement** — orchestrator blocks wrong-role approvals
- **PII masking** — identifiers removed before any LLM call
- **Hash-chained audit trail** — tamper detection works
- **39-case golden test set** — regression safety net
- **Prompt injection screening** — 14-rule quarantine filter

---

## Cost Estimate (Infrastructure, Monthly at Go-Live)

| Component | Service | Est. Cost/Month |
|-----------|---------|----------------|
| App server | 2× 4-vCPU VM (active-standby) | $200 |
| PostgreSQL | Managed DB, 100 GB | $150 |
| Redis | Managed cache, 1 GB | $30 |
| Qdrant | 1× 4-vCPU VM | $80 |
| Temporal | Self-hosted on 2× 2-vCPU | $100 |
| Log storage | Elasticsearch + S3 (90 days hot) | $120 |
| OpenRouter | ~200 cases/month × $0.50/case | $100 |
| **Total** | | **~$780/month** |

Vault, Grafana, CI/CD assumed self-hosted or existing enterprise licence.
