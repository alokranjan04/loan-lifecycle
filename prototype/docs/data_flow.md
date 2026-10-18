# Data Flow — Agentic Loan Lifecycle

How data enters, transforms, and exits the system. Updated October 2026.

## Flow diagram

```mermaid
flowchart LR
    subgraph IN["Inputs"]
        AppJSON[/"application.json\nborrower · facility · RM"/]
        Docs[/"Supporting documents\nfinancials · KYC · valuation\nbank statement · project report"/]
        Browser[/"Browser (Web UI)\nAlpine.js SPA"/]
    end

    subgraph CTRL["Controls & Knowledge"]
        Vault["PII Vault\ntokenises names,\naccounts, addresses"]
        SCR[("Screening Watchlist\nSanctions · PEP\nAdverse media")]
        KB[("Policy KB\nBM25 index of\n9 policy docs · 143 clauses")]
        VDB[("Qdrant Vector DB\nopenai/text-embedding-3-small\n1536-dim · collection per SHA-256")]
        LLM["LLM Layer\nOpenRouterLLM / MockLLM"]
        OR["OpenRouter API\nLLM completions +\nembeddings"]
    end

    subgraph STATE["Shared State"]
        CF["CaseFile\nin-memory object\npasses between agents"]
        EXT[("extracted_fields.json\n35+ fields\neach with confidence + line citation")]
    end

    subgraph CALC["Deterministic Calculations (Python)"]
        Ratios["Financial ratios\nDSCR · LTV · debt/EBITDA\ncurrent ratio · vintage"]
        Score["8-factor scorecard\nrating 1–10\nindicative 1yr PD"]
        PolicyChk["13 policy checks\nPASS · FLAG · FAIL · NOT_EVALUATED"]
        RAGSearch["Hybrid RAG search\n40% BM25 + 60% vector cosine"]
    end

    subgraph HG["Human Gates"]
        HITL["HITL Data Validator\n(confidence < 75%)"]
        Credit["Credit Authority\n(SoD + DoA)"]
    end

    subgraph OUT["Outputs"]
        Summary[/"decision_summary.md\nhuman-readable report"/]
        Record[/"decision_record.json\nmachine-readable"/]
        Tracker[/"conditions_tracker.json\ndisbursement readiness"/]
        AuditLog[/"audit_log.jsonl\nSHA-256 hash chain"/]
        CaseReport[/"Case Report (web)\nreliability % · avg confidence\ngrounded evidence table"/]
    end

    Browser -->|REST API| CF
    AppJSON -->|load| CF
    Docs -->|raw text| Vault
    Vault -->|masked text| LLM
    LLM -->|completions| OR
    OR -->|structured fields| LLM
    LLM -->|structured fields| EXT
    EXT -->|enrich| CF

    CF -->|entity names| SCR
    SCR -->|hit / clear + detail| CF

    CF -->|clause query| RAGSearch
    RAGSearch -->|BM25| KB
    RAGSearch -->|embed + ANN| VDB
    VDB -->|embed query| OR
    RAGSearch -->|clause text + ref| CF

    CF -->|balance sheet · P&L · facility| Ratios
    Ratios -->|computed metrics| CF

    CF -->|metrics| PolicyChk
    PolicyChk -->|PASS/FLAG/FAIL per clause| CF

    CF -->|metrics + policy result| Score
    Score -->|rating · grade · PD| CF

    CF -->|avg confidence < 75%| HITL
    HITL -->|corrected fields| CF

    CF -->|LLM drafts narrative + conditions| LLM
    LLM -->|risk narrative · conditions text| CF

    CF -->|authority gate| Credit
    Credit -->|decision + rationale| CF

    CF -->|final state| Summary
    CF -->|final state| Record
    CF -->|conditions list| Tracker
    CF -->|final state| CaseReport
    CF -.->|every action hash-chained| AuditLog
```

## Field extraction detail

