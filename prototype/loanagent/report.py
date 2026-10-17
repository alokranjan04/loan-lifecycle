"""Builds the auditable decision summary and the machine-readable decision record."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .models import SEVERITY_ORDER, CaseFile

ICON = {"PASS": "PASS", "FLAG": "FLAG", "FAIL": "FAIL"}


def _fmt_metric(k: str, v) -> str:
    if k in ("ltv", "bank_credit_to_revenue", "promoter_share"):
        return f"{v:.1%}"
    if k in ("debt_ebitda_post", "dscr_hist", "dscr_proj", "current_ratio"):
        return f"{v:.2f}x"
    if k == "vintage_years":
        return f"{v:.1f} years"
    if k == "group_exposure_post":
        return f"USD {v:,.0f}"
    return str(v)


METRIC_LABELS = {
    "vintage_years": ("Business vintage", "application.json"),
    "debt_ebitda_post": ("Debt / EBITDA after facility", "financials"),
    "dscr_hist": ("Historical DSCR (FY2025)", "financials"),
    "dscr_proj": ("Projected DSCR", "project_report"),
    "current_ratio": ("Current ratio", "financials"),
    "ltv": ("Loan to value", "valuation"),
    "promoter_share": ("Promoter contribution", "project_report"),
    "bank_credit_to_revenue": ("Bank credits / revenue", "bank_statement"),
    "group_exposure_post": ("Group exposure after facility", "application.json"),
    "valuation_age_days": ("Valuation age (days)", "valuation"),
}


def build_summary(case: CaseFile, llm, kb, vault, audit_head: str, trace) -> str:
    a = case.application
    b, f = a["borrower"], a["facility"]
    r, rec = case.risk, case.recommendation
    L = []
    L += [f"# Credit Decision Summary: {case.app_id}", "",
          f"**Borrower:** {b['legal_name']} ({b['sector']}, {b['country']})  ",
          f"**Facility:** {f['type']}, USD {f['amount_usd']:,.0f}, {f['tenor_months']} months, {f['proposed_rate']}  ",
          f"**Purpose:** {f['purpose']}  ",
          f"**Decision date:** {case.as_of} · **RM:** {a.get('relationship_manager')} · **Analyst:** {a.get('credit_analyst')}", "",
          f"## Final decision: {case.checklist.get('final_status')}", ""]
    L += ["| Gate | Required role | Decided by | Decision | Override | Rationale |", "|---|---|---|---|---|---|"]
    for h in case.human_decisions:
        L.append(f"| {h['gate']} | {h['required_role']} | {h['name']} ({h['role']}) | {h['decision']} | "
                 f"{'yes' if h['override'] else 'no'} | {h['rationale'] or '-'} |")
    L += ["", f"Disbursement status: **{case.checklist.get('disbursement_status', 'n/a')}**", ""]

    L += ["## System recommendation (decision support only)", "",
          f"**{rec['action']}**. {rec['reason']}", "", rec["summary"], ""]

    L += ["## Key metrics", "", "| Metric | Value | Source |", "|---|---|---|"]
    for k, (label, src) in METRIC_LABELS.items():
        if k in case.metrics:
            L.append(f"| {label} | {_fmt_metric(k, case.metrics[k])} | {src} |")
    L += ["", f"Internal rating **{r['rating']} ({r['grade']})**, scorecard {r['score']}/{r['max_score']}, "
          f"indicative 1-year PD {r['pd_1y']:.2%}.", "",
          "| Scorecard factor | Points (0 best) |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in r["scorecard"].items()]

    L += ["", "## Policy and eligibility checks", "", f"Credit policy **{kb.version}** (effective {kb.effective_from}, sha256 `{kb.sha256[:16]}`); clause text retrieved and cited per check.", "",
          "| Clause | Check | Result | Actual | Requirement | Evidence |", "|---|---|---|---|---|---|"]
    for c in case.policy_checks:
        ev = " ".join(e.cite() for e in c.evidence)
        L.append(f"| {c.ref} | {c.name} | **{ICON.get(c.status, c.status)}** | {c.actual} | {c.threshold} | {ev} |")

    L += ["", "## Risk observations", "", r["narrative"], ""]

    if case.conditions:
        L += ["## Conditions", "", "| ID | Condition | Stage | Owner | Due | Basis |", "|---|---|---|---|---|---|"]
        L += [f"| {c.id} | {c.text} | {c.stage} | {c.owner} | {c.due} | {c.source_ref} |" for c in case.conditions]
        L.append("")

    if case.checklist.get("missing"):
        L += ["## Missing information", ""]
        L += [f"- {m['title']} ({m['policy_ref']}){' **blocking**' if m['blocking'] else ''}" for m in case.checklist["missing"]]
        L += ["", "Request drafted to the RM: see `rm_request.txt`.", ""]

    L += ["## Documents and extracted evidence", "", "| Document | Type | Fields extracted |", "|---|---|---|"]
    for name, d in case.documents.items():
        n = len(case.extracted.get(d["type"], {}))
        L.append(f"| {name} | {d['type']} | {n} |")
    L += ["", "Every extracted field with its line citation is in `extracted_fields.json`.", ""]

    L += ["## Controls and audit", "",
          f"- Model: {llm.name}. The model extracted fields and drafted text; ratios, policy checks, rating and routing are deterministic code.",
          f"- PII masked before any model call: {vault.total} identifiers tokenised.",
          f"- Segregation of duties and delegated authority enforced on every human action "
          f"({sum(1 for _ in [h for h in case.human_decisions])} accepted, "
          f"{case.checklist.get('blocked_attempts', 0)} blocked).",
          f"- Audit log: hash-chained, `audit_log.jsonl`. Head at issue: `{audit_head}`.",
          f"- Trace `{trace.trace_id}`: {len(trace.spans)} agent spans, {llm.stats.calls} model calls, "
          f"{llm.stats.input_tokens + llm.stats.output_tokens} tokens.",
          "- Verify with: `python run_demo.py --verify output/" + case.app_id + "/audit_log.jsonl`", ""]
    return "\n".join(L)


def write_outputs(case: CaseFile, out: Path, audit, tracer, llm, kb, vault):
    case.checklist["blocked_attempts"] = sum(1 for e in audit.entries if e["action"] == "human_action_blocked")
    summary = build_summary(case, llm, kb, vault, audit.head, tracer)
    (out / "decision_summary.md").write_text(summary, encoding="utf-8")
    if case.rm_request:
        (out / "rm_request.txt").write_text(case.rm_request)
    elif (out / "rm_request.txt").exists():
        (out / "rm_request.txt").unlink()
    (out / "extracted_fields.json").write_text(json.dumps(
        {dt: {k: asdict(v) for k, v in fs.items()} for dt, fs in case.extracted.items()}, indent=2, default=str))
    (out / "conditions_tracker.json").write_text(json.dumps(
        {"case_id": case.app_id, "disbursement_status": case.checklist.get("disbursement_status"),
         "conditions": [asdict(c) for c in case.conditions]}, indent=2))
    record = {
        "case_id": case.app_id, "as_of": case.as_of, "final_status": case.checklist.get("final_status"),
        "recommendation": case.recommendation, "human_decisions": case.human_decisions,
        "application": case.application,
        "risk": {k: v for k, v in case.risk.items() if k != "narrative"},
        "metrics": {k: v for k, v in case.metrics.items() if isinstance(v, (int, float, str))},
        "screening": case.metrics.get("screening", {}),
        "policy_checks": [asdict(c) for c in case.policy_checks],
        "findings": sorted([x.to_dict() for x in case.findings], key=lambda x: -SEVERITY_ORDER[x["severity"]]),
        "conditions": [asdict(c) for c in case.conditions],
        "gates": case.checklist.get("gates", []), "security_flags": case.checklist.get("security_flags", []),
        "policy": {"version": kb.version, "effective_from": kb.effective_from, "sha256": kb.sha256},
        "controls": {"model": llm.name, "prompt_version": llm.PROMPT_VERSION, "policy_kb": kb.version, "pii_tokens_masked": vault.total,
                     "audit_head": audit.head, "trace_id": tracer.trace_id, **llm.stats.snapshot()},
    }
    (out / "decision_record.json").write_text(json.dumps(record, indent=2, default=str))
    digest = hashlib.sha256(summary.encode()).hexdigest()
    audit.record("system", "system", "decision_summary_issued", None,
                 {"file": "decision_summary.md", "sha256": digest})


def write_pending(case: CaseFile, out: Path, llm, kb, vault):
    """State of a case waiting at its first human gate, for the reviewer workbench."""
    (out / "extracted_fields.json").write_text(json.dumps(
        {dt: {k: asdict(v) for k, v in fs.items()} for dt, fs in case.extracted.items()}, indent=2, default=str))
    record = {
        "case_id": case.app_id, "as_of": case.as_of, "final_status": None, "pending": True,
        "application": case.application, "recommendation": case.recommendation, "gates": case.checklist["gates"],
        "risk": case.risk, "metrics": {k: v for k, v in case.metrics.items() if isinstance(v, (int, float, str))},
        "policy": {"version": kb.version, "effective_from": kb.effective_from, "sha256": kb.sha256},
        "policy_checks": [asdict(c) for c in case.policy_checks],
        "findings": sorted([x.to_dict() for x in case.findings], key=lambda x: -SEVERITY_ORDER[x["severity"]]),
        "conditions": [asdict(c) for c in case.conditions], "missing": case.checklist.get("missing", []),
        "security_flags": case.checklist.get("security_flags", []), "rm_request": case.rm_request,
        "controls": {"model": llm.name, "pii_tokens_masked": vault.total, **llm.stats.snapshot()},
    }
    (out / "pending_record.json").write_text(json.dumps(record, indent=2, default=str))
