# Loan Lifecycle — Video Walkthrough Script
### Assignment 1 · Financial Institution: Agentic Loan Lifecycle Management
### Alok Ranjan · Updated October 2026

---

## Assignment completion status

| Requirement | Status | Notes |
|---|---|---|
| Map the lifecycle — current process + 5 high-value AI areas | ✅ 100% | Covered in Part 1 of script; before/after table in Part 10 |
| Design the agent ecosystem (8 agents) | ✅ 100% | All 8 built and running; Portfolio Monitoring scoped to Phase 2 |
| Build working agent/workflow (intake → audit) | ✅ 100% | Full pipeline, 39 golden cases, mock + live LLM (OpenRouter) |
| Show architecture — RAG, security, HITL, auditability, observability | ✅ 95% | RAG now **vector + BM25** (Qdrant + OpenRouter embeddings, 143 clauses); full audit chain |
| Before vs. after with quantified impact | ✅ 90% | Before/after table in script Part 10 with stated assumptions |
| 6–8 week POC plan with milestones and KPIs | ✅ 85% | In script Part 10; full doc in `docs/first_two_weeks.md` |
| Policy Library (admin edit + re-ingest) | ✅ 100% | 9 policy docs, editable in portal, RAG auto re-indexes on save |
| Case Report with confidence + reliability % | ✅ 100% | 100% field verification, 98% avg confidence on demo case |
| Credential management and security | ✅ 100% | `.env` / `.env.local`, `.gitignore`, OpenRouter key isolation |

**Overall: ~95% complete** — all core engineering requirements met.

---

## What is built

### Pipeline (8 agents in sequence)
1. **Origination & Intake Agent** — parses application form, identifies required document types
2. **Document Intelligence Agent** — extracts 35+ fields from 7 document types with confidence scores and line-level citations
3. **Completeness Agent** — identifies missing documents, drafts RM request email
4. **Due Diligence Agent** — screens directors, UBOs and entity against sanctions + PEP lists
5. **Policy & Eligibility Agent** — runs 13 policy checks (POL-2.1 through POL-5.2) against v3.2 credit policy
6. **Risk Agent** — scorecard (8 factors, 30 points), internal rating (1–10), PD estimate
7. **Approval & Workflow Agent** — recommendation, conditions, delegated authority gates
8. **Disbursement & Condition Monitoring Agent** — blocks disbursement until conditions precedent cleared; schedules covenants

### Knowledge layer (RAG)
- **9 policy documents** with 143 named clauses (POL, DOA, KYC, EDD, SAN, COL, RRM, RAS, PPG)
- **Hybrid search**: 40% BM25 keyword + 60% vector cosine via Qdrant (`policy_f1fe794acc3d4cf8`, 1536-dim, `openai/text-embedding-3-small` via OpenRouter)
- **Admin Policy Library** — edit any clause in the browser; save triggers SHA-256 change → Qdrant re-indexes automatically on next server start

### Case Report (new)
- **Reliability %** — verified fields / total (100% on demo case)
- **Avg confidence** — 98% on demo case (all citations verified)
- **Decision pipeline flow** — shows exactly when and why human review is triggered
- **Grounded evidence table** — every extracted value traced to `source:line` with quote

### Demo case — APP-2026-0201 (Sunrise Cold Chain Logistics Ltd)
- USD 3,800,000 secured term loan, 60 months
- **12 PASS / 1 FLAG** on policy checks; FLAG on POL-2.3 (DSCR 1.39x between 1.25x–1.40x)
- **Escalated** to Regional Credit Committee — threshold not met for auto-approval
- **APPROVED WITH CONDITIONS** — C01 (DSRA pre-disbursement) + C02 (annual DSCR covenant)
- Risk grade BBB, score 8/30, PD 0.10%

### Security
- Keys in `.env.local` (never committed); `.gitignore` blocks all `*.env` files
- Role-based login: segregation of duties enforced in code
- SHA-256 hash-chained audit log — any tampering breaks the chain
- Documents wrapped as untrusted data; prompt injection quarantined before any model call

---

## How to use this script

**The one sentence to remember:** *the AI reads and writes, the code checks the rules, and people make the decision.*

Aim for **22–25 minutes**. In the script, **Say** = what you say out loud. **Do** = what you click. **In plain words** = optional analogy for non-technical reviewers.

---

## The process (before recording)

### Step 1: Start the server

