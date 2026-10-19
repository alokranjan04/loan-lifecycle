# Production System Design
## Agentic Loan Lifecycle — Scalable · Available · Secure

---

## Core Design Principles Applied

| Principle | How it applies here |
|-----------|-------------------|
| **Single Responsibility** | Each agent owns exactly one concern; pipeline orchestrator owns only sequencing |
| **Separation of Concerns** | API layer ≠ pipeline execution ≠ storage ≠ auth |
| **CAP Theorem → CP** | Bank context: Consistency + Partition Tolerance over Availability — a stale decision is worse than a brief outage |
| **Event-Driven** | Pipeline steps decoupled from HTTP via Pub/Sub; HTTP returns instantly, agents run async |
| **Idempotency** | Every operation is safe to retry — case ID is the idempotency key; duplicate runs are rejected |
| **Circuit Breaker** | LLM unavailable → fallback to MockLLM; Qdrant down → fallback to BM25; never hard fail |
| **Bulkhead** | LLM pool, Qdrant pool, DB pool are isolated — one exhausted pool does not starve others |
| **Saga (Choreography)** | Each agent publishes completion event; next agent subscribes — no central coordinator bottleneck |
| **CQRS** | Reads (case status, history, reports) served from read replicas; writes (agent results, approvals) go to primary |
| **Zero Trust** | Every service-to-service call carries a short-lived token; no implicit trust from VPC position |
| **Immutability** | Audit entries are append-only; decisions are never updated, only superseded |
| **Observability First** | Every operation emits a structured log, a span, and a metric — not as an afterthought |

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  INTERNET                                                           │
│                                                                     │
│   Browser / API client                                              │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  EDGE LAYER                                                         │
│                                                                     │
│   Cloud Armor  ──  WAF rules, DDoS L3/L4/L7, geo-fencing          │
│        │                                                            │
│   Global HTTPS Load Balancer  ──  anycast IP, SSL offload          │
│        │                    ──  URL-based routing                   │
│   Cloud CDN  ──  static assets (index.html, JS, CSS)               │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
     asia-south1  asia-southeast1  europe-west1
          ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  API LAYER  (Cloud Run — stateless, auto-scaling 2→100)             │
│                                                                     │
│   loan-lifecycle-api                                                │
│   ├── POST /api/applications    → validate + publish to Pub/Sub     │
│   ├── GET  /api/stream/{id}     → SSE from Redis Streams            │
│   ├── POST /api/approve/{id}    → validate role + publish event     │
│   ├── GET  /api/cases           → read replica query                │
│   └── GET  /api/rag/status      → Qdrant health check               │
│                                                                     │
│   Min instances: 2 per region   Concurrency: 80 per instance        │
│   CPU: always-allocated         Memory: 2Gi                         │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ publish
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  EVENT BUS  (Cloud Pub/Sub)                                         │
│                                                                     │
│   Topics:                                                           │
│   ├── case.submitted      → triggers IntakeAgent                    │
│   ├── agent.completed     → triggers next agent in sequence         │
│   ├── gate.pending        → notifies approver, starts timeout       │
│   ├── gate.resolved       → resumes pipeline                        │
│   └── case.finalised      → triggers report generation              │
│                                                                     │
│   Dead-letter topic: case.dlq  (failed after 3 retries → alert)     │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ subscribe
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PIPELINE WORKERS  (Cloud Run Jobs — one per agent)                 │
│                                                                     │
│   intake-worker          document-intelligence-worker               │
│   completeness-worker    due-diligence-worker                       │
│   policy-worker          risk-worker                                │
│   approval-worker        disbursement-worker                        │
│                                                                     │
│   Each worker:                                                      │
│   ├── Pulls one message, processes, acks                            │
│   ├── Writes result to PostgreSQL (agent_steps table)               │
│   ├── Streams progress to Redis Streams (SSE source)                │
│   ├── Publishes agent.completed to Pub/Sub                          │
│   └── On failure: nacks → Pub/Sub retries with backoff              │
│                                                                     │
│   Scales to zero between jobs; no idle cost                         │
└──────────┬─────────────────────────────────────────────────────────┘
           │
    ┌──────┼───────────────────────────────────┐
    ▼      ▼                                   ▼
