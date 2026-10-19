# 8-Week Production Roadmap
## Agentic Loan Lifecycle — Scalable · Available · Secure

**Start:** 2026-10-26 · **Go-live:** 2026-12-21
**Based on:** [System Design](system_design.md) — 12 design principles, multi-region GCP, event-driven pipeline

---

## Master Plan

| Week | Theme | Design Principles | Exit Criteria |
|------|-------|-------------------|---------------|
| **1** | Foundation Hardening | Observability First | `/health` + `/ready` live · structured logs · CI green on every PR |
| **2** | Zero Trust Auth | Zero Trust · Single Responsibility | IAP login · JWT 15 min · RBAC on every endpoint · `Loanlifecycledemo@123` gone |
| **3** | Persistence & CQRS | CP over AP · CQRS · Idempotency | PostgreSQL HA · Redis HA · PgBouncer · no data lost on restart |
| **4** | Event-Driven Pipeline | Event-Driven · Bulkhead · Circuit Breaker · Saga | Pub/Sub topics live · 8 agent workers deployed · DLQ alerting |
| **5** | Security Hardening | Defence in Depth · Zero Trust | Cloud Armor · VPC SC · CMEK · Cloud DLP · Binary Authorization |
| **6** | Full Observability | Observability First · Fault Tolerance | Traces in Cloud Trace · Grafana 4 dashboards · 5 alert policies |
| **7** | HA · Compliance · Blue-Green | Immutability · HA · CAP | Multi-region active-active · WORM audit · SR 11-7 model card |
| **8** | Load Test & Go-Live | All 12 principles | 200 concurrent users pass · chaos pass · ZAP pass · SLO sign-off |

---

## Week 1 — Foundation Hardening
**Design principle:** Observability First — you cannot fix what you cannot see.

### 1.1 Health & readiness probes
- `GET /health` — returns `{"status":"ok","db":"ok","redis":"ok","qdrant":"ok"}`
- `GET /ready` — returns 200 only when KB loaded + DB reachable (used by Cloud Run)
- Wire into Cloud Run `--liveness-probe` and `--startup-probe`

### 1.2 Structured logging
- Replace all `print()` with `structlog` (JSON output)
- Every log line carries: `case_id`, `agent`, `trace_id`, `user_id`, `duration_ms`, `level`
- Replace 8+ bare `except Exception: pass` with `logger.exception()`
- Logs automatically shipped to Cloud Logging from Cloud Run stdout

### 1.3 CI pipeline hardening
- Add `ruff` linter + `pytest` to GitHub Actions (currently only builds)
- Add step: `pytest prototype/tests/ -x` — fail PR if any test red
- Add step: `docker build` smoke test on every PR (not just main)
- Add Dependabot for `requirements.txt` updates

### 1.4 Config management
- Move all hardcoded values (`AS_OF`, `BASE_DIR`, ports) to `config.py` using Pydantic `Settings`
- Every env var documented in `env.example`
- Validate required vars at startup — fail fast with clear error if missing

**Deliverables:** `/health`, `/ready`, structured logs, CI on PRs, `config.py`

---

## Week 2 — Zero Trust Auth
**Design principle:** Zero Trust — every request verified; no implicit trust.

### 2.1 Identity Provider
- Enable **Identity-Aware Proxy (IAP)** on Cloud Run — Google-managed OAuth2
- Staff log in with their Google/company account — no password to manage
- Remove hardcoded `Loanlifecycledemo@123` from `web/app.py`
- Local dev: use `gcloud auth print-identity-token` to get a token

### 2.2 JWT middleware
- Validate IAP JWT on every API request (`x-goog-iap-jwt-assertion` header)
- Extract: `email`, `sub`, `hd` (hosted domain) — map to internal role
- Short-lived: 15-min expiry enforced; client refreshes silently
- Add `require_role(*roles)` FastAPI dependency — returns 403 if role missing

