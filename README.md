# Agentic Loan Lifecycle Management (USTech Assignment 1)

The model reads and writes, code computes and applies policy, people decide. And the prototype is measured: a 39-case golden set (real cases, corner cases and jailbreak scenarios) is the release gate.

| File | What it is |
|---|---|
| [SOLUTION.md](SOLUTION.md) | The write-up: lifecycle map and priorities, agent ecosystem, prototype walkthrough, evidence, architecture, before vs. after with assumptions, 8-week POC plan, demo script |
| [prototype/](prototype/) | Runnable Python prototype: application through to human approval and an auditable decision summary |
| [prototype/evals/results/REPORT.md](prototype/evals/results/REPORT.md) | Golden-set results: before and after the eval-driven fixes |
| [prototype/docs/](prototype/docs/) | Decision records (ADRs), model risk pack, first two weeks on site, deployment mapping, unit economics |
| [prototype/output/](prototype/output/) | Outputs from the last run (decision summaries, audit logs, traces, CP trackers, red-team and policy-change runs) |

## Quick start

```bash
cd prototype
python run_demo.py                                    # both sample cases, offline, scripted approvers
python workbench/serve.py                             # reviewer workbench at http://localhost:8765
python evals/run_evals.py --report                    # golden set (39 cases) -> evals/results/REPORT.md
python run_demo.py --redteam-demo                     # prompt injection is quarantined; results unchanged
python run_demo.py --policy-change-demo               # LTV limit cut in v3.3; old decision still replays
python run_demo.py --replay output/APP-2026-0157      # re-run a recorded decision and compare
python run_demo.py --tamper-demo                      # the audit log detects an edited approval
python run_demo.py --app APP-2026-0142 --interactive  # you are the compliance officer and the approver
python -m unittest discover -s tests                  # 20 tests, including the golden-set release gate
```

With a key, Claude does the extraction and drafting. On the golden set Claude Opus 5.5 matched the policy on 30 of 30 cases at USD 0.073 per case (run before GS-031 to GS-039 were added) (see REPORT.md, including the first run that found 3 issues in our checks):

```bash
ANTHROPIC_API_KEY=sk-... python run_demo.py --llm claude
ANTHROPIC_API_KEY=sk-... python evals/run_evals.py --llm claude --label claude-opus-5-5 --report
```

Python 3.10+, standard library only. `LOAN_AGENT_MODEL` chooses the Claude model (default `claude-opus-5-5`) and `LOAN_AGENT_EFFORT` the effort level (default `medium`).

## Prototype layout

```
prototype/
  run_demo.py                 CLI entry point (demo, red-team, policy change, replay, tamper)
  loanagent/
    agents.py                 the agent classes and document schemas
    orchestrator.py           case state machine, human gates, SoD / authority / override controls
    llm.py                    model layer: MockLLM (offline) and ClaudeLLM (Messages API)
    citations.py              checks each extracted value is on the line it cites
    knowledge.py              versioned policy: clause lookup, BM25, parameters, effective dates
    security.py               PII tokenisation and prompt-injection quarantine before any model call
    replay.py                 deterministic replay of a recorded decision
    audit.py                  hash-chained audit log, verification, tracing
    report.py                 decision summary and decision record
  workbench/                  reviewer workbench (serve.py + index.html, standard library)
  evals/
    generate_cases.py         builds the 39-case golden set with independently computed answers
    golden/README.md          readable index of the 39 cases by category (make_golden_index.py)
    run_evals.py              scores a run and writes REPORT.md
    results/                  recorded runs: baseline-mock, mock-before-screen-fix, mock, and two Claude Opus 5.5 runs
  docs/
    adr/                      five architecture decision records
    model_risk_pack.md        what MRM validates vs. monitors, agent cards, change control
    first_two_weeks.md        stakeholders, 20-case replay, kill criteria
    deployment_mapping.md     Azure primary, AWS and GCP alternatives
    unit_economics.md         model calls and cost per case vs. analyst time
  data/
    policy/                   credit policy v3.2 and v3.3, registry.json with versions and parameters
    applications/             two fictional applications with supporting documents
    screening_watchlist.json  stand-in for a sanctions / PEP / adverse media API
    demo_approvals.json       scripted human decisions (includes deliberately invalid attempts)
  tests/                      test_workflow.py, test_evidence.py
```

All borrowers, people, documents and the policy are fictional.
