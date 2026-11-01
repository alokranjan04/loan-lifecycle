"""Documents must belong to the applicant, and the evidence must be available while a gate is open."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# web.app loads .env files for any key not already set; keep these tests offline.
for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "QDRANT_API_KEY"):
    os.environ[key] = ""

from fastapi import HTTPException                       # noqa: E402
from loanagent.agents import names_borrower             # noqa: E402
from loanagent.orchestrator import run_case, validate_human_action   # noqa: E402
from web import app as web_app                          # noqa: E402

CLEAN_CASE = HERE.parent / "data" / "applications" / "APP-2026-0157"


class NameMatchTests(unittest.TestCase):
    def test_legal_suffix_differences_still_match(self):
        self.assertTrue(names_borrower("Meridian Agro Processing Pvt Ltd", "MERIDIAN AGRO PROCESSING PRIVATE LIMITED"))

    def test_different_company_does_not_match(self):
        self.assertFalse(names_borrower("A1 pvt ltd", "NORTHWIND PRECISION COMPONENTS LLC"))

    def test_short_name_needs_whole_words(self):
        self.assertFalse(names_borrower("A1 Ltd", "Reference BA12 issued by QA1 services"))


class SanctionsHardStopTests(unittest.TestCase):
    GATE = {"gate": "credit", "role": "Senior Credit Manager"}

    def errors(self, decision, status="FAIL"):
        case = SimpleNamespace(application={}, recommendation={"action": "DECLINE"},
                               policy_checks=[SimpleNamespace(rule_id="POL-3.3", status=status)])
        return validate_human_action(self.GATE, {"name": "Grace Mwangi", "role": "Board Credit Committee", "decision": decision,
                                                 "rationale": "Reviewed the screening result in full."}, case)

    def test_confirmed_match_cannot_be_overridden(self):
        for decision in ("APPROVE", "APPROVE WITH CONDITIONS", "RETURN TO RM"):
            self.assertTrue(any("sanctions" in e for e in self.errors(decision)), decision)

    def test_confirmed_match_can_be_declined(self):
        self.assertEqual(self.errors("DECLINE"), [])

    def test_without_a_match_an_override_is_still_possible(self):
        self.assertEqual(self.errors("APPROVE", status="PASS"), [])


class ApplicantMismatchTests(unittest.TestCase):
    def run_as(self, legal_name=None, amount=None):
        folder = Path(tempfile.mkdtemp())
        case_dir = folder / "case"
        shutil.copytree(CLEAN_CASE, case_dir)
        path = case_dir / "application.json"
        application = json.loads(path.read_text())
        application["borrower"]["legal_name"] = legal_name or application["borrower"]["legal_name"]
        application["facility"]["amount_usd"] = amount or application["facility"]["amount_usd"]
        path.write_text(json.dumps(application))
        return run_case(case_dir, SimpleNamespace(ask=None), folder / "out", as_of="2026-10-16", llm_mode="mock",
                        verbose=False, prepare_only=True)

    def test_matching_documents_are_not_flagged(self):
        case = self.run_as()
        self.assertEqual(case.recommendation["action"], "APPROVE")
        self.assertFalse(case.checklist.get("entity_mismatches"))

    def test_another_companys_documents_cannot_be_approved(self):
        case = self.run_as(legal_name="A1 Pvt Ltd")
        self.assertEqual(case.recommendation["action"], "RETURN TO RM")
        self.assertIn("do not name the applicant", case.recommendation["reason"])
        self.assertEqual(next(c.status for c in case.policy_checks if c.rule_id == "POL-3.4"), "FAIL")
        titles = [f.title for f in case.findings if f.severity == "high"]
        self.assertTrue(any("kyc_ubo_declaration.txt" in t for t in titles))

    def test_another_companys_figures_are_not_scored(self):
        case = self.run_as(legal_name="A1 Pvt Ltd")
        self.assertIs(case.risk["assessed"], False)
        self.assertIsNone(case.risk["grade"])
        self.assertEqual(case.risk["mitigants"], [])
        statuses = {c.rule_id: c.status for c in case.policy_checks}
        for rule in ("POL-2.2", "POL-2.3", "POL-2.4", "POL-3.1", "POL-3.2", "POL-3.3", "POL-5.2"):
            self.assertEqual(statuses[rule], "NOT_EVALUATED", rule)
        self.assertFalse([f for f in case.findings if "NOT EVALUATED" in f.title])

    def test_a_screening_hit_survives_a_mismatch(self):
        folder = Path(tempfile.mkdtemp())
        case_dir = folder / "case"
        shutil.copytree(CLEAN_CASE, case_dir)
        application = json.loads((case_dir / "application.json").read_text())
        application["borrower"]["legal_name"] = "A1 Pvt Ltd"
        (case_dir / "application.json").write_text(json.dumps(application))
        watchlist = folder / "watchlist.json"
        watchlist.write_text(json.dumps({"sanctions": [{"name": "Tomas Reyes", "list": "test"}]}))
        case = run_case(case_dir, SimpleNamespace(ask=None), folder / "out", as_of="2026-10-16", llm_mode="mock",
                        verbose=False, prepare_only=True, watchlist_path=watchlist)
        self.assertEqual(next(c.status for c in case.policy_checks if c.rule_id == "POL-3.3"), "FAIL")
        self.assertEqual(case.recommendation["action"], "DECLINE")

    def test_matching_documents_are_still_scored(self):
        case = self.run_as()
        self.assertNotIn("assessed", case.risk)
        self.assertIsNotNone(case.risk["grade"])

    def test_mismatched_case_writes_a_report_without_a_rating(self):
        folder = Path(tempfile.mkdtemp())
        case_dir = folder / "case"
        shutil.copytree(CLEAN_CASE, case_dir)
        application = json.loads((case_dir / "application.json").read_text())
        application["borrower"]["legal_name"] = "A1 Pvt Ltd"
        (case_dir / "application.json").write_text(json.dumps(application))
        run_case(case_dir, web_app.AutoApprover(), folder / "out", as_of="2026-10-16", llm_mode="mock", verbose=False)
        memo = next((folder / "out").rglob("*.md")).read_text(encoding="utf-8")
        self.assertIn("Not assessed", memo)
        self.assertNotIn("Internal rating **", memo)

    def test_extra_document_adds_no_requirements(self):
        folder = Path(tempfile.mkdtemp())
        case_dir = folder / "case"
        shutil.copytree(CLEAN_CASE, case_dir)
        (case_dir / "documents" / "project_report.txt").write_text("PROJECT REPORT\nNorthwind Precision Components LLC\n")
        application = json.loads((case_dir / "application.json").read_text())
        application["declared_documents"].append("project_report.txt")
        (case_dir / "application.json").write_text(json.dumps(application))
        case = run_case(case_dir, SimpleNamespace(ask=None), folder / "out", as_of="2026-10-16", llm_mode="mock",
                        verbose=False, prepare_only=True)
        self.assertFalse([m for m in case.checklist["missing"] if m["doc"] == "project_report"])

    def test_valuation_need_not_name_the_applicant(self):
        case = self.run_as(legal_name="A1 Pvt Ltd")
        self.assertNotIn("collateral_valuation.txt", [m["document"] for m in case.checklist["entity_mismatches"]])

    def test_resolution_far_above_the_request_is_flagged(self):
        case = self.run_as(amount=75000)
        self.assertTrue(any(f.title == "Board resolution far above facility amount" for f in case.findings))


class ReviewPacketTests(unittest.TestCase):
    def test_only_available_while_waiting_for_a_decision(self):
        with self.assertRaises(HTTPException) as caught:
            web_app.get_review_packet("APP-2026-0157")
        self.assertEqual(caught.exception.status_code, 404)

    def test_packet_holds_checks_findings_and_fields(self):
        folder = Path(tempfile.mkdtemp())
        out = folder / "out"
        run_case(CLEAN_CASE, SimpleNamespace(ask=None), out, as_of="2026-10-16", llm_mode="mock", verbose=False, prepare_only=True)
        session = web_app.Session("APP-2026-0157")
        session.status = "awaiting_approval"
        with mock.patch.dict(web_app._sessions, {session.id: session}),                 mock.patch.dict(web_app._app_sid, {"APP-2026-0157": session.id}),                 mock.patch.object(web_app, "out_dir", lambda app_id: out / app_id):
            packet = web_app.get_review_packet("APP-2026-0157")
        self.assertEqual(len(packet["policy_checks"]), 13)
        self.assertIn("kyc", packet["extracted_fields"])
        self.assertIn("recommendation", packet)


if __name__ == "__main__":
    unittest.main()
