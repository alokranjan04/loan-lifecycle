# Agentic workbench service

The Northstar administrator portal embeds this workbench for agentic document analysis, KYC/due diligence, policy checks, risk analysis, human gates, audit/replay, evaluations, and control demos. A cited policy Q&A assistant uses the policy retrieval layer.

## Start (Windows)

Start the Northstar portal first. Then, from the `prototype` folder, run `start_web.bat`, or:

```bat
cd "C:\Users\Alok Ranjan\Documents\loan-lifecycle\prototype"
python -m pip install -r web\requirements.txt
python -m uvicorn web.app:app --host 127.0.0.1 --port 8001
```

Open http://127.0.0.1:8000 and sign in as an administrator. The workbench service is loopback-only on port 8001, and its API validates the Northstar administrator session. For an AI provider, set the key in the same window before starting (never commit it):

```bat
set ANTHROPIC_API_KEY=your-key-here
python -m uvicorn web.app:app --host 127.0.0.1 --port 8001
```

## Screens

- **Home**: what the system does, the latest real-model eval headline, the golden set by category (real, corner, jailbreak) with per-category scores, and links into everything below.
- **Cases**: the 2 sample applications and the 39 golden cases, grouped as Real cases (18), Corner cases (13) and Jailbreak scenarios (8). Golden rows show the policy answer next to the system's result.
- **Case**: run the agents with "I decide at each gate" (you approve in the browser; try approving as the case's analyst or too junior a role to see the controls block it) or "Recorded approvers". Tabs show policy checks with clause text and clickable source lines, extracted fields with verified citations, findings and conditions, human decisions and blocked attempts, the documents, the hash-chained audit trail and the credit memo. Golden cases also show the comparison with ground truth.
- **Evals**: runs `evals/run_evals.py` and rebuilds the report; compares every saved run side by side, overall and by category.
- **Control demos**: prompt-injection red team, policy change v3.2 to v3.3, tamper-evident audit log, decision replay, and the unit tests.
- **Policy Assistant**: asks policy questions against retrieved clauses, displays clause citations and source lines, and refuses to answer when no relevant clause is found.

The interface assets are served locally. When no model provider key is configured, the workflow uses its deterministic offline mock; the policy assistant still retrieves and displays source clauses.

## Approver identity

The name and role on a human decision come from the signed-in portal session, not from the browser. `data/approver_assignments.json` (not committed; see `approver_assignments.example.json`) maps each portal account email to its approver roles, and an account with no entry cannot decide at any gate. Set `LOAN_APPROVER_ASSIGNMENTS` to use a different file. The audit log records the authenticated account on each decision and marks scripted approvals as `recorded`. Recorded approvers are refused for applications submitted through the web portal.