### 2.3 Backend RBAC
- Define roles: `rm`, `senior_analyst`, `compliance_officer`, `credit_manager`, `committee`, `board`, `admin`
- Protect every `/api/*` endpoint with correct role requirement
- Gate validation in `orchestrator.validate_human_action` cross-checks JWT role — not the form field
- SoD: same user cannot approve at two different gates (already built, now backed by JWT)

### 2.4 Workload Identity (service-to-service)
- Each Cloud Run service gets its own GCP service account
- Services call each other using short-lived tokens from Workload Identity Federation
- No JSON key files anywhere — key-less auth throughout
- Pipeline workers authenticate to Cloud SQL + Pub/Sub via Workload Identity

### 2.5 API keys for integrations
- `POST /admin/api-keys` — scoped key for core banking / reporting systems
- Keys stored hashed in DB; rate-limited 60 req/min
- Shown once at creation; never retrievable again

**Deliverables:** IAP login, JWT middleware, RBAC on all endpoints, Workload Identity, API key management

---

## Week 3 — Persistence & CQRS
**Design principle:** CP over AP (consistency) · CQRS (read/write separation) · Idempotency.

### 3.1 PostgreSQL HA (Cloud SQL)
Schema — 6 core tables:
```
cases            (case_id, app_id, rm_id, status, version, created_at)
agent_steps      (step_id, case_id, agent, result_json, started_at, completed_at)
gate_events      (event_id, case_id, gate, role, decision, actor_id, rationale, decided_at)
decision_records (record_id, case_id, final, summary_md, record_json, created_at)
audit_entries    (entry_id, case_id, seq, event, payload, sha256, prev_sha256)
activity_log     (log_id, actor_id, role, endpoint, case_id, ip, status, ts)
```
- Cloud SQL HA: synchronous standby, automatic failover <30s
- Read replica in same region — all GET queries routed here
- Alembic migrations: version-controlled, backward-compatible, tested on DB clone

### 3.2 Redis HA (Cloud Memorystore)
- Replace `_sessions: dict` with Redis hash per `case_id` (TTL 30 days)
- Redis Streams for SSE — pipeline workers publish events, API streams to browser
- Rate limiting counters per user (LLM cost guard)
- Distributed locks for approval idempotency
- Failover: Cloud Memorystore HA mode — automatic replica promotion <30s

### 3.3 PgBouncer (connection pooling)
- Deploy PgBouncer as Cloud Run sidecar
- Transaction mode: 1000 client connections → 100 server connections
- Prevents Cloud SQL connection exhaustion under load

### 3.4 CQRS implementation
- **Write path**: `POST /api/run`, `POST /api/approve` → Cloud SQL primary
- **Read path**: `GET /api/cases`, `GET /api/cases/{id}/history` → read replica
- Cache layer: Redis caches active case status (TTL 30s, invalidated on state change)

### 3.5 Idempotency
- `POST /api/run` checks DB for existing case with same `app_id` — returns existing if found
- Gate approvals use `version` column + optimistic locking — 409 Conflict on duplicate submit
- All Pub/Sub messages carry `message_id` — workers deduplicate using Redis SET NX

**Deliverables:** PostgreSQL HA + Alembic, Redis HA, PgBouncer, CQRS routing, idempotency keys

---

## Week 4 — Event-Driven Pipeline
**Design principle:** Event-Driven · Bulkhead · Circuit Breaker · Saga.

### 4.1 Pub/Sub topic design
```
case.submitted       → IntakeWorker
agent.completed      → next agent worker (choreography)
gate.pending         → notification service + timeout timer
gate.resolved        → resume pipeline worker
case.finalised       → report generator
case.dlq             → dead-letter (alert ops, manual retry)
```

### 4.2 Agent workers (Cloud Run services)
Each agent becomes an independent Cloud Run service:
- `intake-worker`, `docint-worker`, `completeness-worker`, `duediligence-worker`
- `policy-worker`, `risk-worker`, `approval-worker`, `disbursement-worker`

