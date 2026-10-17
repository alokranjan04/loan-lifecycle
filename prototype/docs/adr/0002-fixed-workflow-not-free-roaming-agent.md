# ADR 0002: A fixed workflow with agents inside steps, not a free-roaming agent

**Status:** accepted · **Date:** 2026-10-16

## Context
A single planner agent with every tool could, in principle, run the whole lifecycle. In lending that creates three problems: the path a case took cannot be stated in advance, so it cannot be validated; a case waits days for humans, which a running agent loop handles badly; and an agent that can call any tool can skip a gate.

## Decision
The regulated path is a fixed state machine in `orchestrator.py`: intake, document intelligence, completeness, due diligence, policy, risk, recommendation, human gates, disbursement. Each agent has one job, a typed input and output, and only the tools that job needs. Freedom exists only inside a step (for example, how to read an unusual layout). Human gates sit outside every agent and cannot be called by one.

In production the state machine runs on a durable workflow engine (Azure Durable Functions or Logic Apps; Temporal, AWS Step Functions or Google Workflows as alternatives) so a case can wait on a human task without a live process and every transition is replayable.

## Consequences
- Every case follows a path that can be drawn, tested and audited; `audit_log.jsonl` records each step with inputs hash, outputs, policy references and model version.
- New capability is added as a new step or a better agent inside a step, not as a new prompt instruction to a planner.
- We lose some flexibility on genuinely novel cases. Those are returned to the RM or an analyst by design, which is what a bank wants.