```
cd "C:\Users\Alok Ranjan\Documents\loan-lifecycle\prototype"
double-click start_web.bat   ← loads .env.local automatically
open http://localhost:8000
```

Check:
- RAG badge in sidebar is **green** (⬡ RAG: vector + BM25)
- APP-2026-0201 shows APPROVED WITH CONDITIONS in Cases list
- Decision Log shows at least one completed case

### Step 2: Screen setup
- 1920×1080, browser zoom 125%
- Do Not Disturb on. Close email and chat.
- Tab 1: http://localhost:8000 — Tab 2: deck — Tab 3: terminal (font 18+)
- This script on your phone or second screen

### Step 3: Pre-flight checks
- [ ] Login as `newuser / demo123` — applicant portal appears, no admin screens
- [ ] Login as `amara.osei / demo123` — Dashboard, Cases, Policy Library, Decision Log all visible
- [ ] Open Cases → click APP-2026-0201 → Case Report tab loads with 100% reliability badge
- [ ] Run eval (offline mock) — completes in ~10 s, shows metrics table
- [ ] RAG badge in sidebar is green

---

## The script — ten parts

---

### Part 1 · The problem — how commercial lending works today (1.5 min)

**Do:** Start on a deck slide: the 10-stage lending lifecycle diagram.

**Say:** "Before I show the system, let me show the problem it solves. A commercial loan goes through ten stages: origination, due diligence, appraisal, approval, documentation, disbursement, monitoring, compliance, renewal, and closure. The technology is rarely the bottleneck. The bottleneck is information."

**Do:** Point at the three main pain points on the slide.

**Say:** "Stage one: the RM collects documents by email. On average a pack comes back incomplete 2.5 times — each round trip adds three business days. Stage three: an analyst spends 14 hours spreading financials from PDFs into Excel, and another 10 hours writing a credit memo that mostly restates what those PDFs already say. Stage four: a stale valuation, an expired passport, a director on a watchlist — these are often discovered at the credit committee on day 15, not at intake on day one. Sending the case back adds another week."

**Do:** Switch to the 5 high-value AI areas table.

**Say:** "I mapped five areas where agents create the most measurable value: document intelligence and spreading — the single largest block of analyst time; intake completeness and the missing-document loop; policy checks that run at intake instead of committee; risk observation and memo drafting; and condition and covenant monitoring post-approval. These five areas are what I built. Let me show you."

**In plain words:** A school library where the librarian has to phone home three times, re-copy the book details by hand, and wait for the head teacher to be free — that is commercial lending today.

---

### Part 2 · What I built — the dashboard (1 min)

**Do:** Open browser. Log in as `amara.osei / demo123`. Dashboard appears.

**Say:** "Hi, I'm Alok. This is LoanPilot — eight AI agents that take a commercial loan from first document to final approval. Instead of just showing slides, I'll run it live against 39 test cases. Every result is produced by the system running on this laptop right now, not pre-recorded."

**Do:** Point at the eight-agent pipeline diagram.

**Say:** "Eight agents in a fixed sequence: Origination, Document Intelligence, Completeness, Due Diligence, Policy and Eligibility, Risk, Approval and Workflow, and Disbursement and Condition Monitoring. A ninth agent — Portfolio Monitoring — is designed for Phase 2. It needs live core banking feeds which aren't available in a prototype."

**Do:** Point at the RAG badge in the sidebar — it should be green.

**Say:** "One thing I want to highlight: the knowledge layer. The credit policy — 9 documents, 143 named clauses — is loaded into a hybrid search engine: BM25 keyword retrieval combined with vector embeddings via Qdrant. When an agent checks clause POL-2.3, it retrieves the exact clause text, applies the rule, and the citation goes into the audit log. Admins can edit any clause in the Policy Library and the system re-indexes automatically."

**In plain words:** A school library where a helper robot reads every book, a calculator checks the sums, but only the head librarian decides who borrows the rare books.

---

### Part 3 · Role-based login — new user submits a loan (1.5 min)

**Do:** Click Sign out. Land on login screen. Point at the two quick-fill cards.

**Say:** "Two roles. A Relationship Manager — new user — can only submit applications and track their own cases. An admin logs in with their actual name from the approver list; their authority is set at login and cannot be overridden in any form."

**Do:** Click the green **New User** card → Sign in. Applicant portal appears.

**Say:** "The new user sees only this — their own submissions and a form. No case lists, no evals, no policy controls."