Each worker:
1. Pulls one Pub/Sub message
2. Loads case from PostgreSQL
3. Runs agent logic (unchanged from current `agents.py`)
4. Writes result to `agent_steps` table
5. Publishes `agent.completed` event
6. Acks message

Scales to zero between runs — no idle cost.

### 4.3 Circuit Breaker (LLM)
```
States: CLOSED → OPEN → HALF-OPEN
CLOSED:    all calls go to OpenRouter
OPEN:      5 failures in 60s → switch to MockLLM, fire alert
HALF-OPEN: after 5 min → probe 1 real call → if OK, back to CLOSED
```
Implemented in `llm.py` using Redis counter for failure tracking (shared across instances).

### 4.4 Retry + Dead-Letter Queue
- Pub/Sub retry policy: 3 attempts with exponential backoff (2s, 4s, 8s)
- After 3 failures: message routed to `case.dlq`
- DLQ subscriber: writes to `cases_failed` table + fires PagerDuty P2 alert
- Manual retry: `POST /admin/cases/{id}/retry` — re-publishes from last checkpoint

### 4.5 Approval timeout
- On `gate.pending` event: Cloud Tasks creates a task delayed by 72h
- If task fires: escalate to next authority tier + notify RM + log in audit
- On `gate.resolved` event: cancel the Cloud Tasks task

**Deliverables:** 8 Pub/Sub topics · 8 agent workers deployed · circuit breaker · DLQ · approval timeout

---

## Week 5 — Security Hardening
**Design principle:** Defence in Depth — 7 security layers.

### 5.1 Cloud Armor (Layer 1 — Network)
- Enable on Global HTTPS Load Balancer
- Rules: OWASP CRS preconfigured rules, rate limit 100 req/s per IP, geo-block high-risk regions
- DDoS protection: L3/L4 always on, L7 adaptive protection enabled
- Log all blocked requests to Cloud Logging

### 5.2 VPC Service Controls (Layer 1 — Network)
- Define a perimeter around: Cloud Run, Cloud SQL, Memorystore, Secret Manager, Qdrant
- Block access from outside the perimeter — data cannot leave even via compromised credential
- Exceptions: OpenRouter API (egress allowlist)

### 5.3 Cloud KMS — CMEK (Layer 5 — Data)
- Customer-managed encryption keys for: Cloud SQL, Cloud Storage (audit backups), Pub/Sub
- Key rotation policy: 90 days automatic
- Key access logged in Cloud Audit Logs — every decrypt operation recorded

### 5.4 Cloud DLP — PII scanning (Layer 5 — Data)
- Scan uploaded documents before ingestion: detect SSN, passport, bank account patterns
- Redact detected PII from raw text before storing in `agent_steps`
- PII tokenisation (already built in `security.py`) remains the LLM-facing layer

### 5.5 Binary Authorization (Layer 2 — Identity)
- Only container images signed by the CI/CD pipeline's attestor can deploy to Cloud Run
- Unsigned images rejected at deploy time — prevents supply chain attack
- Attestor key stored in Cloud KMS

### 5.6 Field-level encryption (Layer 5 — Data)
- `decision_records.record_json` and `extracted_fields.value` encrypted with AES-256-GCM
- Envelope encryption: DEK per record, KEK in Cloud KMS
- PII vault token map persisted to encrypted DB column (survives restarts — fixes current bug)

**Deliverables:** Cloud Armor rules · VPC SC perimeter · CMEK on all stores · Cloud DLP · Binary Auth · field encryption

---

## Week 6 — Full Observability
**Design principle:** Observability First — logs + traces + metrics as one unified signal.

### 6.1 Distributed tracing (OpenTelemetry → Cloud Trace)
- Instrument FastAPI with `opentelemetry-instrumentation-fastapi`
- Each agent step creates a child span under the case trace
- Trace spans carry: `case_id`, `agent`, `llm_tokens`, `llm_cost_usd`, `qdrant_latency_ms`
- `trace_id` propagated across Pub/Sub messages (custom attribute)
- View full pipeline trace: single request from submit to decision in Cloud Trace

