# Data Flow — Agentic Loan Lifecycle

How data enters, transforms, and exits the system.

## Flow diagram

```mermaid
flowchart LR
    subgraph IN["Inputs"]
        AppJSON[/"application.json\nborrower · facility · RM"/]
        Docs[/"Supporting documents\nfinancials · KYC · valuation\nbank statement · project report"/]
    end

    subgraph CTRL["Controls"]
        Vault["PII Vault\ntokenises names,\naccounts, addresses"]
        SCR[("Screening Watchlist\nSanctions · PEP\nAdverse media")]
        KB[("Policy KB\nBM25 index of\ncredit_policy.md")]
        LLM["LLM Layer\nfield extraction\nnarrative drafting"]
    end

    subgraph STATE["Shared State"]
        CF["CaseFile\nin-memory object\npasses between agents"]
        EXT[("extracted_fields.json\n~50 fields\neach with line citation")]
    end

    subgraph CALC["Deterministic Calculations (Python)"]
        Ratios["Financial ratios\nDSCR · LTV · debt/EBITDA\ncurrent ratio · vintage"]
        Score["8-factor scorecard\nrating 1–10\nindicative 1yr PD"]
        PolicyChk["13 policy checks\nPASS · FLAG · FAIL"]
    end

    subgraph OUT["Outputs"]
        Summary[/"decision_summary.md\nhuman-readable\nmarkdown report"/]
        Record[/"decision_record.json\nmachine-readable\ndownstream record"/]
        Tracker[/"conditions_tracker.json\ndisbursement readiness\nper condition ID"/]
        AuditLog[/"audit_log.jsonl\nSHA-256 hash chain\nevery agent action"/]
    end

    AppJSON -->|"load"| CF
    Docs -->|"raw text"| Vault
    Vault -->|"masked text"| LLM
    LLM -->|"structured fields"| EXT
    EXT -->|"enrich"| CF

    CF -->|"entity names"| SCR
    SCR -->|"hit / clear + detail"| CF

    CF -->|"clause query"| KB
    KB -->|"clause text + ref"| CF

    CF -->|"balance sheet,\nP&L, facility terms"| Ratios
    Ratios -->|"computed metrics"| CF

    CF -->|"metrics"| PolicyChk
    PolicyChk -->|"PASS/FLAG/FAIL per clause"| CF

    CF -->|"metrics + policy result"| Score
    Score -->|"rating · grade · PD"| CF

    CF -->|"LLM drafts\nnarrative + conditions"| LLM
    LLM -->|"risk narrative\nconditions text"| CF

    CF -->|"final state"| Summary
    CF -->|"final state"| Record
    CF -->|"conditions list"| Tracker
    CF -.->|"every action\nhash-chained"| AuditLog
```

## Field extraction detail

| Document type | Key extracted fields |
|---|---|
| `financials` | revenue, EBITDA, total debt, current assets/liabilities, net profit |
| `bank_statement` | average balance, returned items, bank credits, credit-to-revenue ratio |
| `valuation` | property value, valuation date, valuation age (days), LTV |
| `project_report` | projected revenue, projected DSCR, promoter contribution % |
| `kyc` | director names, date of incorporation, ownership structure |
| `application.json` | borrower legal name, sector, country, facility type, amount, tenor, purpose |

Every extracted field is stored as `{value, source_doc, page, line_ref, confidence}` and written to `extracted_fields.json`.

## PII handling

```
Raw document text
       ↓
  PII Vault.mask()           ← replaces names, accounts, addresses with tokens  T-0001, T-0002 …
       ↓
  LLM call (masked text)     ← model never sees real PII
       ↓
  PII Vault.unmask()         ← tokens replaced back before storing in CaseFile
       ↓
  extracted_fields.json      ← real values, never logged to external services
```

## Audit chain

Each agent action appends one JSONL line:

```json
{"seq": 42, "ts": "2026-10-17T14:23:01Z", "actor": "system", "action": "policy_check_complete",
 "app_id": "APP-2026-0001", "detail": {"clauses_evaluated": 13, "fail_count": 0},
 "prev_hash": "a3f9…", "hash": "7c1d…"}
```

`hash = SHA-256(seq + ts + actor + action + detail + prev_hash)` — any tampering breaks the chain.
Verify with: `python run_demo.py --verify output/<APP-ID>/audit_log.jsonl`

## Output artefacts

| File | Format | Consumer |
|---|---|---|
| `decision_summary.md` | Markdown | Credit file, regulator, audit committee |
| `decision_record.json` | JSON | Downstream LOS, data warehouse, reporting |
| `extracted_fields.json` | JSON | QA review, model risk validation |
| `conditions_tracker.json` | JSON | Operations / disbursement team |
| `audit_log.jsonl` | JSONL (hash-chained) | Compliance, internal audit, forensics |
| `rm_request.txt` | Plain text | Relationship manager (missing-docs request) |
