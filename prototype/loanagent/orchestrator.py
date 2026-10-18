"""Orchestration: runs the agents in order as a state machine, enforces the human gates and writes
the audit trail. Each step is a node; in production the same graph runs on a durable workflow
engine (Temporal / Step Functions / LangGraph with a checkpointer) so a case can wait days for a
human without holding a process open.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .agents import (AUTHORITY_RANK, ApprovalWorkflowAgent, CompletenessAgent, DisbursementConditionAgent,
                     DocumentIntelligenceAgent, DueDiligenceAgent, IntakeAgent, PolicyEligibilityAgent, RiskAgent)
from .audit import AuditLog, Tracer, verify_chain
from .knowledge import PolicyKnowledgeBase
from .rag import get_knowledge_base
from .llm import get_llm
from .models import CaseFile
from .report import write_outputs, write_pending
from .security import PIIVault

ROOT = Path(__file__).resolve().parent.parent
CREDIT_DECISIONS = ["APPROVE WITH CONDITIONS", "APPROVE", "DECLINE", "RETURN TO RM"]
COMPLIANCE_DECISIONS = ["EDD CLEARED", "EDD NOT CLEARED"]


class Context:
    def __init__(self, llm, kb):
        self.llm, self.kb = llm, kb


class ControlViolation(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# Human gates
# ---------------------------------------------------------------------------------------------
class InteractiveApprover:
    """Terminal prompt. Stands in for the approval screen in the loan origination system."""

    def ask(self, gate: dict, case: CaseFile, attempt: int) -> dict:
        options = COMPLIANCE_DECISIONS if gate["gate"] == "compliance" else CREDIT_DECISIONS
        print(f"\n=== HUMAN GATE: {gate['role']} ===  ({gate['reason']})")
        if gate["gate"] == "credit":
            print(f"System recommendation: {case.recommendation['action']}  ({case.recommendation['reason']})")
        else:
            for h in case.metrics.get("screening", {}).get("pep", []):
                print(f"PEP match: {h['name']}: {h['detail']} (match score {h.get('match_score', 'n/a')})")
        name = input("Your name: ").strip()
        role = input(f"Your role [{gate['role']}]: ").strip() or gate["role"]
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}")
        choice = input("Decision number: ").strip()
        decision = options[int(choice) - 1] if choice.isdigit() and 0 < int(choice) <= len(options) else options[0]
        rationale = input("Rationale (required if you differ from the recommendation): ").strip()
        return {"name": name, "role": role, "decision": decision, "rationale": rationale}


class ScriptedApprover:
    """Pre-recorded human responses, for demos and tests. Each gate takes a list of attempts."""

    def __init__(self, script: dict[str, list[dict]]):
        self.script = script

    def ask(self, gate: dict, case: CaseFile, attempt: int) -> dict:
        attempts = self.script.get(gate["gate"], [])
        if attempt >= len(attempts):
            raise ControlViolation(f"No valid human response scripted for the {gate['gate']} gate")
        return attempts[attempt]


def validate_human_action(gate: dict, action: dict, case: CaseFile) -> list[str]:
    """Controls applied to every human decision: segregation of duties, authority, override rationale."""
    errors = []
    app = case.application
    conflicted = {app.get("credit_analyst", "").lower(), app.get("relationship_manager", "").lower()}
    if not action.get("name"):
        errors.append("approver name is required")
    elif action["name"].lower() in conflicted:
        errors.append(f"segregation of duties: {action['name']} prepared or sponsored this proposal (POL-6.2)")
    if gate["gate"] == "credit":
        if AUTHORITY_RANK.get(action.get("role"), 0) < AUTHORITY_RANK[gate["role"]]:
            errors.append(f"insufficient authority: {action.get('role')} cannot approve; requires {gate['role']} (POL-6.1)")
        if action.get("decision") != case.recommendation["action"] and len(action.get("rationale", "")) < 20:
            errors.append("override of the system recommendation needs a written rationale of at least 20 characters (POL-6.2)")
    elif action.get("role") != "Compliance Officer":
        errors.append("EDD sign-off must come from a Compliance Officer (POL-3.3)")
    return errors


# ---------------------------------------------------------------------------------------------
def run_case(app_dir: Path, approver, out_root: Path, as_of: str | None = None, llm_mode: str = "auto",
             watchlist_path: Path | None = None, verbose: bool = True, policy_version: str | None = None,
             llm=None, prepare_only: bool = False) -> CaseFile:
    say = print if verbose else (lambda *a, **k: None)
    application = json.loads((app_dir / "application.json").read_text())
    case = CaseFile(application, as_of or date.today().isoformat())
    out = out_root / case.app_id
    out.mkdir(parents=True, exist_ok=True)

    llm = llm or get_llm(llm_mode)
    kb = get_knowledge_base(ROOT / "data" / "policy", case.as_of, policy_version)
    ctx = Context(llm, kb)
    audit = AuditLog(out / "audit_log.jsonl", case.app_id)
    tracer = Tracer(out / "trace.jsonl", llm)
    vault = PIIVault()
    watchlist = json.loads((watchlist_path or ROOT / "data" / "screening_watchlist.json").read_text())

    audit.record("system", "system", "case_opened", application,
                 {"as_of": case.as_of, "model": llm.name, "prompt_version": llm.PROMPT_VERSION, "policy_version": kb.version,
                  "policy_effective_from": kb.effective_from, "policy_sha256": kb.sha256}, model=llm.name)
    say(f"\n>>> {case.app_id}  {application['borrower']['legal_name']}  "
        f"USD {application['facility']['amount_usd']:,.0f}   [model: {llm.name}, policy {kb.version}]")

    def step(agent, *args, refs=None):
        with tracer.span(agent.name) as sp:
            result = agent.run(case, *args)
            sp.attrs["findings_total"] = len(case.findings)
        audit.record(agent.name, "agent", type(agent).__name__, {"app": case.app_id, "args": [str(a) for a in args]},
                     result, policy_refs=(refs() if callable(refs) else refs) or [f.policy_ref for f in case.findings if f.policy_ref and f.agent == agent.name],
                     model=llm.name)
        say(f"  [{agent.name}] " + json.dumps(result, default=str)[:180])
        return result

    step(IntakeAgent(ctx))
    step(DocumentIntelligenceAgent(ctx), app_dir / "documents", vault)
    step(CompletenessAgent(ctx))
    step(DueDiligenceAgent(ctx), watchlist)
    step(PolicyEligibilityAgent(ctx), refs=lambda: [c.rule_id for c in case.policy_checks])
    step(RiskAgent(ctx))
    step(ApprovalWorkflowAgent(ctx), refs=["POL-6.1", "POL-6.2", "POL-7.1"])

    say(f"\n  Recommendation: {case.recommendation['action']}: {case.recommendation['reason']}")
    say(f"  Rating {case.risk['rating']} ({case.risk['grade']}), {len(case.conditions)} conditions, "
        f"gates: {' -> '.join(g['role'] for g in case.checklist['gates'])}")

    if prepare_only:   # stop at the first human gate: the reviewer workbench shows this state
        write_pending(case, out, llm, kb, vault)
        return case

    # Human gates, in order. Nothing past this point happens without a person.
    final = None
    for gate in case.checklist["gates"]:
        attempt = 0
        while True:
            action = approver.ask(gate, case, attempt)
            errors = validate_human_action(gate, action, case)
            if not errors:
                break
            audit.record("control", "system", "human_action_blocked", action,
                         {"gate": gate["gate"], "attempted_by": action.get("name"), "errors": errors},
                         policy_refs=["POL-6.1", "POL-6.2"])
            say(f"  [CONTROL] blocked {action.get('name')} at {gate['gate']} gate: {'; '.join(errors)}")
            attempt += 1
            if attempt >= 3:
                raise ControlViolation("Too many invalid approval attempts")
        override = gate["gate"] == "credit" and action["decision"] != case.recommendation["action"]
        rec = {**action, "gate": gate["gate"], "required_role": gate["role"], "override": override}
        case.human_decisions.append(rec)
        audit.record(action["name"], "human", f"{gate['gate']}_decision", {"gate": gate},
                     {"decision": action["decision"], "rationale": action["rationale"], "override": override},
                     policy_refs=["POL-3.3"] if gate["gate"] == "compliance" else ["POL-6.1", "POL-6.2"])
        say(f"  [HUMAN] {action['name']} ({action['role']}): {action['decision']}" + ("  (OVERRIDE)" if override else ""))
        if gate["gate"] == "compliance" and action["decision"] == "EDD NOT CLEARED":
            final = "DECLINED (compliance)"
            break
    if final is None:
        final = {"APPROVE": "APPROVED", "APPROVE WITH CONDITIONS": "APPROVED WITH CONDITIONS",
                 "DECLINE": "DECLINED", "RETURN TO RM": "RETURNED TO RM"}[case.human_decisions[-1]["decision"]]
    case.checklist["final_status"] = final

    step(DisbursementConditionAgent(ctx))
    audit.record("system", "system", "case_decided", {"final": final},
                 {"final_status": final, "pii_tokens_masked": vault.total, **llm.stats.snapshot()})
    write_outputs(case, out, audit, tracer, llm, kb, vault)
    ok, msg = verify_chain(out / "audit_log.jsonl")
    case.checklist["audit_verification"] = msg if ok else f"FAILED: {msg}"
    say(f"\n  FINAL: {final}.  Audit chain: {case.checklist['audit_verification']}")
    say(f"  Outputs in {out}")
    return case