### 6.2 Metrics (Cloud Monitoring)
Key metrics exported:
```
loan_pipeline_duration_seconds{agent}     histogram
loan_gate_decision_total{gate, decision}  counter
loan_llm_tokens_total{provider, model}    counter
loan_llm_cost_usd_total{provider}         counter
loan_cases_pending{gate}                  gauge
loan_cases_total{status}                  counter
loan_dlq_depth                            gauge
```

### 6.3 Grafana dashboards (4)
- **Operations**: active cases, pipeline p95 latency, error rate, DLQ depth
- **LLM Cost**: daily spend, cost/case, budget burn rate, model distribution
- **HITL Gates**: time-to-decision per gate, approval/decline rates, override rates
- **Compliance**: PEP hits, blocked actions, audit chain status, SLO burn rate

### 6.4 Alert policies (5)
```
PipelineErrorRate > 5% for 5 min     → PagerDuty P2
DLQDepth > 0                          → PagerDuty P2
GatePendingCount > 10 for 30 min     → Slack #loan-ops
LLMCostDaily > $50                    → Slack #finops
AuditChainBroken (any)                → PagerDuty P1
```

### 6.5 SLO monitoring
- Define SLO windows in Cloud Monitoring (rolling 28-day)
- Error budget burn rate alerts at 2× and 5× baseline
- SLO report auto-generated weekly → emailed to stakeholders

**Deliverables:** OpenTelemetry traces · `/metrics` endpoint · 4 Grafana dashboards · 5 alert policies · SLO burn rate

---

## Week 7 — HA · Compliance · Blue-Green
**Design principle:** Immutability · High Availability · CAP-CP.

### 7.1 Multi-region active-active
- Deploy Cloud Run to `asia-south1` (primary) + `asia-southeast1` (secondary)
- Global HTTPS LB: anycast IP routes to nearest healthy region
- Failover: if primary returns 5xx for 30s → LB shifts 100% to secondary
- Cloud SQL: primary in asia-south1, async read replica in asia-southeast1
- Test: kill primary region → verify failover < 10s

### 7.2 Blue-Green deployment
- Cloud Run traffic splitting: `--traffic=LATEST=10` for canary, `=100` for full rollout
- Automated rollback trigger: if error rate > 1% on new revision → shift back to stable
- Database migrations run as pre-deploy Cloud Run Job (backward-compatible required)
- Runbook: rollback procedure documented + tested

### 7.3 WORM audit log (immutability)
- Audit entries: DB trigger prevents UPDATE/DELETE on `audit_entries` table
- File backup: Cloud Storage bucket with Object Lock enabled (Compliance mode, 7-year retention)
- Daily job: verify SHA-256 hash chain integrity; alert on any break
- Compliance export: `GET /admin/cases/{id}/compliance-pack` — ZIP with signed decision record + audit log

### 7.4 Activity log (7-year)
- Every API call logged: `actor_id`, `role`, `endpoint`, `case_id`, `ip`, `user_agent`, `ts`, `response_code`
- Separate table, separate DB role — immutable inserts only
- Retention: 7 years (Cloud Storage cold tier after 90 days)
- Supports regulator query: "all actions by user X on case Y between date A and B"

### 7.5 SR 11-7 Model Card
- `docs/model_risk/model_card.md`: purpose, inputs, outputs, performance, limitations
- `docs/model_risk/change_log.md`: version history of policy thresholds + agent logic
- Validation report: 39-case golden set results, BM25 vs hybrid RAG accuracy delta
- Sign-off: Model Owner, Model Validator, Model Risk Officer

**Deliverables:** Multi-region LB · blue-green rollback · WORM audit · activity log · compliance-pack · SR 11-7 model card

---

## Week 8 — Load Test & Go-Live
**Design principle:** All 12 — validated under load.