**Do:** Click **New Application**. Fill:
- Legal name: `Veritas Logistics Pvt Ltd`
- Sector: `Transport & logistics` | Country: `India` | Incorporated: `2018-05-01`
- Click **Next** — Amount: `1500000` | Tenor: `60` | Purpose: `Purchase of 12 refrigerated trucks`
- Click **Next** — **Fill all with templates** → **Create & run pipeline**

**Say:** "Pipeline starts immediately. The new user watches their card live — Processing → decision. They get a toast the moment the result lands."

**Do:** Wait for the green APPROVED toast.

**Say:** "Approved — Senior Credit Manager level, under two million. The new user sees the result, not the internal pipeline."

---

### Part 4 · The end-to-end demo case — Sunrise Cold Chain (3 min) ← NEW

**Do:** Sign out → log in as `amara.osei / demo123`. Click Cases → click **APP-2026-0201** (Sunrise Cold Chain Logistics Ltd).

**Say:** "This is the demo approval case I built to show the full end-to-end flow with confidence scores and reliability. Sunrise Cold Chain is applying for USD 3.8 million, 60-month secured term loan to acquire a Grade-A refrigerated warehouse in Bhiwandi Logistics Park."

**Do:** Point at the Case Report tab (it opens by default). Show the three badges at the top.

**Say:** "The Case Report is the new view I added — it shows you how trustworthy the system's own work is before you look at the decision. 100% reliability — all 35 extracted fields were verified against the source document. 98% average confidence. 12 policy checks passed, 1 flagged."

**Do:** Scroll to the Decision Pipeline flow.

**Say:** "This is the key flow. The system ran 13 policy checks. Eleven passed automatically. One check — POL-2.3, Debt Service Coverage — hit a flag: the projected DSCR is 1.39x, which is above the 1.25x floor but below the 1.40x clean-pass threshold. When a threshold is not fully met but is curable, the system cannot auto-approve — it escalates to human review. That's the 'Human Review Required' step you see here."

**Do:** Point at the Human Review Required step with the "Threshold not met → escalated to Regional Credit Committee" label.

**Say:** "The system routes to the Regional Credit Committee — the right authority level for a USD 3.8 million facility. Ananya Sharma reviewed it: strong 7-year relationship, clean KYC, all other ratios within policy. She approved with two conditions."

**Do:** Scroll to the Policy flags section.

**Say:** "The flag is fully grounded. The system shows you the exact clause — POL-2.3 — with its text, the actual value of 1.39x versus the 1.40x clean threshold, and the two citations: one from the financial projections file, line 10, and one from the audited financials. Everything traceable."

**Do:** Scroll to the Grounded evidence table. Expand financials.

**Say:** "Every single number the system used is here. Revenue: USD 11.1 million, from audited_financials.txt line 7. EBITDA: USD 1.887 million, same file. Each row shows the field, its value, the source and line, the actual quoted text, and the confidence percentage. This is what replaces 14 hours of analyst spreading."

---

### Part 5 · Real cases (1.5 min)

**Do:** Click Cases → Real cases (18) filter.

**Say:** "Real cases are the everyday mix a credit desk sees: clean approvals, thin collateral, stale valuations, PEP matches, sanctions hits. Each row shows the scenario and the answer the rulebook gives."

**Do:** Point at GS-001, GS-004, GS-007.

**Say:** "GS-001, Oakridge — clean fast path, Senior Credit Manager signs. GS-004, Eastwind — valuation 221 days old, rule allows 180 — approved with conditions, escalated to the Board. GS-007 — director on the sanctions list — the only answer is decline. Same system, three different answers, every one traceable to a specific policy clause."

---

### Part 6 · Corner cases (1.5 min)

**Do:** Click Corner cases (13) filter.

**Say:** "Corner cases are where systems usually break: a number sitting exactly on a threshold, two documents that contradict each other, missing papers."

**Do:** Point at GS-025, GS-014, GS-027.

**Say:** "GS-025 has two different property values in the same file. The system flags the conflict — the rulebook's answer is decline. GS-014 is missing its bank statements — instead of guessing, it drafts a request to the RM and sends the case back. GS-027 is a perfectly clean loan in an unusual layout — the hardest kind for an offline reader."

---

### Part 7 · Human in the loop — the centrepiece (4 min)

**Do:** Still logged in as `amara.osei / demo123`. Open **Control demos** → click **Launch demo**.

