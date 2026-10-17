"""The agents.

Each agent has one job, reads from and writes to the CaseFile, and returns a short summary that the
orchestrator writes to the audit log. Division of labour:

  model (LLM)    reads documents, drafts emails and narrative
  code (rules)   computes ratios, applies policy, scores risk, routes approvals
  humans         clear compliance, approve, override (with a reason)
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from .citations import verify
from .models import SEVERITY_ORDER, CaseFile, Condition, Evidence, Finding, PolicyCheck
from .security import QUARANTINE, PIIVault, scan_for_injection


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _money(n: float) -> str:
    return f"USD {n:,.0f}"


# ---------------------------------------------------------------------------------------------
# Document schemas: what the Document Intelligence Agent extracts from each document type.
# mock_pattern is used only by the offline MockLLM; Claude gets the description.
# ---------------------------------------------------------------------------------------------
def _fy(label: str, idx: int) -> str:
    cols = [r"[\d,]+"] * 3
    cols[idx] = r"([\d,]+)"
    return rf"^{label}\s+" + r"\s+".join(cols)


SCHEMAS: dict[str, list[dict]] = {
    "financials": [
        *[{"name": f"revenue_fy{y}", "type": "money", "description": f"Revenue for FY{y}",
           "mock_pattern": _fy("Revenue", i)} for i, y in enumerate((2023, 2024, 2025))],
        *[{"name": f"ebitda_fy{y}", "type": "money", "description": f"EBITDA for FY{y}",
           "mock_pattern": _fy("EBITDA", i)} for i, y in enumerate((2023, 2024, 2025))],
        {"name": "interest_fy2025", "type": "money", "description": "Interest expense, latest year", "mock_pattern": _fy("Interest expense", 2)},
        {"name": "net_profit_fy2025", "type": "money", "description": "Net profit, latest year", "mock_pattern": _fy("Net profit", 2)},
        {"name": "total_debt", "type": "money", "description": "Total debt on the latest balance sheet", "mock_pattern": r"^Total debt\s+([\d,]+)"},
        {"name": "current_assets", "type": "money", "description": "Current assets", "mock_pattern": r"^Current assets\s+([\d,]+)"},
        {"name": "current_liabilities", "type": "money", "description": "Current liabilities", "mock_pattern": r"^Current liabilities\s+([\d,]+)"},
        {"name": "equity", "type": "money", "description": "Shareholders equity", "mock_pattern": r"^Shareholders equity\s+([\d,]+)"},
        {"name": "principal_fy2025", "type": "money", "description": "Scheduled principal repayment, latest year", "mock_pattern": r"principal repayment\s+([\d,]+)"},
        {"name": "audit_opinion", "type": "str", "description": "Auditor's opinion", "mock_pattern": r"Audit opinion:\s*(.+)$"},
        {"name": "related_party_name", "type": "str", "description": "Name of related party customer, if disclosed", "mock_pattern": r"Related party sales to (.+?) amounted"},
        {"name": "related_party_sales", "type": "money", "description": "Related party sales amount", "mock_pattern": r"Related party sales to .+? amounted to ([\d,]+)"},
    ],
    "bank_statement": [
        {"name": "total_credits", "type": "money", "description": "Total credits over 12 months", "mock_pattern": r"Total credits \(12 months\):\s*([\d,]+)"},
        {"name": "returned_items", "type": "int", "description": "Number of returned / bounced items", "mock_pattern": r"Returned items[^:]*:\s*(\d+)"},
        {"name": "lowest_balance", "type": "money", "description": "Lowest month-end balance", "mock_pattern": r"Lowest month-end balance:\s*([\d,]+)"},
        {"name": "peak_od_pct", "type": "float", "optional": True, "description": "Peak overdraft utilisation percent", "mock_pattern": r"Overdraft utilisation: peak (\d+)%"},
        {"name": "period", "type": "str", "description": "Statement period", "mock_pattern": r"Period:\s*(.+)$"},
    ],
    "kyc": [
        {"name": "directors", "type": "list", "multi": True, "columns": ["name", "role", "shareholding", "id", "id_expiry"],
         "description": "Every director/owner with role, shareholding percent, ID document and ID expiry date (YYYY-MM-DD)",
         "mock_pattern": r"Director \d+:\s*(.+?)\s*\|\s*Role:\s*(.+?)\s*\|\s*Shareholding:\s*(\d+)%\s*\|\s*ID:\s*(.+?)\s*\|\s*ID expiry:\s*(\d{4}-\d{2}-\d{2})"},
        {"name": "declaration_date", "type": "str", "description": "Date of declaration", "mock_pattern": r"Date of declaration:\s*(\S+)"},
    ],
    "valuation": [
        {"name": "valuation_date", "type": "str", "description": "Valuation date YYYY-MM-DD; if the report states only the inspection date the valuation is based on, use that date", "mock_pattern": r"Valuation date:\s*(\d{4}-\d{2}-\d{2})"},
        {"name": "valuer", "type": "str", "description": "Valuer name and empanelment status", "mock_pattern": r"Valuer:\s*(.+)$"},
        {"name": "market_value", "type": "money", "description": "Market value", "mock_pattern": r"Market value \(USD\):\s*([\d,]+)"},
        {"name": "realisable_value", "type": "money", "description": "Realisable value", "mock_pattern": r"Realisable value \(USD\):\s*([\d,]+)"},
        {"name": "remarks", "type": "str", "description": "Valuer remarks", "mock_pattern": r"Remarks:\s*(.+)$"},
    ],
    "project_report": [
        {"name": "total_project_cost", "type": "money", "description": "Total project cost", "mock_pattern": r"Total project cost \(USD\):\s*([\d,]+)"},
        {"name": "promoter_equity", "type": "money", "description": "Promoter equity contribution", "mock_pattern": r"Promoter equity contribution \(USD\):\s*([\d,]+)"},
        {"name": "dscr_by_year", "type": "float_list", "description": "Projected DSCR for each year", "mock_pattern": r"Projected DSCR by year:\s*(.+)$"},
        {"name": "dscr_avg", "type": "float", "description": "Average projected DSCR", "mock_pattern": r"Average projected DSCR:\s*([\d.]+)"},
        {"name": "cod", "type": "str", "description": "Commercial operations date", "mock_pattern": r"Commercial operations date:\s*(\S+)"},
    ],
    "tax_return": [
        {"name": "tax_year", "type": "int", "description": "Tax year", "mock_pattern": r"Tax year:\s*(\d{4})"},
        {"name": "gross_receipts", "type": "money", "description": "Gross receipts", "mock_pattern": r"Gross receipts:\s*([\d,]+)"},
        {"name": "status", "type": "str", "description": "Filing status", "mock_pattern": r"Status:\s*(.+)$"},
    ],
    "board_resolution": [
        {"name": "amount", "type": "money", "description": "Borrowing amount authorised", "mock_pattern": r"borrow up to USD ([\d,]+)"},
        {"name": "date", "type": "str", "description": "Date of resolution", "mock_pattern": r"Date of resolution:\s*(\S+)"},
    ],
}

CLASSIFIER = [
    ("financials", "AUDITED FINANCIAL STATEMENTS"), ("bank_statement", "STATEMENT SUMMARY"),
    ("kyc", "BENEFICIAL OWNERSHIP"), ("valuation", "VALUATION REPORT"), ("project_report", "PROJECT REPORT"),
    ("tax_return", "TAX RETURN"), ("board_resolution", "RESOLUTION"),
]

DOC_LABELS = {
    "financials": "3 years audited financial statements", "bank_statement": "12 months bank statements",
    "kyc": "KYC / UBO declaration", "valuation": "Collateral valuation report", "project_report": "Project report",
    "tax_return": "Latest tax returns", "board_resolution": "Board resolution authorising the borrowing",
}
BLOCKING_DOCS = {"financials", "bank_statement", "kyc"}   # cannot be deferred to a condition precedent

SECTOR_APPETITE = {"agri and food processing": "Grow", "industrial manufacturing": "Grow",
                   "commercial real estate": "Maintain", "coal mining": "Exit", "thermal power": "Exit"}
AUTHORITY_RANK = {"Senior Credit Manager": 1, "Regional Credit Committee": 2, "Board Credit Committee": 3}
ASSUMED_NEW_LOAN_RATE = 0.075   # used to estimate debt service when no project report exists


class Agent:
    name = "Agent"

    def __init__(self, ctx):
        self.ctx = ctx
        self.llm = ctx.llm
        self.kb = ctx.kb


# ---------------------------------------------------------------------------------------------
class IntakeAgent(Agent):
    """Registers the case, validates the form and works out which documents this facility needs."""
    name = "Origination & Intake Agent"
    REQUIRED_FIELDS = ["application_id", "borrower.legal_name", "borrower.incorporated_on", "borrower.sector",
                       "facility.type", "facility.amount_usd", "facility.tenor_months", "facility.purpose"]

    def run(self, case: CaseFile) -> dict:
        app = case.application
        gaps = []
        for path in self.REQUIRED_FIELDS:
            node = app
            for part in path.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            if node in (None, ""):
                gaps.append(path)
        for g in gaps:
            case.findings.append(Finding(self.name, "missing_info", "high", f"Application field missing: {g}",
                                         "The application form is incomplete.", "POL-3.4",
                                         [Evidence("application.json")], curable=False))
        ftype = app["facility"]["type"].lower()
        required = ["financials", "bank_statement", "kyc", "tax_return", "board_resolution"]
        if "secured" in ftype:
            required.insert(3, "valuation")
        if "project" in ftype:
            required.insert(4, "project_report")
        case.checklist["required_documents"] = required
        return {"form_gaps": gaps, "required_documents": required}


# ---------------------------------------------------------------------------------------------
class DocumentIntelligenceAgent(Agent):
    """Ingests documents: masks PII, classifies, extracts fields with line citations, cross-checks."""
    name = "Document Intelligence Agent"

    def run(self, case: CaseFile, doc_dir: Path, vault: PIIVault) -> dict:
        processed = []
        for path in sorted(doc_dir.glob("*.txt")):
            raw = path.read_text()
            masked = vault.mask(raw)
            lines = masked.splitlines()
            doc_type = next((t for t, kw in CLASSIFIER if kw in raw.upper()), "unknown")
            case.documents[path.name] = {"type": doc_type, "lines": len(lines)}
            hits = scan_for_injection(lines)
            if hits:
                flags = case.checklist.setdefault("security_flags", [])
                for h in hits:
                    flags.append({"document": path.name, **h})
                    lines[h["line"] - 1] = QUARANTINE      # the model never sees the instruction
                case.findings.append(Finding(self.name, "security", "high", f"Possible prompt injection in {path.name}",
                                             f"{len(hits)} line(s) of instruction-like text addressed to an automated reviewer were "
                                             "quarantined before any model call. An analyst must review the document and its origin.",
                                             evidence=[Evidence(path.name, h["line"], vault.unmask(h["text"])) for h in hits]))
            if doc_type == "unknown":
                case.findings.append(Finding(self.name, "missing_info", "low", f"Unrecognised document: {path.name}",
                                             "Document could not be classified and needs manual review.",
                                             evidence=[Evidence(path.name)]))
                continue
            fields = self.llm.extract(path.name, doc_type, lines, SCHEMAS[doc_type])
            unverified = case.checklist.setdefault("unverified_fields", [])
            for name, f in list(fields.items()):
                ok, why = verify(f, lines)
                if not ok:
                    # never let an unverifiable number reach the rules: withhold it and send it to an analyst
                    f.citation_verified, f.verify_note = False, why
                    unverified.append({"document": path.name, "field": name, "reason": why})
                    case.findings.append(Finding(self.name, "missing_info", "medium",
                                                 f"Unverified extraction withheld: {name}",
                                                 f"The model's value could not be matched to its cited source ({why}); "
                                                 "an analyst must confirm it before it is used.",
                                                 evidence=[f.evidence]))
                    del fields[name]
            for f in fields.values():
                f.value = vault.unmask(f.value)
                f.evidence.quote = vault.unmask(f.evidence.quote)
                if f.confidence < 0.8:
                    case.findings.append(Finding(self.name, "missing_info", "low",
                                                 f"Low-confidence extraction: {f.name}",
                                                 f"Model confidence {f.confidence:.2f}; analyst to verify.",
                                                 evidence=[f.evidence]))
            self._conflicts(case, path.name, doc_type, fields, lines)
            if doc_type == "kyc" and "directors" in fields:
                for d in fields["directors"].value:
                    d["shareholding"] = float(str(d["shareholding"]).rstrip("%"))
            case.extracted[doc_type] = fields
            processed.append({"document": path.name, "type": doc_type, "fields_extracted": len(fields),
                              "expected_fields": len(SCHEMAS[doc_type])})
        self._cross_checks(case)
        return {"documents": processed, "pii_tokens_masked": vault.total}

    # Fields where a document might state two figures, and the conservative choice if it does.
    CONFLICT_FIELDS = {
        ("valuation", "realisable_value"): (r"realisable", min), ("valuation", "market_value"): (r"market value", min),
        ("financials", "total_debt"): (r"total debt|borrowings", max), ("bank_statement", "total_credits"): (r"credits|money in", min),
        ("financials", "current_liabilities"): (r"current liabilities", max), ("financials", "current_assets"): (r"current assets", min),
    }

    def _conflicts(self, case: CaseFile, doc_name: str, doc_type: str, fields: dict, lines: list[str]):
        """If a document states a key figure twice with different values, flag it and use the conservative one."""
        for (dt, name), (kw, pick) in self.CONFLICT_FIELDS.items():
            f = fields.get(name)
            if dt != doc_type or f is None or not isinstance(f.value, (int, float)):
                continue
            others = []
            for i, line in enumerate(lines, 1):
                if i == f.evidence.line or not re.search(kw, line, re.I):
                    continue
                for num in re.findall(r"\d{1,3}(?:,\d{3})+|\d{5,}", line):
                    v = float(num.replace(",", ""))
                    if v >= 10_000 and abs(v - f.value) / max(f.value, 1) > 0.02:
                        others.append((v, i, line.strip()))
            if not others:
                continue
            chosen = pick([f.value] + [v for v, _, _ in others])
            case.findings.append(Finding(self.name, "due_diligence", "high", f"Conflicting values for {name} in {doc_name}",
                                         f"The document states {_money(f.value)} (line {f.evidence.line}) and "
                                         + ", ".join(f"{_money(v)} (line {i})" for v, i, _ in others)
                                         + f". The conservative figure {_money(chosen)} is used until an analyst confirms.",
                                         evidence=[f.evidence] + [Evidence(doc_name, i, q) for _, i, q in others]))
            if chosen != f.value:
                v, i, q = next(o for o in others if o[0] == chosen)
                fields[name] = type(f)(name, chosen, Evidence(doc_name, i, q), min(f.confidence, 0.7))

    def _cross_checks(self, case: CaseFile):
        amount = case.application["facility"]["amount_usd"]
        rev = case.field("financials", "revenue_fy2025")
        gross = case.field("tax_return", "gross_receipts")
        if rev and gross and abs(gross - rev) / rev > 0.05:
            case.findings.append(Finding(self.name, "due_diligence", "medium", "Tax return does not match audited revenue",
                                         f"Gross receipts {_money(gross)} vs audited revenue {_money(rev)}.",
                                         evidence=case.ev("tax_return", "gross_receipts") + case.ev("financials", "revenue_fy2025")))
        auth = case.field("board_resolution", "amount")
        if auth is not None and auth < amount:
            case.findings.append(Finding(self.name, "due_diligence", "high", "Board resolution below facility amount",
                                         f"Resolution authorises {_money(auth)}; facility is {_money(amount)}.", "POL-3.4",
                                         case.ev("board_resolution", "amount")))


# ---------------------------------------------------------------------------------------------
class CompletenessAgent(Agent):
    """Identifies missing documents and fields, and drafts the request back to the RM."""
    name = "Origination & Intake Agent (completeness)"

    def run(self, case: CaseFile) -> dict:
        present = {d["type"] for d in case.documents.values()}
        missing = []
        for doc in case.checklist["required_documents"]:
            if doc not in present:
                blocking = doc in BLOCKING_DOCS
                missing.append({"doc": doc, "title": DOC_LABELS[doc], "policy_ref": "POL-3.4", "blocking": blocking})
                case.findings.append(Finding(self.name, "missing_info", "high" if blocking else "medium",
                                             f"Missing document: {DOC_LABELS[doc]}",
                                             "Required by policy for this facility type; not in the submission."
                                             + ("" if blocking else " Can be taken as a condition precedent (POL-7.1)."),
                                             "POL-3.4", [Evidence("application.json")], curable=not blocking))
        for doc_type, fields in case.extracted.items():
            for spec in SCHEMAS[doc_type]:
                if spec["name"] not in fields and not spec.get("optional") and not spec["name"].startswith("related_party") and spec["type"] != "str":
                    missing.append({"doc": doc_type, "title": f"{spec['description']} (not found in {DOC_LABELS[doc_type]})",
                                    "policy_ref": "POL-3.4", "blocking": False})
        case.checklist["missing"] = missing
        case.checklist["blocking_missing"] = [m for m in missing if m["blocking"]]
        if missing:
            case.rm_request = self.llm.write("rm_request", {
                "app_id": case.app_id, "borrower": case.application["borrower"]["legal_name"],
                "rm": case.application.get("relationship_manager", "team"), "missing": missing})
        return {"missing_items": [m["title"] for m in missing], "rm_request_drafted": bool(missing)}


# ---------------------------------------------------------------------------------------------
class DueDiligenceAgent(Agent):
    """KYC validity, screening, valuation currency, account conduct and related-party exposure."""
    name = "Due Diligence Agent"

    def run(self, case: CaseFile, watchlist: dict) -> dict:
        as_of = _d(case.as_of)
        m = case.metrics
        b = case.application["borrower"]

        # KYC validity and beneficial owners
        directors = case.field("kyc", "directors") or []
        kyc_ev = case.ev("kyc", "directors")
        m["kyc_expired"] = [d for d in directors if _d(d["id_expiry"]) < as_of]
        m["kyc_expiring_90d"] = [d for d in directors if as_of <= _d(d["id_expiry"]) < as_of + timedelta(days=90)]
        m["ubos"] = [d for d in directors if d["shareholding"] >= 25]
        m["directors_read"] = bool(directors)

        # Screening (stand-in for a sanctions / PEP / adverse media API)
        names = [d["name"] for d in directors] + [b["legal_name"]]
        if case.field("financials", "related_party_name"):
            names.append(case.field("financials", "related_party_name"))
        hits = {k: [w for w in watchlist.get(k, []) if any(w["name"].lower() == n.lower() for n in names)]
                for k in ("sanctions", "pep", "adverse_media")}
        m["screening"] = hits
        m["screened_names"] = names
        case.checklist["edd_required"] = bool(hits["pep"])
        for a in hits["adverse_media"]:
            case.findings.append(Finding(self.name, "due_diligence", "low", f"Adverse media: {a['name']}", a["detail"],
                                         "POL-3.3", [Evidence("screening_api", None, a["detail"])]))

        # Valuation currency
        vdate = case.field("valuation", "valuation_date")
        if vdate:
            m["valuation_age_days"] = (as_of - _d(vdate)).days
            valuer = case.field("valuation", "valuer")
            m["valuer_empanelled"] = None if not valuer else "empanelled" in valuer.lower()
        remarks = case.field("valuation", "remarks") or ""
        if "partially constructed" in remarks.lower():
            case.findings.append(Finding(self.name, "risk", "low", "Collateral is under construction",
                                         "Realisable value depends on completing the building; valuation should be refreshed at completion.",
                                         evidence=case.ev("valuation", "remarks")))

        # Account conduct
        credits = case.field("bank_statement", "total_credits")
        rev = case.field("financials", "revenue_fy2025")
        if credits and rev:
            m["bank_credit_to_revenue"] = credits / rev
        m["returned_items"] = case.field("bank_statement", "returned_items")
        od = case.field("bank_statement", "peak_od_pct")
        if od is not None and od >= 90:
            case.findings.append(Finding(self.name, "conduct", "medium", "Working capital stress",
                                         f"Overdraft utilisation peaked at {od:.0f}% of limit; lowest month-end balance "
                                         f"{_money(case.field('bank_statement', 'lowest_balance') or 0)}.",
                                         evidence=case.ev("bank_statement", "peak_od_pct") + case.ev("bank_statement", "lowest_balance")))

        # Related party concentration
        rps = case.field("financials", "related_party_sales")
        if rps and rev and rps / rev > 0.05:
            case.findings.append(Finding(self.name, "risk", "medium", "Related-party revenue concentration",
                                         f"{rps / rev:.1%} of FY2025 revenue is from related party "
                                         f"{case.field('financials', 'related_party_name')}.",
                                         evidence=case.ev("financials", "related_party_sales")))
        return {"screened": names, "sanctions_hits": len(hits["sanctions"]), "pep_hits": len(hits["pep"]),
                "adverse_media_hits": len(hits["adverse_media"]), "kyc_expired": [d["name"] for d in m["kyc_expired"]],
                "valuation_age_days": m.get("valuation_age_days")}


# ---------------------------------------------------------------------------------------------
class PolicyEligibilityAgent(Agent):
    """Computes the ratios and evaluates each policy clause, citing the clause retrieved from the KB."""
    name = "Policy & Eligibility Agent"

    def run(self, case: CaseFile) -> dict:
        app, m = case.application, case.metrics
        fac, b = app["facility"], app["borrower"]
        amount = fac["amount_usd"]
        as_of = _d(case.as_of)
        f = lambda n: case.field("financials", n)

        m["vintage_years"] = (as_of - _d(b["incorporated_on"])).days / 365.25
        m["years_audited"] = sum(1 for y in (2023, 2024, 2025) if f(f"revenue_fy{y}"))
        ebitda = f("ebitda_fy2025")
        if ebitda:
            m["debt_ebitda_post"] = ((f("total_debt") or 0) + amount) / ebitda
            existing_ds = (f("interest_fy2025") or 0) + (f("principal_fy2025") or 0)
            m["dscr_hist"] = ebitda / existing_ds if existing_ds else float("inf")
            if case.field("project_report", "dscr_avg"):
                m["dscr_proj"] = case.field("project_report", "dscr_avg")
                m["dscr_proj_source"] = "project report"
            else:
                r, n = ASSUMED_NEW_LOAN_RATE / 12, fac["tenor_months"]
                new_ds = 12 * amount * r / (1 - (1 + r) ** -n)
                m["dscr_proj"] = ebitda / (existing_ds + new_ds)
                m["dscr_proj_source"] = f"computed: FY2025 EBITDA / (existing debt service + new annuity at {ASSUMED_NEW_LOAN_RATE:.1%})"
        if case.field("valuation", "realisable_value"):
            m["ltv"] = amount / case.field("valuation", "realisable_value")
        if f("current_liabilities"):
            m["current_ratio"] = f("current_assets") / f("current_liabilities")
        if case.field("project_report", "total_project_cost"):
            m["promoter_share"] = case.field("project_report", "promoter_equity") / case.field("project_report", "total_project_cost")
        m["group_exposure_post"] = b.get("existing_group_exposure_usd", 0) + amount
        m["sector_appetite"] = SECTOR_APPETITE.get(b["sector"].lower(), "Not classified")

        # A mandatory check whose inputs could not be read is NOT_EVALUATED, never a silent pass or a skip.
        secured = "secured" in fac["type"].lower()
        project = "project" in fac["type"].lower()
        nx = lambda rule_id, query, why: self._check(rule_id, query, "NOT_EVALUATED", why, "inputs needed to evaluate", [])
        K = self.kb.p            # thresholds come from the policy version in force, never from code
        vy, ay = K("vintage_years_min"), K("audited_years_min")
        lmax, lflag = K("leverage_max"), K("leverage_flag")
        dp, dh, dsw = K("dscr_proj_min"), K("dscr_hist_min"), K("dscr_sweep_below")
        checks = [
            self._check("POL-2.1", "business vintage operating history audited", "PASS" if m["vintage_years"] >= vy and m["years_audited"] >= ay else "FAIL",
                        f"{m['vintage_years']:.1f} yrs, {m['years_audited']} audited yrs", f">= {vy} yrs and {ay} audited yrs",
                        [Evidence("application.json", None, f"incorporated_on {b['incorporated_on']}")] + case.ev("financials", "revenue_fy2023"))
            if f("revenue_fy2025") else nx("POL-2.1", "business vintage operating history audited", "audited revenue could not be read"),
        ]
        if "debt_ebitda_post" not in m:
            checks.append(nx("POL-2.2", "leverage total debt EBITDA", "EBITDA could not be read"))
            checks.append(nx("POL-2.3", "debt service coverage DSCR projected historical", "EBITDA could not be read"))
        if "debt_ebitda_post" in m:
            v = m["debt_ebitda_post"]
            checks.append(self._check("POL-2.2", "leverage total debt EBITDA", "PASS" if v <= lflag else "FLAG" if v <= lmax else "FAIL",
                                      f"{v:.2f}x", f"<= {lmax:.1f}x (flag above {lflag:.1f}x)", case.ev("financials", "total_debt") + case.ev("financials", "ebitda_fy2025"),
                                      note="Elevated leverage" if lflag < v <= lmax else ""))
            p, h = m["dscr_proj"], m["dscr_hist"]
            st = "FAIL" if p < dp or h < dh else "FLAG" if p < dsw else "PASS"
            checks.append(self._check("POL-2.3", "debt service coverage DSCR projected historical", st,
                                      f"projected {p:.2f}x, historical {h:.2f}x", f"projected >= {dp:.2f}x, historical >= {dh:.2f}x",
                                      case.ev("project_report", "dscr_avg") + case.ev("financials", "ebitda_fy2025"),
                                      curable=st == "FLAG", note="Needs DSRA / cash sweep" if st == "FLAG" else ""))
        if "ltv" in m:
            checks.append(self._check("POL-2.4", "loan to value collateral", "PASS" if m["ltv"] <= K("ltv_max") else "FAIL",
                                      f"{m['ltv']:.1%}", f"<= {K('ltv_max'):.0%}", case.ev("valuation", "realisable_value")))
        elif secured:
            checks.append(nx("POL-2.4", "loan to value collateral", "realisable value of collateral not available"))
        if "current_ratio" in m and f("current_assets") is not None:
            checks.append(self._check("POL-2.5", "liquidity current ratio", "PASS" if m["current_ratio"] >= K("current_ratio_min") else "FAIL",
                                      f"{m['current_ratio']:.2f}x", f">= {K('current_ratio_min'):.2f}x", case.ev("financials", "current_assets") + case.ev("financials", "current_liabilities")))
        else:
            checks.append(nx("POL-2.5", "liquidity current ratio", "current assets or current liabilities could not be read"))
        if project:
            ps = m.get("promoter_share")
            if ps is None:
                checks.append(nx("POL-2.6", "promoter contribution equity project", "project cost and promoter equity not available"))
            else:
                checks.append(self._check("POL-2.6", "promoter contribution equity project", "PASS" if ps >= K("promoter_min") else "FAIL",
                                          f"{ps:.1%}", f">= {K('promoter_min'):.0%} of project cost", case.ev("project_report", "promoter_equity")))
        if secured and "valuation_age_days" not in m:
            checks.append(nx("POL-3.1", "collateral valuation currency 180 days", "valuation date not available"))
        if "valuation_age_days" in m and m["valuer_empanelled"] is None and m["valuation_age_days"] <= K("valuation_max_age_days"):
            # a stale valuation fails whoever the valuer is; a current one passes only with a known empanelled valuer
            checks.append(nx("POL-3.1", "collateral valuation currency 180 days", "valuer not available"))
        elif "valuation_age_days" in m:
            ok = m["valuation_age_days"] <= K("valuation_max_age_days") and m["valuer_empanelled"]
            checks.append(self._check("POL-3.1", "collateral valuation currency 180 days", "PASS" if ok else "FAIL",
                                      f"{m['valuation_age_days']} days old" + ("" if m["valuer_empanelled"] else ", valuer not empanelled"),
                                      f"<= {K('valuation_max_age_days')} days, empanelled valuer", case.ev("valuation", "valuation_date"), curable=True,
                                      note="Fresh valuation needed" if not ok else ""))
        exp = m.get("kyc_expired", [])
        if not m.get("directors_read"):
            checks.append(nx("POL-3.2", "KYC beneficial ownership identity documents valid", "directors and owners could not be read"))
        else:
            checks.append(self._check("POL-3.2", "KYC beneficial ownership identity documents valid", "FAIL" if exp else "PASS",
                                      ", ".join(f"{d['name']} ({d['shareholding']:.0f}%) ID expired {d['id_expiry']}" for d in exp) or "all IDs valid",
                                      "all director / UBO IDs valid", case.ev("kyc", "directors"), curable=True))
        hits = m.get("screening", {})
        st = "FAIL" if hits.get("sanctions") else "FLAG" if hits.get("pep") else "PASS" if m.get("directors_read") else "NOT_EVALUATED"
        actual = "; ".join([f"SANCTIONS: {h['name']}" for h in hits.get("sanctions", [])] +
                           [f"PEP: {h['name']} ({h['detail']})" for h in hits.get("pep", [])]) or "no sanctions or PEP matches"
        checks.append(self._check("POL-3.3", "sanctions PEP politically exposed adverse media screening", st, actual,
                                  "no sanctions match; PEP needs EDD + Compliance sign-off",
                                  [Evidence("screening_api", None, actual)], curable=False,
                                  note="Compliance EDD gate added" if st == "FLAG" else
                                  "Directors and owners could not be read, so they were not screened" if st == "NOT_EVALUATED" else ""))
        miss = [m_ for m_ in case.checklist.get("missing", []) if m_["policy_ref"] == "POL-3.4" and m_["doc"] in DOC_LABELS and m_["title"] == DOC_LABELS[m_["doc"]]]
        checks.append(self._check("POL-3.4", "mandatory documents complete application", "FAIL" if miss else "PASS",
                                  ", ".join(x["title"] for x in miss) or "all present", "all mandatory documents",
                                  [Evidence("application.json")], curable=not any(x["blocking"] for x in miss)))
        app_ = m["sector_appetite"]
        checks.append(self._check("POL-4.1", "sector appetite grow maintain exit", "FAIL" if app_ == "Exit" else "FLAG" if app_ in ("Maintain", "Not classified") else "PASS",
                                  f"{b['sector']}: {app_}", "not an Exit sector", [Evidence("application.json", None, b["sector"])]))
        checks.append(self._check("POL-4.2", "single obligor limit exposure", "PASS" if m["group_exposure_post"] <= K("single_obligor_max_usd") else "FAIL",
                                  _money(m["group_exposure_post"]), f"<= {_money(K('single_obligor_max_usd'))}", [Evidence("application.json")]))
        if m.get("returned_items") is None:
            checks.append(nx("POL-5.1", "returned items bounced payments", "bank statement returned items not available"))
        if "bank_credit_to_revenue" not in m:
            checks.append(nx("POL-5.2", "revenue reconciliation bank credits", "bank credits or revenue not available"))
        if m.get("returned_items") is not None:
            checks.append(self._check("POL-5.1", "returned items bounced payments", "FLAG" if m["returned_items"] > K("returned_items_max") else "PASS",
                                      f"{m['returned_items']} in 12 months", f"<= {K('returned_items_max')}", case.ev("bank_statement", "returned_items"),
                                      curable=True, note="RM explanation required" if m["returned_items"] > K("returned_items_max") else ""))
        if "bank_credit_to_revenue" in m:
            r = m["bank_credit_to_revenue"]
            checks.append(self._check("POL-5.2", "revenue reconciliation bank credits", "FLAG" if r < K("bank_credit_to_revenue_min") else "PASS",
                                      f"{r:.0%} of reported revenue", f">= {K('bank_credit_to_revenue_min'):.0%}", case.ev("bank_statement", "total_credits") + case.ev("financials", "revenue_fy2025"),
                                      curable=True, note="Investigate other banking / revenue quality" if r < K("bank_credit_to_revenue_min") else ""))
        order = ["POL-2.1", "POL-2.2", "POL-2.3", "POL-2.4", "POL-2.5", "POL-2.6", "POL-3.1", "POL-3.2", "POL-3.3", "POL-3.4",
                 "POL-4.1", "POL-4.2", "POL-5.1", "POL-5.2"]
        checks.sort(key=lambda c: order.index(c.rule_id) if c.rule_id in order else 99)
        case.policy_checks = checks

        sev = {"POL-3.3": "high", "POL-5.2": "high", "POL-3.2": "high", "POL-3.1": "high"}
        for c in checks:
            if c.status == "NOT_EVALUATED":
                case.findings.append(Finding(self.name, "missing_info", "high", f"{c.rule_id} {c.name}: NOT EVALUATED",
                                             f"This mandatory check could not be run: {c.actual}. It is not treated as a pass.",
                                             c.rule_id, curable=False, status="not_evaluated"))
                continue
            if c.status in ("FAIL", "FLAG") and c.rule_id != "POL-3.4":   # missing documents already raised by the completeness pass
                s = "critical" if c.status == "FAIL" and not c.curable else sev.get(c.rule_id, "medium")
                case.findings.append(Finding(self.name, "policy", s, f"{c.rule_id} {c.name}: {c.status}",
                                             f"Actual {c.actual}; policy requires {c.threshold}." + (f" {c.note}." if c.note else ""),
                                             c.rule_id, c.evidence, curable=c.curable, status=c.status.lower()))
        return {"checks": {c.rule_id: c.status for c in checks}, "kb_version": self.kb.version}

    def _check(self, rule_id, query, status, actual, threshold, evidence, curable=False, note=""):
        hits = self.kb.search(query, k=3)
        clause = next((c for c, _ in hits if c.id == rule_id), None) or self.kb.get(rule_id)
        return PolicyCheck(rule_id, clause.title, status, actual, threshold, clause.text, evidence, curable, note,
                           policy_version=self.kb.version)


# ---------------------------------------------------------------------------------------------
class RiskAgent(Agent):
    """Scores the case on a transparent scorecard and writes the risk observations."""
    name = "Risk Agent"
    PD = {1: 0.0003, 2: 0.0005, 3: 0.001, 4: 0.002, 5: 0.005, 6: 0.01, 7: 0.025, 8: 0.05, 9: 0.12, 10: 0.25}
    GRADE = {1: "A", 2: "A", 3: "BBB", 4: "BBB", 5: "BB", 6: "BB", 7: "B", 8: "B", 9: "CCC", 10: "CCC"}

    def run(self, case: CaseFile) -> dict:
        m = case.metrics
        band = lambda v, cuts: next((i for i, c in enumerate(cuts) if c(v)), len(cuts))
        factors = {
            "Leverage (Debt/EBITDA)": band(m.get("debt_ebitda_post", 9), [lambda v: v < 2, lambda v: v < 3, lambda v: v < 3.5, lambda v: v <= 4]),
            "Projected DSCR": band(m.get("dscr_proj", 0), [lambda v: v >= 1.75, lambda v: v >= 1.5, lambda v: v >= 1.4, lambda v: v >= 1.25]),
            "Liquidity (current ratio)": band(m.get("current_ratio", 0), [lambda v: v >= 1.5, lambda v: v >= 1.25, lambda v: v >= 1.1]),
            "Collateral (LTV)": band(m.get("ltv", 1), [lambda v: v <= 0.5, lambda v: v <= 0.6, lambda v: v <= 0.7]),
            "Account conduct": (2 if (m.get("returned_items") or 0) > 2 else 0) + (2 if m.get("bank_credit_to_revenue", 1) < 0.8 else 0),
            "Sector appetite": {"Grow": 0, "Maintain": 1}.get(m.get("sector_appetite"), 2),
            "Vintage": band(m.get("vintage_years", 0), [lambda v: v >= 10, lambda v: v >= 5]),
            "Compliance": 1 if m.get("screening", {}).get("pep") else 0,
        }
        total = sum(factors.values())
        rating = 1 + min(9, round(total * 9 / 30))
        case.risk = {"scorecard": factors, "score": total, "max_score": 30, "rating": rating,
                     "grade": self.GRADE[rating], "pd_1y": self.PD[rating]}

        # Early warning signals the rules alone would not raise
        yearly = case.field("project_report", "dscr_by_year") or []
        if yearly and min(yearly) < self.kb.p("dscr_proj_min"):
            yr = yearly.index(min(yearly)) + 1
            case.findings.append(Finding(self.name, "risk", "medium", "Ramp-up year DSCR below policy floor",
                                         f"Projected DSCR in year {yr} is {min(yearly):.2f}x against the {self.kb.p('dscr_proj_min'):.2f}x floor; the average hides a thin first year.",
                                         "POL-2.3", case.ev("project_report", "dscr_by_year")))
        revs = [case.field("financials", f"revenue_fy{y}") for y in (2023, 2024, 2025)]
        mitigants = []
        if all(revs):
            cagr = (revs[2] / revs[0]) ** 0.5 - 1
            mitigants.append(f"revenue CAGR {cagr:.1%} over FY2023-25")
        if (case.field("financials", "audit_opinion") or "").lower().startswith("unqualified"):
            mitigants.append("unqualified audit opinion")
        if m.get("ltv", 1) <= self.kb.p("ltv_max"):
            mitigants.append(f"LTV {m['ltv']:.0%} within the {self.kb.p('ltv_max'):.0%} limit")
        if m.get("promoter_share", 0) >= 0.25:
            mitigants.append(f"promoter equity {m['promoter_share']:.0%} of project cost")

        obs = sorted([f for f in case.findings if f.severity != "info"], key=lambda f: -SEVERITY_ORDER[f.severity])
        case.risk["narrative"] = self.llm.write("risk_narrative", {
            "observations": [{"title": o.title, "severity": o.severity, "detail": o.detail,
                              "citations": [e.cite() for e in o.evidence] + ([f"[{o.policy_ref}]"] if o.policy_ref else [])} for o in obs],
            "mitigants": mitigants})
        case.risk["mitigants"] = mitigants
        return {"rating": rating, "grade": case.risk["grade"], "score": f"{total}/30", "observations": len(obs)}


# ---------------------------------------------------------------------------------------------
CONDITION_TEXT = {
    "POL-3.1": ("Obtain a fresh collateral valuation from an empanelled valuer, dated within 180 days", "Collateral Management", "pre-disbursement", 30),
    "POL-3.2": ("Obtain renewed identity documents for: {names}", "KYC Operations", "pre-disbursement", 21),
    "POL-2.3": ("Fund a Debt Service Reserve Account of 2 quarters' debt service and apply a 50% cash sweep while DSCR < {sweep:.2f}x", "Credit Administration", "pre-disbursement", 45),
    "POL-2.2": ("Financial covenant: Total Debt / EBITDA <= {lev:.1f}x, tested annually on audited accounts", "Portfolio Monitoring", "post-disbursement covenant", 365),
    "POL-5.1": ("RM to provide a written explanation of the returned items", "Relationship Manager", "pre-approval", 5),
    "POL-5.2": ("RM to reconcile bank credits with reported revenue and disclose other banking relationships", "Relationship Manager", "pre-approval", 5),
}


class ApprovalWorkflowAgent(Agent):
    """Recommends the next action, drafts conditions and routes to the right human approvers."""
    name = "Approval & Workflow Agent"

    def run(self, case: CaseFile) -> dict:
        app = case.application
        amount = app["facility"]["amount_usd"]
        crit = [f for f in case.findings if f.severity == "critical"]
        blocking = case.checklist.get("blocking_missing", [])
        open_items = [c for c in case.policy_checks if c.status in ("FAIL", "FLAG")]
        not_evaluated = [c for c in case.policy_checks if c.status == "NOT_EVALUATED"]

        if any(c.rule_id == "POL-3.3" and c.status == "FAIL" for c in case.policy_checks):
            rec, why = "DECLINE", "Confirmed sanctions match (POL-3.3)."
        elif crit:
            rec, why = "DECLINE", "Non-curable policy breach: " + "; ".join(f.title for f in crit)
        elif blocking:
            rec, why = "RETURN TO RM", "Blocking documents missing: " + ", ".join(b["title"] for b in blocking)
        elif not_evaluated:
            rec, why = "RETURN TO RM", "Mandatory checks could not be evaluated: " + ", ".join(c.rule_id for c in not_evaluated)
        elif case.risk["rating"] >= 9:
            rec, why = "DECLINE", f"Internal rating {case.risk['rating']} is outside risk appetite."
        elif open_items or any(f.status == "open" and f.severity in ("medium", "high") for f in case.findings):
            rec, why = "APPROVE WITH CONDITIONS", "Eligible; open items are curable and converted into conditions."
        else:
            rec, why = "APPROVE", "Meets all policy criteria with no material observations."

        conds: list[Condition] = []
        as_of = _d(case.as_of)
        if rec.startswith("APPROVE"):
            for c in open_items:
                if c.rule_id in CONDITION_TEXT:
                    text, owner, stage, days = CONDITION_TEXT[c.rule_id]
                    text = text.format(names=", ".join(d["name"] for d in case.metrics.get("kyc_expired", [])),
                                       sweep=self.kb.p("dscr_sweep_below"), lev=self.kb.p("leverage_max"))
                    conds.append(Condition("", text, c.ref, owner, str(as_of + timedelta(days=days)), stage))
            for mi in case.checklist.get("missing", []):
                if not mi["blocking"] and mi["title"] == DOC_LABELS.get(mi["doc"]):
                    conds.append(Condition("", f"Submit {mi['title'].lower()}", "POL-3.4 / POL-7.1", "Relationship Manager",
                                           str(as_of + timedelta(days=30)), "pre-disbursement"))
            for sf in [f for f in case.findings if f.category == "security"]:
                conds.append(Condition("", f"Analyst to review {sf.evidence[0].source} for tampering and confirm its origin with the RM "
                                       "(instruction-like text was quarantined)", "Security review", "Credit Analyst",
                                       str(as_of + timedelta(days=2)), "pre-approval"))
            if "dscr_proj" in case.metrics:
                conds.append(Condition("", f"Financial covenant: DSCR >= {self.kb.p('dscr_proj_min'):.2f}x, tested annually"
                                       + (" from the first full year after COD" if case.field("project_report", "cod") else ""),
                                       "POL-2.3", "Portfolio Monitoring", "annual", "post-disbursement covenant"))
            for i, c in enumerate(conds, 1):
                c.id = f"C{i:02d}"
        case.conditions = conds

        limits = self.kb.authority()
        authority = next(level for limit, level in limits if amount <= limit)
        exceptions = [c.rule_id for c in case.policy_checks if c.status == "FAIL"]
        escalated = rec == "APPROVE WITH CONDITIONS" and bool(exceptions)
        if escalated:   # POL-6.1: any facility with an open policy exception escalates one level
            levels = [lvl for _, lvl in limits]
            authority = levels[min(levels.index(authority) + 1, len(levels) - 1)]
        gates = []
        if case.checklist.get("edd_required"):
            gates.append({"gate": "compliance", "role": "Compliance Officer", "reason": "PEP match requires EDD sign-off before approval (POL-3.3)"})
        gates.append({"gate": "credit", "role": authority, "reason": f"Delegated authority for {_money(amount)} (POL-6.1)"
                      + (f"; escalated one level for open policy exceptions {', '.join(exceptions)}" if escalated else "")})
        case.checklist["gates"] = gates

        sev = [f.severity for f in case.findings]
        case.recommendation = {
            "action": rec, "reason": why, "authority": authority, "escalated_for_exceptions": exceptions if escalated else [],
            "summary": self.llm.write("decision_rationale", {
                "borrower": app["borrower"]["legal_name"], "facility_type": app["facility"]["type"], "amount": amount,
                "tenor": app["facility"]["tenor_months"], "purpose": app["facility"]["purpose"],
                "rating": case.risk["rating"], "grade": case.risk["grade"], "recommendation": rec,
                "n_conditions": len(conds), "n_high": sev.count("high") + sev.count("critical"), "n_medium": sev.count("medium"),
                "gates": [f"{g['role']} ({g['gate']})" for g in gates]}),
        }
        return {"recommendation": rec, "reason": why, "conditions": len(conds), "gates": [g["role"] for g in gates]}


# ---------------------------------------------------------------------------------------------
class DisbursementConditionAgent(Agent):
    """After approval: turns conditions into a tracker and sets disbursement readiness."""
    name = "Disbursement & Condition Monitoring Agent"

    def run(self, case: CaseFile) -> dict:
        final = case.human_decisions[-1]["decision"] if case.human_decisions else None
        if final not in ("APPROVE", "APPROVE WITH CONDITIONS"):
            return {"disbursement_status": "NOT APPLICABLE", "reason": f"final decision {final}"}
        pre = [c for c in case.conditions if c.stage in ("pre-approval", "pre-disbursement") and c.status == "open"]
        status = "BLOCKED: conditions precedent open" if pre else "READY FOR DISBURSEMENT"
        case.checklist["disbursement_status"] = status
        return {"disbursement_status": status, "open_conditions_precedent": [c.id for c in pre],
                "covenants_scheduled": [c.id for c in case.conditions if c.stage == "post-disbursement covenant"]}
