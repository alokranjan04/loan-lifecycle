# Architecture — Agentic Loan Lifecycle Management

> Application intake through disbursement conditions

## Component diagram

```mermaid
flowchart TD
    Applicant(["Applicant / RM\nSubmits application"])
    CLI["CLI Entry Point\nrun_demo.py"]
    AppData[("Application Files\nJSON + supporting docs")]
    Orch["Orchestrator\nCase state machine (SoD)"]

    subgraph HG["Human Gates — SoD enforced"]
        HC["Credit Authority\nSCM · Committee · Board"]
        HCO["Compliance Officer\nPEP / sanctions gate"]
    end

    subgraph AP["Agent Pipeline — sequential"]
        A1["1  Intake Agent\nForm completeness · doc list"]
        A2["2  Document Intelligence\nExtract fields · cross-check"]
        A3["3  Completeness Agent\nMissing docs → RM email"]
        A4["4  Due Diligence\nKYC · Sanctions · Conduct"]
        A5["5  Policy Eligibility\n13 clauses · DSCR · LTV"]
        A6["6  Risk Agent\n8-factor scorecard 1–10"]
        A7["7  Approval Workflow\nRoute · draft conditions"]
        A8["8  Disbursement Agent\nCondition tracker"]
        A1 --> A2 --> A3 --> A4 --> A5 --> A6 --> A7 --> A8
    end

    subgraph BB["Bank Boundary — PII stays inside"]
        PII["PII Vault\nMask → model → unmask"]
        SCR[("Screening Watchlist\nSanctions / PEP / Adverse media")]
        LLM["LLM Layer\nMockLLM / ClaudeLLM"]
        KB[("Policy KB\nBM25 · credit_policy.md")]
        AUD[("Audit Log\nSHA-256 hash chain")]
        OUT[("Output Files\nSummary · Record · Tracker")]
    end

    Applicant -->|submit| CLI
    CLI -->|"run_case()"| Orch
    CLI -.->|load app| AppData
    Orch -->|start pipeline| A1
    Orch -->|PEP gate| HCO
    Orch -->|credit decision| HC
    Orch -.->|log events| AUD
    A2 -->|mask PII| PII
    A2 -->|extract fields| LLM
    A4 -->|screen entity| SCR
    A5 --> KB
    A6 --> LLM
    A7 --> LLM
    A8 -->|write outputs| OUT
```

## Layers

| Layer | Components | Responsibility |
|---|---|---|
| **Entry** | CLI `run_demo.py` | Load case files, invoke orchestrator, stream output |
| **Orchestration** | Orchestrator | Sequence agents, enforce SoD, route human gates |
| **Agent Pipeline** | 8 agents (Intake → Disbursement) | Sequential domain analysis; each agent enriches the shared CaseFile |
| **Human Gates** | Credit Authority, Compliance Officer | Final decisions with delegated authority; overrides require rationale |
| **LLM Layer** | MockLLM / ClaudeLLM (`claude-sonnet-4-6`) | Field extraction, narrative drafting — no deterministic decisions |
| **Data & Controls** | PII Vault, Policy KB, Screening Watchlist, Audit Log | Tokenise PII before model calls, BM25 clause retrieval, sanctions/PEP screening, tamper-evident log |
| **Outputs** | `decision_summary.md`, `decision_record.json`, `conditions_tracker.json`, `extracted_fields.json` | Auditable artefacts written once the case resolves |

## Authority limits (deterministic routing)

| Facility size | Required approver |
|---|---|
| ≤ USD 2 000 000 | Senior Credit Manager (SCM) |
| ≤ USD 10 000 000 | Regional Credit Committee |
| > USD 10 000 000 | Board Credit Committee |

## Controls summary

- **PII Vault** — every identifier is tokenised before any text reaches the LLM; unmasked only in final outputs.
- **Audit log** — SHA-256 hash-chained JSONL; `--verify` flag replays the chain to detect tampering.
- **Prompt pinning** — `PROMPT_VERSION` constant in `llm.py`; version recorded in every `decision_record.json`.
- **Deterministic ratios** — DSCR, LTV, debt/EBITDA, current ratio are computed in Python, not inferred by the model.
- **SoD enforcement** — blocked attempts (wrong role, insufficient authority) are counted and reported in the summary.