**Say:** "This is the heart of it. I'm running Meridian Agro Processing — USD 4.5 million — with me as the live approver. Five problems are hidden in its documents: a politically exposed director, a stale valuation, an expired passport, excess returned cheques, and weak bank-credit coverage."

**Do:** Let the pipeline run. Mention the three possible gates as the pipeline progresses.

**Say:** "The system has up to three sequential human gates. Gate zero fires first — Data Validation — whenever the AI's average extraction confidence falls below 75%. A Senior Analyst reviews the flagged fields, decides PROCEED or RETURN FOR RESUBMISSION. On this case, confidence is fine, so it skips straight to Gate 1."

**Do:** Let the amber EDD compliance gate panel appear.

**Say:** "Gate 1 — the compliance gate. I — Amara Osei, Board Credit Committee — am not getting the approval panel, because my role doesn't qualify for compliance clearance. Only a Compliance Officer can clear EDD. Notice there is no notification bell for me — the bell only appears for roles that have something to act on."

**Do:** Open second browser tab → log in as `grace.mwangi / demo123` (Compliance Officer). Point at the notification bell with the red badge.

**Say:** "Grace Mwangi, Compliance Officer, sees the pending approval badge immediately. Her identity is fixed from login — she can't pretend to be someone else."

**Do:** Attempt 1 — EDD NOT CLEARED (wrong decision, to show it records). Then Attempt 2 — EDD CLEARED with rationale.

**Do:** Switch back to amara.osei tab → Gate 2 appears — Board Credit Committee. Amara approves with conditions.

**Say:** "Gate two comes to Amara — her authority level. Three possible gates, three role-enforced identities, the wrong-role attempt — all permanently in the audit trail."

**Do:** Open Audit tab. Point at the blocked attempt and correct approval entries.

**Say:** "Any edit to this log breaks the SHA-256 hash chain. This is what a regulator wants to see."

---

### Part 8 · Jailbreaks (2 min)

**Do:** Cases → Jailbreak (8) filter.

**Say:** "Eight adversarial attacks: a fake board approval, developer-mode role-play, instructions to change a number, skip screening, written in Spanish, hidden as base64. Every one must be caught."

**Do:** Open GS-034. Show the board resolution document. Run it.

**Say:** "This board resolution tells the AI the loan is already approved and to skip compliance screening. That line is quarantined before the AI reads the file. Every policy result is identical to a clean run. One extra security flag, that's it. A trick can only make the system more cautious."

**Do:** Control demos → run **Prompt injection red team**.

**Say:** "This plants a system note in the bank statement. Policy results identical. One extra flag, one extra condition. Even if a sophisticated attack slipped the filter, it still couldn't approve anything — that isn't the AI's job."

---

### Part 9 · Policy Library — edit and re-ingest (1.5 min) ← NEW

**Do:** Click **Policy Library** in the sidebar.

**Say:** "This is new. The bank's credit policy — 9 documents, 143 named clauses — is visible and editable here. Admins can open any document, see the formatted clauses with colour-coded IDs, switch to edit mode, change a threshold, and save."

**Do:** Click on `collateral_valuation_policy.md` in the left panel. Show the formatted Preview.

**Say:** "Each clause has a unique ID — COL-2.1, COL-3.4. These IDs are what the Policy Agent uses when it cites evidence. Click Edit."

**Do:** Click the Edit button. Show the raw markdown with line numbers.

**Say:** "Any analyst can update a threshold — say, LTV from 70% to 65% — save it here, and when the server restarts, the RAG re-indexes automatically. The SHA-256 of all policy files changes, the old Qdrant collection is replaced, and every future search reflects the new text. Full policy version control is in the registry."

---

### Part 10 · Scorecard, evals and controls (2 min)

**Do:** Click **Evals** → **Run eval (offline mock, ~10 s)**.

**Say:** "This is the release gate. Each column is one eval run. The baseline column — my first version — had recommendation matching policy only 80% of the time, 3 unsafe recommendations. Every one of those is now zero. Self-approval attempts blocked: 42 of 42. Audit chains verified: 39 of 39."

**Do:** Point at the OpenRouter button.

**Say:** "There's now a second button — Run with OpenRouter. That sends the same 39 cases through Claude Sonnet via OpenRouter at roughly 50 cents for the full set, instead of USD 2 for direct Anthropic. Same pipeline, same golden cases, different model budget."

**Do:** Run **Unit tests and release gate** demo.

