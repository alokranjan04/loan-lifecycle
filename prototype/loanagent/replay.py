"""Replay: reproduce a past decision exactly.

A decision record names the policy version it used and keeps every extracted field. Replay reloads
that policy version (checking its hash has not changed), feeds the recorded fields back in place of the
model, re-runs the deterministic rules and the recorded human decisions, and compares the results with
what was recorded. Model output is not re-generated: what is reproduced is everything the bank's
model risk team validates (ratios, policy checks, rating, routing).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .knowledge import PolicyKnowledgeBase
from .llm import LLMStats, TEMPLATES
from .models import Evidence, ExtractedField

ROOT = Path(__file__).resolve().parent.parent


class ReplayLLM:
    """Returns the fields recorded in extracted_fields.json instead of calling a model."""
    PROMPT_VERSION = "replay"

    def __init__(self, extracted: dict, recorded_model: str):
        self.extracted = extracted
        self.name = f"replay of {recorded_model}"
        self.model = "replay"
        self.stats = LLMStats()

    def cost_usd(self) -> float:
        return 0.0

    def extract(self, doc_name, doc_type, lines, schema):
        out = {}
        for name, f in self.extracted.get(doc_type, {}).items():
            ev = f["evidence"]
            out[name] = ExtractedField(name, f["value"], Evidence(ev["source"], ev["line"], ev["quote"]), f["confidence"])
        return out

    def write(self, task, context):
        return TEMPLATES[task](context)


class _Approver:
    def __init__(self, decisions):
        self.by_gate = {d["gate"]: d for d in decisions}

    def ask(self, gate, case, attempt):
        d = self.by_gate[gate["gate"]]
        return {k: d[k] for k in ("name", "role", "decision", "rationale")}


def replay(case_dir: Path, app_dir: Path, watchlist_path: Path | None = None) -> dict:
    from .orchestrator import run_case      # local import: orchestrator imports this package too
    rec = json.loads((case_dir / "decision_record.json").read_text())
    extracted = json.loads((case_dir / "extracted_fields.json").read_text())
    pol = rec["policy"]
    kb = PolicyKnowledgeBase.for_date(ROOT / "data" / "policy", rec["as_of"], pol["version"])
    out = Path(tempfile.mkdtemp())
    if watchlist_path is None:      # replay the screening results recorded at the time, not today's lists
        watchlist_path = out / "recorded_screening.json"
        watchlist_path.write_text(json.dumps(rec.get("screening", {})))
    case = run_case(app_dir, _Approver(rec["human_decisions"]), out, as_of=rec["as_of"], verbose=False,
                    policy_version=pol["version"], llm=ReplayLLM(extracted, rec["controls"]["model"]),
                    watchlist_path=watchlist_path)
    now = {c.rule_id: (c.status, c.actual) for c in case.policy_checks}
    then = {c["rule_id"]: (c["status"], c["actual"]) for c in rec["policy_checks"]}
    diffs = [k for k in sorted(set(now) | set(then)) if now.get(k) != then.get(k)]
    return {
        "case_id": rec["case_id"], "as_of": rec["as_of"], "policy_version": pol["version"],
        "policy_hash_matches": kb.sha256 == pol["sha256"],
        "checks_reproduced": f"{len(then) - len(diffs)}/{len(then)}", "check_differences": diffs,
        "recommendation_reproduced": case.recommendation["action"] == rec["recommendation"]["action"],
        "routing_reproduced": case.recommendation["authority"] == rec["recommendation"]["authority"],
        "rating_reproduced": case.risk["rating"] == rec["risk"]["rating"],
        "final_status_reproduced": case.checklist["final_status"] == rec["final_status"],
    }