### 8.1 Load test (Locust)
```
Scenario A — 50 concurrent submissions
  Target: p95 < 200ms (submit), pipeline complete < 5 min
  Pass: 0 errors, 0 data loss

Scenario B — 200 concurrent status reads
  Target: p95 < 50ms
  Pass: Redis hit rate > 95%

Scenario C — 20 simultaneous approvals
  Target: no race conditions, no lost votes
  Pass: all gate_events have unique optimistic lock version
```

### 8.2 Chaos engineering
```
Kill Qdrant          → BM25 fallback activates, pipeline continues
Kill Redis           → session recovers from DB, SSE reconnects
Throttle OpenRouter  → circuit breaker opens, MockLLM activates, alert fires
Kill primary DB      → read replica promoted in <30s, pipeline resumes
Kill asia-south1     → LB routes to asia-southeast1 in <10s
Kill one agent worker → Pub/Sub retries, message re-routed to healthy instance
```

### 8.3 Security pen test (OWASP ZAP + manual)
- Full active scan against staging
- Manual: IDOR (can RM A see RM B's case?), privilege escalation, prompt injection via borrower name
- Binary Auth: attempt to deploy unsigned image — must be rejected
- VPC SC: attempt data exfiltration — must be blocked
- Fix all HIGH findings before go-live; MEDIUM in 30-day backlog

### 8.4 Runbooks
- `ops/runbook_approval_timeout.md` — case timed out at gate
- `ops/runbook_audit_chain_break.md` — tampered audit log
- `ops/runbook_llm_outage.md` — OpenRouter down, circuit open
- `ops/runbook_db_failover.md` — primary DB unavailable
- `ops/runbook_rollback.md` — bad deploy, revert to previous revision

### 8.5 Go-live checklist
- [ ] All 8 agent workers deployed and passing health checks
- [ ] Multi-region LB routing verified from both regions
- [ ] Alert policies firing correctly in staging
- [ ] Compliance pack downloads and hash-chain validates
- [ ] Load test: all 3 scenarios pass
- [ ] Chaos: all 6 scenarios recover within SLO
- [ ] Pen test: zero HIGH findings open
- [ ] Runbooks reviewed by on-call engineer
- [ ] SLO targets agreed and signed by: Tech Lead · Model Risk Officer · Compliance · CISO

**Deliverables:** Load test report · chaos results · pen test report + fixes · 5 runbooks · go-live sign-off

---

## Dependency Map
```
Week 1 (Foundation) ──► Week 2 (Auth) ──► Week 3 (Persistence) ──► Week 4 (Event-Driven)
                                                    │
                                                    ▼
                              Week 5 (Security) ◄──┘
                                    │
                                    ▼
                              Week 6 (Observability) ──► Week 7 (HA + Compliance) ──► Week 8 (Go-Live)
```
Weeks 5 and 6 can run in parallel after Week 3 is complete.

---

## Team & Roles

| Role | Weeks | Focus |
|------|-------|-------|
| Backend Engineer ×2 | All 8 | API, pipeline workers, CQRS, circuit breaker |
| Platform / DevOps | 1, 4, 7, 8 | Cloud Run, Pub/Sub, multi-region, blue-green |
| Security Engineer | 2, 5, 8 | IAP, Cloud Armor, VPC SC, KMS, pen test |
| Data Engineer | 3 | PostgreSQL schema, Alembic, PgBouncer, CQRS |
| Observability Engineer | 6 | OpenTelemetry, Grafana, alert policies |
| Compliance / Risk Analyst | 7 | WORM audit, activity log, SR 11-7 model card |
| QA Engineer | 8 | Locust load test, chaos, regression |

---

## SLOs at Go-Live

| SLO | Target |
|-----|--------|
| API availability | 99.95% |
| Submit P95 latency | < 200ms |
| Case status P95 latency | < 50ms |
| Pipeline P95 (real LLM) | < 5 min |
| Audit chain integrity | 100% |
| Data durability | 99.9999999% |
| RTO (region failure) | < 10 min |
| RPO (data loss window) | < 30 sec |
