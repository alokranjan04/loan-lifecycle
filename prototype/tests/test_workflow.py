"""Run with: python -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loanagent.audit import verify_chain                      # noqa: E402
from loanagent.llm import ClaudeLLM                           # noqa: E402
from loanagent.orchestrator import ControlViolation, ScriptedApprover, run_case  # noqa: E402
from loanagent.security import PIIVault                       # noqa: E402

APPS = ROOT / "data" / "applications"
SCRIPT = json.loads((ROOT / "data" / "demo_approvals.json").read_text())


def run(app, script, **kw):
    out = Path(tempfile.mkdtemp())
    case = run_case(APPS / app, ScriptedApprover(script), out, as_of="2026-10-16", llm_mode="mock", verbose=False, **kw)
    return case, out / app


class WorkflowTests(unittest.TestCase):
    def test_flagged_case_end_to_end(self):
        case, out = run("APP-2026-0142", SCRIPT["APP-2026-0142"])
        checks = {c.rule_id: c.status for c in case.policy_checks}
        self.assertEqual(checks["POL-3.1"], "FAIL")      # stale valuation
        self.assertEqual(checks["POL-3.2"], "FAIL")      # expired UBO passport
        self.assertEqual(checks["POL-3.3"], "FLAG")      # PEP
        self.assertEqual(checks["POL-5.1"], "FLAG")      # 3 returned items
        self.assertEqual(checks["POL-5.2"], "FLAG")      # 73% bank credits / revenue
        self.assertEqual(case.recommendation["action"], "APPROVE WITH CONDITIONS")
        self.assertEqual([g["gate"] for g in case.checklist["gates"]], ["compliance", "credit"])
        self.assertEqual(case.checklist["final_status"], "APPROVED WITH CONDITIONS")
        self.assertTrue(case.checklist["disbursement_status"].startswith("BLOCKED"))
        for f in ("decision_summary.md", "decision_record.json", "audit_log.jsonl", "trace.jsonl",
                  "rm_request.txt", "extracted_fields.json", "conditions_tracker.json"):
            self.assertTrue((out / f).exists(), f)
        self.assertTrue(verify_chain(out / "audit_log.jsonl")[0])

    def test_clean_case_approves(self):
        case, _ = run("APP-2026-0157", SCRIPT["APP-2026-0157"])
        self.assertEqual(case.recommendation["action"], "APPROVE")
        self.assertEqual(case.recommendation["authority"], "Senior Credit Manager")
        self.assertEqual(case.checklist["disbursement_status"], "READY FOR DISBURSEMENT")

    def test_every_extracted_field_has_a_line_citation(self):
        case, _ = run("APP-2026-0157", SCRIPT["APP-2026-0157"])
        for fields in case.extracted.values():
            for f in fields.values():
                self.assertIsNotNone(f.evidence.line, f.name)

    def test_analyst_cannot_approve_own_case(self):
        bad = [{"name": "Daniel Okafor", "role": "Board Credit Committee", "decision": "APPROVE", "rationale": "x"}]
        with self.assertRaises(ControlViolation):
            run("APP-2026-0157", {"credit": bad})

    def test_override_requires_rationale(self):
        s = {"credit": [{"name": "Kenji Watanabe", "role": "Senior Credit Manager", "decision": "DECLINE", "rationale": "no"},
                        {"name": "Kenji Watanabe", "role": "Senior Credit Manager", "decision": "DECLINE",
                         "rationale": "Customer concentration on two OEMs is too high for this tenor."}]}
        case, out = run("APP-2026-0157", s)
        self.assertTrue(case.human_decisions[-1]["override"])
        self.assertEqual(case.checklist["final_status"], "DECLINED")
        blocked = [json.loads(l) for l in (out / "audit_log.jsonl").read_text().splitlines()
                   if json.loads(l)["action"] == "human_action_blocked"]
        self.assertEqual(len(blocked), 1)

    def test_sanctions_match_declines(self):
        wl = Path(tempfile.mkdtemp()) / "wl.json"
        wl.write_text(json.dumps({"sanctions": [{"name": "Tomas Reyes", "list": "test"}]}))
        s = {"credit": [{"name": "Kenji Watanabe", "role": "Senior Credit Manager", "decision": "DECLINE", "rationale": ""}]}
        case, _ = run("APP-2026-0157", s, watchlist_path=wl)
        self.assertEqual(case.recommendation["action"], "DECLINE")

    def test_tampering_is_detected(self):
        _, out = run("APP-2026-0157", SCRIPT["APP-2026-0157"])
        log = out / "audit_log.jsonl"
        lines = log.read_text().splitlines()
        e = json.loads(lines[3]); e["outputs"] = {"edited": True}; lines[3] = json.dumps(e)
        log.write_text("\n".join(lines) + "\n")
        self.assertFalse(verify_chain(log)[0])

    def test_pii_masked_and_restored(self):
        v = PIIVault()
        masked = v.mask("ID: Passport Z4471893 | account 50200048813327")
        self.assertNotIn("Z4471893", masked)
        self.assertNotIn("50200048813327", masked)
        self.assertEqual(v.unmask(masked), "ID: Passport Z4471893 | account 50200048813327")

    def test_claude_extraction_parsing(self):
        llm = ClaudeLLM.__new__(ClaudeLLM)
        llm.stats = type("S", (), {"calls": 0})()
        llm._call = lambda system, prompt, max_tokens=2000, **kw: 'Here: {"valuation_date": {"value": "2026-02-10", "line": 2, "confidence": 0.95}, "bogus": {"value": 1}}'
        out = llm.extract("v.txt", "valuation", ["VALUATION REPORT", "Valuation date: 2026-02-10"],
                          [{"name": "valuation_date", "type": "str", "description": "date"}])
        self.assertEqual(out["valuation_date"].value, "2026-02-10")
        self.assertEqual(out["valuation_date"].evidence.quote, "Valuation date: 2026-02-10")
        self.assertNotIn("bogus", out)


if __name__ == "__main__":
    unittest.main()
