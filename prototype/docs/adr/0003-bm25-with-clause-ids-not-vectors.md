# ADR 0003: Keyword retrieval over clause IDs, not a vector database, at this policy size

**Status:** accepted for the POC; revisit at scale · **Date:** 2026-10-16

## Context
The credit policy in scope has about 20 clauses. Each policy result must cite the exact clause and the version in force on the decision date. Vector search returns "similar" text, which is the wrong guarantee for a citation: a near-miss clause is worse than no clause.

## Decision
- Policy checks are keyed by clause ID (`POL-2.4`) and look the clause up directly; BM25 over clause-level chunks (`knowledge.py`) is used only for free-text questions and supporting retrieval.
- The policy registry (`data/policy/registry.json`) holds each version with its effective date, parameters and a sha256. A check cites `POL-2.4@v3.2`, and the decision record stores the policy hash.
- A vector or hybrid index (Azure AI Search hybrid, OpenSearch, Vertex AI Search) is added when the corpus grows to product notes, regulatory circulars and precedent memos, where semantic recall matters. Clause IDs and effective dates stay as filters on that index.

## Consequences
- No embedding pipeline, vector store or re-indexing to run for the POC; nothing to drift.
- Retrieval is exact and explainable. The policy-change demo shows the same case passing under v3.2 and failing under v3.3, each citing its own version, and an October decision replays exactly in November.
- Free-text questions over large corpora are weaker until the hybrid index is added. That is a phase-2 need, not a POC need.