**Say:** "26 tests on the safety rules. No self-approval, no over-authority, no fail-open, no hidden instructions pass. The six new SC-09 tests cover the data-validation gate: gate fires on low confidence, PROCEED continues, RETURN FOR RESUBMISSION terminates, wrong role is blocked, high confidence skips the gate, audit chain intact. All 26 pass."

---

### Part 11 · Decision Log (0.5 min)

**Do:** Click **Decision Log** in the sidebar.

**Say:** "Every case that went through a human gate appears here — borrower, facility, final status, who decided it, their role, their exact rationale, and the timestamp from the hash-chained audit log. What you see here is read directly from the tamper-protected log — it cannot be edited after the fact."

---

### Part 12 · Architecture, before/after, and POC plan (3 min)

**Do:** Switch to deck — architecture slide.

**Say:** "Seven layers. Channels — portal, email, workbench. Orchestration — durable workflow, pauses for human gates, full replay. The agent pipeline. Model layer — Claude via OpenRouter, in-region, behind a gateway for PII masking, rate limits, cost tracking. Knowledge layer — hybrid vector plus BM25 over 143 policy clauses, Qdrant, auto re-index on policy edit. Systems integration — core banking API, document store. Controls — RBAC, segregation of duties, SHA-256 audit chain."

**Do:** Point at the knowledge layer.

**Say:** "On RAG: we now have full vector search active — OpenRouter embeddings, 1536-dimensional, Qdrant. BM25 handles exact clause IDs like POL-3.1; vector handles semantic queries like 'conditions for a debt service reserve'. Production would add regulatory circulars, product notes, and precedent memos — thousands of documents — on top of the same index."

**Do:** Switch to before/after slide. Keep it on screen for at least 60 seconds.

**Say:** "Before and after — stated assumptions for 2,000 loans a year, 25 analysts at USD 85/hour, 15-20 documents per case."

**Do:** Point at each row.

**Say:** "Cycle time: 22 business days to 9. Missing documents caught on day one, parallel due diligence. Manual touches: 45 to 18. Document review: 14 hours to 4 — analyst verifies instead of re-keys. Credit memo: 10 hours to 3, drafted from extracted facts. Exceptions found before committee: 70% to 95%. SLA adherence: 55% to 85%. Analyst productivity: 6 cases a month to 14."

**Say:** "The value: 17 analyst hours saved per case, 2,000 cases, USD 85 — roughly USD 2.9 million a year in capacity freed. The model cost for a full real case is about USD 1.20 via OpenRouter — one twelve-hundredth of the analyst time it replaces. These are targets. The POC proves or disproves them on the bank's own historical cases."

**Do:** Switch to POC plan slide.

**Say:** "Eight weeks. Week 1: measure the current baseline on 20 live cases. Week 2: replay 20 historical closed cases against the golden set. Weeks 3–5: full pipeline on the bank's own documents. Week 6: shadow mode alongside live cases. Week 7: security hardening and red-team. Week 8: KPI read-out and go/no-go. To start I need: 200 closed loans with documents and decisions, a secure sandbox, and a credit expert to label the golden set."

**Do:** Closing slide.

**Say:** "Everything you've seen — the code, 39 test cases, the portal, the policy library, the RAG vector store, the audit logs, the architecture docs — is in the package I'm sharing. Thank you."

**Do:** Hold two seconds. Stop recording.

---

## Pre-recording checklist

- [ ] Qdrant running (`docker ps` shows qdrant container)
- [ ] `.env.local` has `OPENROUTER_API_KEY` set
- [ ] Server started via `start_web.bat` — RAG badge in sidebar is **green**
- [ ] APP-2026-0201 shows APPROVED WITH CONDITIONS in Cases list
- [ ] Eval mock run completes in ~10s — metrics table appears
- [ ] Login as `newuser / demo123` → applicant portal, no admin screens
- [ ] Login as `amara.osei / demo123` → all tabs visible
- [ ] Policy Library → open `collateral_valuation_policy.md` → Preview loads with coloured clause badges
- [ ] Logged in as `amara.osei` — notification bell is NOT visible (admin-only)
- [ ] Logged in as `admin` account — notification bell IS visible with pending badge if any gate is open
- [ ] No API key, password or notification visible in any screen
- [ ] Do Not Disturb on; email and chat closed

---

## Q&A crib sheet