┌───────┐ ┌───────────────────────────────┐  ┌────────────────────┐
│CACHE  │ │  PRIMARY DATASTORE            │  │  AI SERVICES       │
│       │ │                               │  │                    │
│Cloud  │ │  Cloud SQL PostgreSQL (HA)    │  │  OpenRouter API    │
│Memory │ │  ├── Primary  (asia-south1)   │  │  (LLM completions) │
│store  │ │  └── Replica  (asia-south-east│  │                    │
│Redis  │ │                               │  │  Qdrant Cloud      │
│       │ │  Tables:                      │  │  (vector search)   │
│Uses:  │ │  cases, agent_steps,          │  │                    │
│- SSE  │ │  gate_events, audit_entries,  │  │  Circuit breaker:  │
│  stream│ │  decision_records,           │  │  if OpenRouter 5xx │
│- rate │ │  extracted_fields,            │  │  → MockLLM         │
│  limit│ │  activity_log                 │  │  if Qdrant timeout │
│- locks│ │                               │  │  → BM25 fallback   │
└───────┘ │  Read replica handles all     │  └────────────────────┘
          │  GET /api/cases queries       │
          └───────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  SECURITY PLANE  (cross-cutting)                                    │
│                                                                     │
│   Identity-Aware Proxy (IAP)  ──  Google-managed OAuth for staff    │
│   Secret Manager  ──  all API keys, DB passwords, JWT secrets       │
│   Cloud KMS  ──  CMEK for Cloud SQL, Cloud Storage, Pub/Sub         │
│   VPC Service Controls  ──  prevent data exfiltration               │
│   Binary Authorization  ──  only signed images deploy to Cloud Run  │
│   Cloud DLP  ──  scan uploaded documents for PII before processing  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  OBSERVABILITY PLANE  (cross-cutting)                               │
│                                                                     │
│   Cloud Logging  ──  structured JSON logs, 90-day hot retention     │
│   Cloud Trace  ──  OpenTelemetry spans across API + workers         │
│   Cloud Monitoring  ──  Prometheus-compatible metrics               │
│   Error Reporting  ──  automatic exception grouping + alerting      │
│   Grafana  ──  dashboards (ops, cost, HITL gates, compliance)       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## High Availability Design

### Multi-Region Active-Active
- **API layer**: Cloud Run deployed in `asia-south1` (Mumbai) + `asia-southeast1` (Singapore)
- **Global LB**: Routes to nearest healthy region; automatic failover in <10s
- **Database**: Cloud SQL HA with synchronous standby in same region + async read replica in secondary region
- **Qdrant Cloud**: Multi-node cluster with replication factor 2
- **Redis**: Cloud Memorystore with high-availability mode (automatic failover <30s)

### Availability Target: 99.95%
| Component | SLA | Downtime/month |
|-----------|-----|---------------|
| Cloud Run | 99.95% | 22 min |
| Cloud SQL HA | 99.95% | 22 min |
| Cloud Memorystore HA | 99.9% | 43 min |
| Qdrant Cloud | 99.9% | 43 min |
| Composite (with fallbacks) | **99.9%** | 43 min |

---

## Scalability Design

### Current Bottleneck: Background Thread
The pipeline runs in a `threading.Thread` inside the API container — this means:
- Only 1 active pipeline per container instance
- Pipeline blocked by LLM latency (2-5 min per run)
- Cannot scale horizontally

### Solution: Decouple with Pub/Sub + Worker Pool

```
Before:  HTTP request → [API + Pipeline Thread]  (coupled)

After:   HTTP request → API → Pub/Sub → Worker Pool
                                └─ IntakeWorker (×N)
                                └─ DocIntWorker (×N)
                                └─ PolicyWorker (×N)
                                   ...
```

Each worker is a separate Cloud Run service that:
- Pulls one Pub/Sub message
- Runs one agent
- Publishes result
- Scales independently (e.g. DocInt worker can scale to 20× during peak)

### Throughput Target
| Load | Instances | Cases/hour |
|------|-----------|-----------|
| Normal | 2 API + 2 per worker | 10 |
| Peak | 5 API + 10 per worker | 50 |
| Burst | 20 API + 50 per worker | 200 |

Cloud Run scales from 0→100 instances in ~10 seconds.

---

## Low Latency Design

### P95 Latency Targets
| Operation | Target | How achieved |
|-----------|--------|-------------|
| Submit application | < 200ms | Async: validate + publish to Pub/Sub, return immediately |
| Get case status | < 50ms | Redis cache + read replica |
| SSE stream event | < 100ms | Redis Streams → SSE push |
| Policy RAG query | < 300ms | Qdrant in-memory vectors + BM25 pre-indexed |
| Approval submit | < 200ms | Optimistic lock + Pub/Sub publish |
| Static assets | < 20ms | Cloud CDN edge cache |

### Caching Strategy (Cache-Aside)
```
L1: Cloud CDN (static HTML/JS/CSS) — TTL 1 hour
L2: Redis (case status, pending approvals) — TTL 30 seconds
L3: Qdrant in-memory index (policy vectors) — rebuilt only on SHA-256 change
L4: PostgreSQL read replica (reports, history) — no TTL, always fresh
```

---

## Security Design (Defence in Depth)

### 7 Security Layers

```
Layer 1 — NETWORK
  Cloud Armor: WAF, DDoS, geo-block, rate limit 100 req/s per IP

Layer 2 — IDENTITY
  IAP: Google-managed OAuth2 for all staff access
  Workload Identity: service-to-service auth (no static keys)
  API keys: scoped per integration (core banking, reporting)

Layer 3 — TRANSPORT
  TLS 1.3 enforced end-to-end
  HSTS preloading
  mTLS between internal services (Cloud Run → Cloud SQL)

Layer 4 — APPLICATION
  Input validation: Pydantic models + file type whitelist + ClamAV scan
  Output encoding: CSP headers prevent XSS
  OWASP Top 10 mitigations in middleware

Layer 5 — DATA
  PII tokenisation before any LLM call (already built)
  AES-256-GCM field-level encryption for decision records
  CMEK: customer-managed keys in Cloud KMS
  Cloud DLP: scan uploads before ingestion

Layer 6 — SECRETS
  Secret Manager: all API keys, DB passwords, JWT secrets
  Zero secrets in env vars, code, or container images
  Key rotation: automated 90-day rotation via Secret Manager

Layer 7 — AUDIT
  SHA-256 hash-chained audit log (already built)
  WORM storage: Cloud Storage Object Lock (7-year retention)
  Activity log: every API call logged with actor, IP, timestamp
  VPC Service Controls: prevent data leaving the perimeter
```

### Zero Trust Implementation
```
Every request must present:
  ├── Valid JWT (short-lived, 15 min) issued by IAP/Identity Platform
  ├── Role claim matching the required permission
  ├── Request signed with HMAC (replay protection)
  └── Source IP within allowed range (staff VPN or office CIDR)

Service-to-service:
  ├── Workload Identity Federation (no JSON key files)
  ├── Each Cloud Run service has its own service account
  └── Least-privilege IAM: only the permissions it needs
```

---

## Fault Tolerance Patterns

### Circuit Breaker — LLM Calls
```python
States: CLOSED → OPEN → HALF-OPEN

CLOSED:    normal operation, all calls go to OpenRouter
OPEN:      OpenRouter failed 5× in 60s → switch to MockLLM, alert ops
HALF-OPEN: after 5 min, try 1 real call → if OK, back to CLOSED

Thresholds: 5 failures in 60s → OPEN; 5 min timeout → HALF-OPEN
```

### Retry with Exponential Backoff
```
Attempt 1: immediate
Attempt 2: 2s delay
Attempt 3: 4s delay
Max attempts: 3
Jitter: ±500ms (prevents thundering herd)
After 3 failures: message → dead-letter topic → alert
```

### Bulkhead — Resource Isolation
```
LLM connection pool:       max 10 concurrent calls
Qdrant connection pool:    max 20 concurrent queries
DB connection pool:        max 50 connections (PgBouncer)
Each pool fails independently — Qdrant exhausted ≠ DB unavailable
```

### Saga Pattern — Agent Pipeline
```
Each agent is a saga step:
  execute() → on success: publish next event
            → on failure: publish compensating event (e.g. return_to_intake)

No distributed transaction needed — each agent writes its own result
and the orchestrator reconstructs state from event history.
This means: replay from any checkpoint, idempotent re-runs.
```

---

## Database Design for Scale

### Sharding Strategy
```
cases table:        sharded by case_id (UUID v4, random distribution)
audit_entries:      partitioned by month (time-series, bulk writes)
extracted_fields:   partitioned by case_id (co-located with cases)
activity_log:       partitioned by day (high volume, time-series queries)
```

### Read/Write Separation (CQRS)
```
Write path:  API → Cloud SQL primary → replication lag ~100ms
Read path:   API → Cloud SQL read replica (case status, history)
             API → Redis cache (hot data: pending approvals, active cases)
             API → Qdrant (vector search, always reads in-memory)
```

### Connection Pooling
```
PgBouncer in transaction mode:
  ├── Max server connections: 100 (Cloud SQL limit)
  ├── Max client connections: 1000
  └── Pool mode: transaction (most efficient for short queries)
```

---

## Deployment Strategy

### Blue-Green Deployment (zero downtime)
```
Current:  BLUE  (v1.2.3) — 100% traffic
Deploy:   GREEN (v1.2.4) — 0% traffic, health checks pass
Shift:    BLUE 90% / GREEN 10%  → watch error rates for 5 min
Shift:    BLUE 0% / GREEN 100%
Rollback: flip traffic back to BLUE in <30 seconds if error rate spikes
```
Cloud Run supports traffic splitting natively — no extra tooling needed.

### Database Migrations
```
Alembic migrations run as a Cloud Run Job before each deploy
Migration must be:
  ├── Backward compatible (old code can read new schema)
  ├── Additive only (new columns nullable or with defaults)
  └── Tested against a clone of production data
Never: DROP COLUMN, ALTER TYPE in the same deploy as code change
```

---

## Revised 8-Week Production Plan (System Design Focus)

| Week | Theme | Key Deliverables | System Design Principle |
|------|-------|-----------------|------------------------|
| **1** | Foundation hardening | `/health` + `/ready` probes · structured logging · fix bare excepts · PgBouncer setup | Observability First |
| **2** | Auth & Zero Trust | IAP + Identity Platform · JWT (15 min) · Workload Identity for service accounts · RBAC middleware | Zero Trust |
| **3** | Persistence & CQRS | PostgreSQL HA + read replica · Redis HA · PgBouncer · CQRS read/write split · Alembic migrations | CQRS · CP over AP |
| **4** | Event-Driven Pipeline | Pub/Sub topics · agent workers as separate Cloud Run services · dead-letter queue · circuit breaker | Event-Driven · Bulkhead · Circuit Breaker |
| **5** | Security Hardening | Cloud Armor WAF · VPC Service Controls · Cloud KMS CMEK · Cloud DLP · Binary Authorization | Defence in Depth |
| **6** | Observability | OpenTelemetry → Cloud Trace · Cloud Monitoring metrics · Grafana dashboards · alert policies | Observability First |
| **7** | Compliance & HA | WORM audit (Object Lock) · activity log · multi-region active-active · blue-green deploy · SR 11-7 | Immutability · HA |
| **8** | Load Test & Go-Live | Locust 200 concurrent · chaos (kill Qdrant, kill DB) · OWASP ZAP · runbooks · SLO sign-off | Fault Tolerance |

---

## SLO Definitions (Production Targets)

| SLO | Target | Measurement |
|-----|--------|-------------|
| API availability | 99.95% | Uptime checks every 60s from 3 regions |
| P95 submission latency | < 200ms | Cloud Monitoring latency distribution |
| P95 case status latency | < 50ms | Redis hit rate + read replica latency |
| Pipeline completion (mock LLM) | < 30s | end-to-end trace duration |
| Pipeline completion (real LLM) | < 5 min | end-to-end trace duration |
| Audit chain integrity | 100% | Daily hash-chain verification job |
| Data durability | 99.9999999% (9 nines) | Cloud SQL HA + PITR backups |

---

## Cost at Scale (500 cases/month)

| Component | Service | Cost/month |
|-----------|---------|-----------|
| API (2 regions, min-2) | Cloud Run | $80 |
| Pipeline workers (scale-to-zero) | Cloud Run Jobs | $40 |
| Database HA + replica | Cloud SQL | $250 |
| Cache HA | Memorystore Redis | $120 |
| Events | Cloud Pub/Sub | $5 |
| Secrets | Secret Manager | $2 |
| CDN + LB | Cloud CDN + HTTPS LB | $30 |
| Logging + Tracing | Cloud Operations | $50 |
| LLM (500 cases × $0.50) | OpenRouter | $250 |
| Vector DB | Qdrant Cloud | $0 (free tier) or $25 (dedicated) |
| **Total** | | **~$830/month** |