| Document type | Key extracted fields |
|---|---|
| `audited_financials` | revenue, EBITDA, total debt, current assets/liabilities, net profit |
| `bank_statement_summary` | average balance, returned items, bank credits, credit-to-revenue ratio |
| `collateral_valuation` | property value, valuation date, valuation age (days), LTV |
| `project_report` | projected revenue, projected DSCR, promoter contribution % |
| `kyc_ubo_declaration` | director names, date of incorporation, ownership structure |
| `board_resolution` | authorised signatories, resolution date |
| `application.json` | borrower legal name, sector, country, facility type, amount, tenor, purpose |

Every extracted field is stored as `{value, source_doc, page, line_ref, confidence}` and written to `extracted_fields.json`.

Confidence scoring:
- **≥ 90%** — citation verified, value present on the cited line
- **75–89%** — value extracted but citation is approximate
- **< 75%** — low-confidence; triggers HITL data validation gate

## RAG search pipeline

```
Analyst submits a question (or agent queries a policy rule)
         │
         ├── BM25 keyword match (40% weight)
         │       └── PolicyKnowledgeBase._search_bm25()
         │               └── TF-IDF over 143 clauses from 9 policy docs
         │
         └── Vector cosine similarity (60% weight)
                 ├── Embed query: POST /v1/embeddings to OpenRouter
                 │       model: openai/text-embedding-3-small → 1536-dim vector
                 └── ANN search in Qdrant collection policy_{sha256[:16]}
                         └── Returns top-k by cosine similarity

Merge: score = 0.4 × normalised_bm25 + 0.6 × cosine_sim
Output: clause_id, title, text, source_file, line_number, hybrid_score
```

Re-index trigger: any edit to `data/policy/docs/*.md` → SHA-256 of all files changes → new collection name → auto-built on next server start.

## PII handling

```
Raw document text
       ↓
  PII Vault.mask()           ← replaces names, accounts, addresses with tokens T-0001, T-0002 …
       ↓
  LLM call (masked text)     ← model never sees real PII
       ↓
  PII Vault.unmask()         ← tokens replaced back before storing in CaseFile
       ↓
  extracted_fields.json      ← real values; never logged to external services
```

## Audit chain

Each agent action appends one JSONL line:

```json
{"seq": 42, "ts": "2026-10-17T14:23:01Z", "actor": "system", "action": "policy_check_complete",
 "app_id": "APP-2026-0201", "detail": {"clauses_evaluated": 13, "fail_count": 0},
 "prev_hash": "a3f9…", "hash": "7c1d…"}
```

`hash = SHA-256(seq + ts + actor + action + detail + prev_hash)` — any tampering breaks the chain.

Verify with: `python run_demo.py --verify output/<APP-ID>/audit_log.jsonl`

## Case Report data assembly (web)

```
CaseFile (final state)
    │
    ├── Reliability score: verified_fields / total_fields × 100
    │       Source: extracted_fields where citation_verified = true
    │
    ├── Avg confidence: mean(field.confidence for all fields)
    │
    ├── Decision pipeline: sequential steps from CaseFile.timeline
    │       └── Includes HITL step if triggered (with approver name + rationale)
    │
    ├── Key metrics: DSCR, LTV, Debt/EBITDA, Current Ratio, Vintage, Bank/Revenue
    │       Colour-coded vs. policy thresholds (green/amber/red)
    │
    ├── Grounded evidence: grouped by document
    │       Each row: field name · value · source:line · quote · confidence %
    │
    └── Policy flags: FLAG/FAIL clauses only
            Each: clause ID · title · actual vs. required · curable note · conditions
```

## Output artefacts

| File | Format | Consumer |
|---|---|---|
| `decision_summary.md` | Markdown | Credit file, regulator, audit committee |
| `decision_record.json` | JSON | Downstream LOS, data warehouse, reporting |
| `extracted_fields.json` | JSON | QA review, model risk validation |
| `conditions_tracker.json` | JSON | Operations / disbursement team |
| `audit_log.jsonl` | JSONL (hash-chained) | Compliance, internal audit, forensics |
| `rm_request.txt` | Plain text | Relationship manager (missing-docs request) |
| Case Report (web) | Alpine.js rendered | Credit analyst, reviewer, demo audience |