| Question | Answer |
|---|---|
| Which one — Voyage AI or OpenRouter? | OpenRouter for both LLM and embeddings. Voyage AI was rate-limited on the free tier. OpenRouter routes to `openai/text-embedding-3-small` (1536-dim) for embeddings and Claude Sonnet for the LLM. |
| Why isn't the AI making the decision? | A regulator must trace exactly why a loan was approved. An AI's reasoning can change run-to-run. The AI saves the reading and typing; people keep the decision. |
| How do you know the AI didn't invent a number? | Every number must appear on the line it cites. If the text on that line doesn't contain the value, `citation_verified` is false and the case flags for human review. On the Sunrise demo: 35 of 35 fields verified. |
| What happens when a policy threshold is not met? | If the check is FLAG (curable), the pipeline converts it to a condition and escalates to the appropriate human gate. If FAIL (hard block), the pipeline recommends DECLINE. POL-2.3 on the Sunrise case is an example of a FLAG → Regional Credit Committee escalation. |
| How does re-ingesting policy work? | Edit any `.md` file in the Policy Library, save it. The SHA-256 of all policy files changes → new Qdrant collection name → `_try_init()` auto-indexes all 143 clauses on next start. Old collection is left in Qdrant as an immutable snapshot. |
| What does it cost? | About 7 cents per test case with mock. Roughly USD 0.50 for 39 real cases via OpenRouter. About USD 1.20 for a full real-world case, against ~USD 1,000+ of analyst time. |
| Is the confidence score reliable? | The mock LLM gives 0.97–0.98 by pattern. With a live LLM, confidence comes from the model's self-reported certainty. The citation verification step (comparing extracted value against the quoted text) is the harder, code-enforced check that cannot be faked. |
| You said 100% reliability — is that meaningful? | On the Sunrise demo documents, which were clean and structured: yes. On real messy scans, confidence will be lower and the data-validation HITL gate fires automatically when avg confidence drops below 75% — the pipeline pauses for a Senior Analyst to review before any credit decision is made. |
| Who decides at the data-validation gate? | A Senior Analyst (e.g. Priya Iyer). Their two choices: PROCEED (pipeline continues to Due Diligence) or RETURN FOR RESUBMISSION (pipeline terminates immediately with status RETURNED TO RM — the credit gate never fires). The system enforces this role in code via `validate_human_action`. |
| Why does the spinning icon stop when the pipeline is waiting for approval? | The "Run again" button spins only while the pipeline is actively processing (`sessionStatus === 'running'`). When it's paused at a human gate (`awaiting_approval`), the spinner stops — nothing is processing, so the visual accurately reflects the state. |
| Why isn't Portfolio Monitoring in the demo? | It needs live core banking account feeds for continuous covenant tests. Not available in a prototype. Fully designed in docs: inputs, tools, outputs, autonomy level, and what it's never allowed to do. First agent added in POC Phase 2. |
| Which cloud? | Whatever the bank uses. Mapped to Azure first; AWS and Google alternatives documented in `docs/deployment_mapping.md`. |

---

## Glossary (for non-technical reviewers)

- **Agent** — a small AI helper with one job and a fixed list of tools it can use.
- **Citation** — the exact document and line number a fact came from.
- **Confidence score** — how certain the AI is that it read a value correctly (0–100%).
- **Reliability %** — how many extracted values were confirmed against the source text.
- **RAG (Retrieval-Augmented Generation)** — finding the right policy clause before asking the AI to apply it, so the AI works from the actual rulebook, not memory.
- **BM25** — keyword-based search. Finds exact terms like "POL-3.1".
- **Vector search** — meaning-based search. Finds clauses that are *about* debt service even if they don't use those exact words.
- **Qdrant** — the vector database where the 143 policy clauses are stored as embeddings.
- **Segregation of duties** — the person who prepares a case cannot also approve it.
- **Delegated authority** — bigger loans need more senior approvers.
- **FLAG** — a policy check that is not a hard block but is curable; converted into a condition and escalated.
- **FAIL** — a hard policy block; pipeline recommends DECLINE.
- **DSRA** — Debt Service Reserve Account; a cash buffer held by the borrower.
- **DSCR** — Debt Service Coverage Ratio; how many times EBITDA covers loan repayments.
- **LTV** — Loan-to-Value; loan amount divided by collateral value.
- **Golden set** — 39 test cases where the correct answer is known in advance, worked from the rulebook, not the code.
- **Hash-chained audit log** — every log entry is sealed to the previous one; editing any entry breaks all later seals.
