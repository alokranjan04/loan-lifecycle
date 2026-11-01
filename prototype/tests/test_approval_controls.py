"""Approver identity, valid decisions and the OpenRouter extraction path."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# web.app loads .env files for any key not already set; keep these tests offline.
for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "QDRANT_API_KEY"):
    os.environ[key] = ""

from fastapi import HTTPException                                   # noqa: E402
from loanagent.llm import OpenRouterLLM                              # noqa: E402
from loanagent.orchestrator import ScriptedApprover, role_for_gate, run_case, validate_human_action  # noqa: E402
from web import app as web_app                                       # noqa: E402

APPS = HERE.parent / "data" / "applications"
COMPLIANCE = {"gate": "compliance", "role": "Compliance Officer"}
CREDIT = {"gate": "credit", "role": "Board Credit Committee"}
CASE = SimpleNamespace(policy_checks=[], application={"credit_analyst": "Daniel Okafor", "relationship_manager": "Priya Nair"},
                       recommendation={"action": "APPROVE"})


def request_for(email, full_name="Test Approver"):
    return SimpleNamespace(state=SimpleNamespace(portal_user={"email": email, "full_name": full_name, "role": "admin"}))


class OpenRouterExtractionTests(unittest.TestCase):
    def test_extraction_parses_without_import_error(self):
        llm = OpenRouterLLM(api_key="not-used")
        llm._call = lambda system, prompt, **kw: '{"valuation_date": {"value": "2026-02-10", "line": 2, "confidence": 0.9}}'
        out = llm.extract("v.txt", "valuation", ["VALUATION REPORT", "Valuation date: 2026-02-10"],
                          [{"name": "valuation_date", "type": "str", "description": "date"}])
        self.assertEqual(out["valuation_date"].value, "2026-02-10")
        self.assertEqual(out["valuation_date"].evidence.quote, "Valuation date: 2026-02-10")


class DecisionValidationTests(unittest.TestCase):
    def action(self, decision):
        return {"name": "Grace Mwangi", "role": "Compliance Officer", "decision": decision, "rationale": "Reviewed the file."}

    def test_invalid_decision_rejected_at_each_gate(self):
        self.assertTrue(any("invalid decision" in e for e in validate_human_action(COMPLIANCE, self.action("YOLO"), CASE)))
        credit = {**self.action("EDD CLEARED"), "role": "Board Credit Committee"}
        self.assertTrue(any("invalid decision" in e for e in validate_human_action(CREDIT, credit, CASE)))

    def test_valid_decision_accepted(self):
        self.assertEqual(validate_human_action(COMPLIANCE, self.action("EDD CLEARED"), CASE), [])

    def test_invalid_decision_does_not_advance_case(self):
        script = {"compliance": [self.action("YOLO"), self.action("EDD CLEARED")],
                  "credit": [{"name": "Amara Osei", "role": "Board Credit Committee",
                              "decision": "APPROVE WITH CONDITIONS", "rationale": ""}]}
        out = Path(tempfile.mkdtemp())
        case = run_case(APPS / "APP-2026-0142", ScriptedApprover(script), out, as_of="2026-10-19", llm_mode="mock", verbose=False)
        self.assertEqual([d["decision"] for d in case.human_decisions if d["gate"] == "compliance"], ["EDD CLEARED"])
        entries = [json.loads(l) for l in (out / "APP-2026-0142" / "audit_log.jsonl").read_text().splitlines()]
        self.assertTrue(any(e["action"] == "human_action_blocked" for e in entries))
        self.assertTrue(all(e["outputs"].get("recorded") for e in entries if e["actor_type"] == "human"))


class ApproverIdentityTests(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.path = folder / "assignments.json"
        self.path.write_text(json.dumps({"assignments": {
            "compliance@example.com": ["Compliance Officer"],
            "BOARD@example.com": ["Compliance Officer", "Board Credit Committee", "Not A Role"],
            "manager@example.com": ["Senior Credit Manager"],
        }}))
        patcher = mock.patch.object(web_app, "APPROVER_ASSIGNMENTS", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def session(self, gate):
        s = web_app.Session("TEST")
        s.status, s._orig_gate, s.pending_case = "awaiting_approval", gate, CASE
        web_app._sessions[s.id] = s
        self.addCleanup(web_app._sessions.pop, s.id, None)
        return s

    def approve(self, s, email, decision="APPROVE", rationale="Reviewed the cited evidence in full.", full_name="Test Approver"):
        body = web_app.ApproveRequest.model_validate(
            {"name": "Totally Made Up", "role": "Board Credit Committee", "decision": decision, "rationale": rationale})
        return web_app.submit_approval(s.id, body, request_for(email, full_name))

    def test_request_body_cannot_set_name_or_role(self):
        s = self.session(CREDIT)
        self.assertTrue(self.approve(s, "board@example.com")["ok"])
        self.assertEqual(s._resp["name"], "Test Approver")
        self.assertEqual(s._resp["role"], "Board Credit Committee")
        self.assertEqual(s._resp["authenticated_account"], "board@example.com")

    def test_claiming_a_role_does_not_grant_it(self):
        s = self.session(CREDIT)
        result = self.approve(s, "manager@example.com")
        self.assertFalse(result["ok"])
        self.assertTrue(any("insufficient authority" in e for e in result["errors"]))
        self.assertIsNone(s._resp)

    def test_unassigned_account_is_refused(self):
        s = self.session(COMPLIANCE)
        self.assertEqual(self.approve(s, "nobody@example.com", "EDD CLEARED"),
                         {"ok": False, "errors": ["Your account has no approver role assigned."]})

    def test_missing_or_malformed_file_grants_nothing(self):
        self.path.write_text("not json")
        self.assertEqual(web_app.approver_roles("board@example.com"), [])
        self.path.unlink()
        self.assertEqual(web_app.approver_roles("board@example.com"), [])

    def test_signed_in_analyst_cannot_approve_own_case(self):
        s = self.session(COMPLIANCE)
        result = self.approve(s, "compliance@example.com", "EDD CLEARED", full_name="Daniel Okafor")
        self.assertFalse(result["ok"])
        self.assertTrue(any("segregation of duties" in e for e in result["errors"]))

    def test_invalid_decision_refused_through_api(self):
        s = self.session(COMPLIANCE)
        self.assertFalse(self.approve(s, "compliance@example.com", "YOLO")["ok"])

    def test_unknown_roles_are_dropped(self):
        self.assertEqual(web_app.approver_roles("board@example.com"), ["Compliance Officer", "Board Credit Committee"])

    def test_role_for_gate_uses_the_applicable_role(self):
        roles = ["Compliance Officer", "Senior Analyst", "Senior Credit Manager", "Board Credit Committee"]
        self.assertEqual(role_for_gate(COMPLIANCE, roles), "Compliance Officer")
        self.assertEqual(role_for_gate({"gate": "data_validation", "role": "Senior Analyst"}, roles), "Senior Analyst")
        self.assertEqual(role_for_gate(CREDIT, roles), "Board Credit Committee")
        self.assertEqual(role_for_gate(CREDIT, []), "")

    def test_recorded_approvers_refused_for_portal_applications(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "APP-PORTAL").mkdir()
        (folder / "APP-PORTAL" / "application.json").write_text(json.dumps({"channel": "Web portal"}))
        with mock.patch.object(web_app, "DATA", folder), mock.patch.object(threading.Thread, "start") as started:
            with self.assertRaises(HTTPException) as caught:
                web_app.start_run("APP-PORTAL", web_app.RunRequest(llm_mode="mock", approver="scripted"))
            self.assertEqual(caught.exception.status_code, 400)
            started.assert_not_called()


if __name__ == "__main__":
    unittest.main()
