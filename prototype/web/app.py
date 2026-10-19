"""FastAPI web server wrapping the loan-lifecycle agent pipeline.

Start it from the prototype folder:
  python web/app.py                 # then open http://localhost:8000

Exposes:
  GET  /api/overview                – counts and latest eval headline for the home page
  GET  /api/applications            – sample applications and the 39 golden cases (real, corner, jailbreak)
  GET  /api/applications/<id>       – application JSON, documents (numbered lines), ground truth if golden
  POST /api/run/<id>                – start pipeline in background thread (approvers: web | scripted)
  GET  /api/stream/<sid>            – SSE stream of pipeline events
  POST /api/approve/<sid>           – submit human approval decision
  GET  /api/session/<id>            – current session status for an app
  GET  /api/results/<id>            – decision_record.json after completion (+ ground-truth comparison)
  GET  /api/audit/<id>              – audit_log.jsonl parsed
  GET  /api/audit/<id>/verified     – the same, with hash-chain verification
  GET  /api/evals                   – every saved eval run's summary
  POST /api/evals/run               – run the golden-set eval in the background
  GET  /api/evals/status            – progress / log of that run
  GET  /api/evals/report            – evals/results/REPORT.md
  POST /api/demos/<name>            – red-team, policy-change, tamper, replay
  GET  /api/rag/status              – RAG layer status (vector_ready, embed_model, collection, …)
  GET  /api/policy/docs             – list all policy documents with metadata
  GET  /api/policy/docs/{name}      – fetch markdown content of a policy document
  PUT  /api/policy/docs/{name}      – save updated markdown content (triggers RAG re-index)
  GET  /                            – serves the SPA (static/index.html)
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Path setup ────────────────────────────────────────────────────────────────
import sys
PROTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROTO))


# ── Load environment from .env.local (secrets) then .env (defaults) ──────────
def _load_env(*paths: Path) -> None:
    """Parse KEY=VALUE lines from env files. Already-set env vars take precedence."""
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:   # never overwrite a key set in the shell
                os.environ[k] = v


_load_env(PROTO / ".env.local", PROTO / ".env")

from loanagent.audit import verify_chain      # noqa: E402
from loanagent.orchestrator import (          # noqa: E402
    CREDIT_DECISIONS, COMPLIANCE_DECISIONS,
    ScriptedApprover, run_case, validate_human_action,
)
from loanagent.rag import get_knowledge_base  # noqa: E402

DATA    = PROTO / "data" / "applications"
GOLDEN  = PROTO / "evals" / "golden"
RESULTS = PROTO / "evals" / "results"
OUT     = PROTO / "output"
AS_OF   = "2026-10-16"                       # fixed decision date so runs are reproducible
OUT.mkdir(exist_ok=True)


def case_source(app_id: str) -> dict:
    """Where a case's inputs live and how it is run. Sample cases and golden cases share one id space."""
    if "/" in app_id or "\\" in app_id or ".." in app_id:
        raise HTTPException(404, "Application not found")
    if (DATA / app_id / "application.json").exists():
        return {"kind": "sample", "dir": DATA / app_id, "out_root": OUT, "as_of": AS_OF, "watchlist": None}
    if (GOLDEN / app_id / "application.json").exists():
        gt = json.loads((GOLDEN / app_id / "ground_truth.json").read_text())
        return {"kind": "golden", "dir": GOLDEN / app_id, "out_root": OUT / "golden", "as_of": gt["as_of"],
                "watchlist": GOLDEN / "screening_watchlist.json", "ground_truth": gt}
    raise HTTPException(404, "Application not found")


def out_dir(app_id: str) -> Path:
    return case_source(app_id)["out_root"] / app_id


# ── Knowledge base cache (built once at startup, reused per request) ──────────
_kb_cache: dict = {}   # sha256 → HybridPolicyKB instance

def _get_cached_kb(policy_dir: Path, as_of: str, policy_version=None):
    kb = get_knowledge_base(policy_dir, as_of, policy_version)
    key = kb.sha256
    if key not in _kb_cache:
        _kb_cache[key] = kb
    return _kb_cache[key]


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Loan Lifecycle Manager")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _warm_kb():
    """Pre-build / verify the Qdrant vector index at server startup so the first
    pipeline run is not penalised by the index-build time."""
    try:
        _get_cached_kb(PROTO / "data" / "policy", AS_OF)
    except Exception:
        pass  # non-fatal; pipeline will build on demand

# ── Session store (in-process; fine for demo) ─────────────────────────────────
_sessions:  dict[str, "Session"] = {}
_app_sid:   dict[str, str]       = {}   # app_id → latest session id


class Session:
    def __init__(self, app_id: str, llm_mode: str = "auto", approver: str = "web"):
        self.id          = uuid.uuid4().hex[:8]
        self.app_id      = app_id
        self.llm_mode    = llm_mode
        self.approver    = approver         # web (you decide) | scripted (recorded approvers)
        self.status      = "pending"        # pending|running|awaiting_approval|complete|error
        self._q: queue.Queue = queue.Queue()
        # Human gate state
        self._orig_gate            = None   # exact gate dict for validate_human_action
        self.pending_gate_info: Optional[dict] = None   # display payload for UI
        self.pending_case          = None
        self._resp_ev              = threading.Event()
        self._resp: Optional[dict] = None
        # Results
        self.error: Optional[str]  = None

    def push(self, ev: dict) -> None:
        self._q.put(ev)


# ── Approvers ─────────────────────────────────────────────────────────────────
class WebApprover:
    """Parks the pipeline at each human gate until someone decides in the browser."""

    def __init__(self, s: Session):
        self.s = s

    def ask(self, gate: dict, case, attempt: int) -> dict:
        self.s._orig_gate       = gate
        self.s.pending_gate_info = {
            "gate_type":     gate["gate"],          # "compliance" | "credit"
            "required_role": gate["role"],
            "reason":        gate.get("reason", ""),
            "attempt":       attempt,
            "analyst":       case.application.get("credit_analyst"),
            "recommendation": (case.recommendation or {}).get("action"),
            "recommendation_reason": (case.recommendation or {}).get("reason"),
            "risk_rating":   (case.risk or {}).get("rating"),
            "risk_grade":    (case.risk or {}).get("grade"),
            "pep_hits": [
                h for h in case.metrics.get("screening", {}).get("pep", [])
            ] if gate["gate"] == "compliance" else [],
        }
        self.s.pending_case = case
        self.s.status       = "awaiting_approval"
        self.s.push({"type": "gate", "data": self.s.pending_gate_info})

        self.s._resp_ev.clear()
        if not self.s._resp_ev.wait(timeout=1800):
            raise TimeoutError("Approval timed out after 30 minutes")

        resp = self.s._resp
        self.s._resp   = None
        self.s.status  = "running"
        self.s.push({"type": "status", "data": {"status": "running"}})
        return resp


class AutoApprover:
    """For golden cases: the analyst tries to approve their own case (blocked), then the routed role
    accepts the recommendation. Same pattern the eval harness uses."""

    def ask(self, gate: dict, case, attempt: int) -> dict:
        if attempt == 0:
            role = ("Compliance Officer" if gate["gate"] == "compliance"
                    else "Senior Analyst" if gate["gate"] == "data_validation"
                    else gate["role"])
            decision = ("EDD CLEARED" if gate["gate"] == "compliance"
                        else "PROCEED" if gate["gate"] == "data_validation"
                        else case.recommendation["action"])
            return {"name": case.application["credit_analyst"], "role": role, "decision": decision,
                    "rationale": "Analyst approving own proposal."}
        if gate["gate"] == "compliance":
            return {"name": "Grace Mwangi", "role": "Compliance Officer", "decision": "EDD CLEARED",
                    "rationale": "EDD completed: source of wealth verified, no adverse findings on the individual."}
        if gate["gate"] == "data_validation":
            return {"name": "Priya Iyer", "role": "Senior Analyst", "decision": "PROCEED",
                    "rationale": "Extracted fields verified against source documents."}
        return {"name": "Sofia Alvarez", "role": gate["role"], "decision": case.recommendation["action"],
                "rationale": "Accepting the recommendation after reviewing the cited evidence."}


def scripted_approver(app_id: str):
    script = json.loads((PROTO / "data" / "demo_approvals.json").read_text())
    if app_id in script:
        return ScriptedApprover(script[app_id])
    return AutoApprover()


# ── Audit tailer ──────────────────────────────────────────────────────────────
def _tail_audit(session: Session, audit_path: Path) -> None:
    """Tail audit_log.jsonl and push progress events to the session queue."""
    deadline = time.monotonic() + 60
    while not audit_path.exists():
        if time.monotonic() > deadline or session.status in ("complete", "error"):
            break
        time.sleep(0.15)

    pos = 0
    while True:
        finished = session.status in ("complete", "error")
        try:
            size = audit_path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size > pos:
            with audit_path.open(encoding="utf-8") as f:
                f.seek(pos)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            e = json.loads(line)
                            session.push({
                                "type": "progress",
                                "data": {
                                    "seq":        e.get("seq"),
                                    "actor":      e.get("actor"),
                                    "actor_type": e.get("actor_type"),
                                    "action":     e.get("action"),
                                    "outputs":    e.get("outputs", {}),
                                    "ts":         e.get("ts"),
                                },
                            })
                        except Exception:
                            pass
                pos = f.tell()
        if finished:
            break
        time.sleep(0.2)


# ── Pipeline runner ───────────────────────────────────────────────────────────
def _run_pipeline(session: Session) -> None:
    src = case_source(session.app_id)
    audit_path = src["out_root"] / session.app_id / "audit_log.jsonl"
    if audit_path.exists():
        audit_path.unlink()             # so the tailer only streams this run
    tailer = threading.Thread(target=_tail_audit, args=(session, audit_path), daemon=True)
    tailer.start()

    try:
        session.status = "running"
        session.push({"type": "status", "data": {"status": "running"}})
        approver = WebApprover(session) if session.approver == "web" else scripted_approver(session.app_id)
        try:
            cached_kb = _get_cached_kb(PROTO / "data" / "policy", src["as_of"])
        except Exception:
            cached_kb = None
        run_case(
            app_dir        = src["dir"],
            approver       = approver,
            out_root       = src["out_root"],
            as_of          = src["as_of"],
            llm_mode       = session.llm_mode,
            watchlist_path = src["watchlist"],
            verbose        = False,
            kb             = cached_kb,
        )
        session.status = "complete"
        tailer.join(timeout=3)
        session.push({"type": "status",   "data": {"status": "complete"}})
        session.push({"type": "complete", "data": {}})
    except Exception as exc:
        import traceback
        session.error  = str(exc)
        session.status = "error"
        session.push({"type": "error", "data": {
            "message": str(exc),
            "detail":  traceback.format_exc()[-600:],
        }})
    finally:
        session._q.put(None)    # sentinel → close SSE


# ── REST endpoints: cases ─────────────────────────────────────────────────────
def _summary(d: Path, kind: str, extra: dict) -> dict:
    data = json.loads((d / "application.json").read_text())
    rf = (OUT if kind == "sample" else OUT / "golden") / d.name / "decision_record.json"
    rec = json.loads(rf.read_text()) if rf.exists() else None
    return {
        "id":            d.name,
        "kind":          kind,
        "borrower":      data["borrower"]["legal_name"],
        "sector":        data["borrower"].get("sector"),
        "amount_usd":    data["facility"]["amount_usd"],
        "facility_type": data["facility"]["type"],
        "submitted_on":  data.get("submitted_on"),
        "rm":            data.get("relationship_manager"),
        "analyst":       data.get("credit_analyst"),
        "channel":       data.get("channel"),
        "has_result":    rec is not None,
        "final_status":  rec.get("final_status") if rec else None,
        "recommendation": (rec or {}).get("recommendation", {}).get("action"),
        **extra,
    }


@app.get("/api/applications")
def list_applications():
    result = []
    for d in sorted(DATA.iterdir()):
        if d.is_dir() and (d / "application.json").exists():
            result.append(_summary(d, "sample", {}))
    for d in sorted(GOLDEN.glob("GS-*")):
        if d.is_dir() and (d / "ground_truth.json").exists():
            gt = json.loads((d / "ground_truth.json").read_text())
            result.append(_summary(d, "golden", {
                "category": gt.get("category"), "style": gt["style"], "planted": gt["planted"],
                "expected_recommendation": gt["recommendation"], "expected_gates": gt["gates"],
            }))
    return result


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def auth_login(body: LoginRequest):
    """Validate credentials and return role + display name."""
    DEMO_PASSWORD = "demo123"
    if body.password != DEMO_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if body.username.lower() == "newuser":
        return {"role": "applicant", "name": "New User", "username": "newuser"}
    # Approver accounts — username is first.last (case-insensitive)
    for a in list_approvers():
        parts = a["name"].split()
        if len(parts) >= 2:
            if body.username.lower() == f"{parts[0].lower()}.{parts[-1].lower()}":
                return {"role": "admin", "name": a["name"], "username": body.username.lower(), "approver_role": a["role"]}
    raise HTTPException(status_code=401, detail="Invalid credentials. Admins: first.last / demo123  ·  New users: newuser / demo123")


class NewApplicationRequest(BaseModel):
    # Borrower
    borrower_name: str
    sector: str
    country: str
    registration_no: str = ""
    incorporated_on: str = ""
    existing_exposure_usd: float = 0.0
    # People
    relationship_manager: str = "Portal RM"
    credit_analyst: str = "Credit Analyst"
    rm_notes: str = ""
    # Facility
    facility_type: str
    amount_usd: float
    tenor_months: int
    purpose: str
    proposed_rate: str = "SOFR + 3.00%"
    security: str = ""
    # Document text content
    doc_financials: str = ""
    doc_bank_statement: str = ""
    doc_valuation: str = ""
    doc_kyc: str = ""
    doc_project_report: str = ""


@app.post("/api/applications")
def create_application(req: NewApplicationRequest):
    import datetime
    year = datetime.date.today().year
    existing_nums = []
    for d in DATA.iterdir():
        if d.is_dir() and d.name.startswith("APP-"):
            parts = d.name.split("-")
            if len(parts) == 3:
                try:
                    existing_nums.append(int(parts[2]))
                except ValueError:
                    pass
    next_num = max(existing_nums, default=1000) + 1
    app_id = f"APP-{year}-{next_num:04d}"
    app_dir = DATA / app_id
    doc_dir = app_dir / "documents"
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_map = {
        "doc_financials":     "audited_financials.txt",
        "doc_bank_statement": "bank_statement_summary.txt",
        "doc_valuation":      "collateral_valuation.txt",
        "doc_kyc":            "kyc_ubo_declaration.txt",
        "doc_project_report": "project_report.txt",
    }
    # Classifier keyword that must appear in each document type for it to be recognised
    _doc_kw = {
        "doc_financials":     "AUDITED FINANCIAL STATEMENTS",
        "doc_bank_statement": "STATEMENT SUMMARY",
        "doc_valuation":      "VALUATION REPORT",
        "doc_kyc":            "KYC DECLARATION",
        "doc_project_report": "PROJECT REPORT",
    }
    declared = []
    for field, filename in doc_map.items():
        content = (getattr(req, field) or "").strip()
        if content:
            kw = _doc_kw.get(field, "")
            if kw and kw not in content.upper():
                content = kw + "\n\n" + content
            (doc_dir / filename).write_text(content, encoding="utf-8")
            declared.append(filename)
    application = {
        "application_id": app_id,
        "submitted_on": str(datetime.date.today()),
        "channel": "Web portal",
        "relationship_manager": req.relationship_manager,
        "credit_analyst": req.credit_analyst,
        "borrower": {
            "legal_name": req.borrower_name,
            "registration_no": req.registration_no,
            "incorporated_on": req.incorporated_on,
            "sector": req.sector,
            "country": req.country,
            "existing_group_exposure_usd": req.existing_exposure_usd,
        },
        "facility": {
            "type": req.facility_type,
            "amount_usd": req.amount_usd,
            "tenor_months": req.tenor_months,
            "purpose": req.purpose,
            "proposed_rate": req.proposed_rate,
            "security": req.security,
        },
        "declared_documents": declared,
        "rm_notes": req.rm_notes,
    }
    (app_dir / "application.json").write_text(json.dumps(application, indent=2), encoding="utf-8")
    return {"app_id": app_id}


@app.delete("/api/applications/{app_id}")
def delete_application(app_id: str):
    """Remove a user-created sample application (not golden cases)."""
    if "/" in app_id or "\\" in app_id or ".." in app_id:
        raise HTTPException(400, "Invalid id")
    d = DATA / app_id
    if not d.exists():
        raise HTTPException(404, "Application not found")
    import shutil
    shutil.rmtree(d)
    return {"deleted": app_id}


@app.get("/api/applications/{app_id}")
def get_application(app_id: str):
    src = case_source(app_id)
    body = json.loads((src["dir"] / "application.json").read_text())
    docs = {p.name: p.read_text(encoding="utf-8").splitlines() for p in sorted((src["dir"] / "documents").glob("*.txt"))}
    return {"application": body, "documents": docs, "kind": src["kind"], "as_of": src["as_of"],
            "ground_truth": src.get("ground_truth")}


def _compare(rec: dict, gt: dict) -> dict:
    actual = {c["rule_id"]: c["status"] for c in rec.get("policy_checks", [])}
    checks = [{"rule_id": k, "expected": v, "actual": actual.get(k, "ABSENT"), "match": actual.get(k) == v}
              for k, v in gt["policy_checks"].items()]
    routes = [g["role"] for g in rec.get("gates", []) if g["gate"] == "credit"]
    return {
        "recommendation": {"expected": gt["recommendation"], "actual": rec["recommendation"]["action"],
                           "match": gt["recommendation"] == rec["recommendation"]["action"]},
        "route": {"expected": gt["gates"], "actual": routes, "match": routes == gt["gates"]},
        "checks": checks,
        "checks_matched": sum(c["match"] for c in checks),
        "planted": gt["planted"], "style": gt["style"], "category": gt.get("category"),
    }


@app.get("/api/results/{app_id}")
def get_results(app_id: str):
    src = case_source(app_id)
    f = src["out_root"] / app_id / "decision_record.json"
    if not f.exists():
        raise HTTPException(404, "Results not found — run the pipeline first")
    rec = json.loads(f.read_text())
    ef = f.parent / "extracted_fields.json"
    rec["extracted_fields"] = json.loads(ef.read_text()) if ef.exists() else {}
    sm = f.parent / "decision_summary.md"
    rec["summary_md"] = sm.read_bytes().decode("utf-8", errors="replace") if sm.exists() else ""
    if src["kind"] == "golden":
        rec["ground_truth_comparison"] = _compare(rec, src["ground_truth"])
    return rec


@app.get("/api/my-applications")
def get_my_applications():
    """Return all apps submitted via the Web portal, newest first, with their current status."""
    results = []
    for folder in sorted(OUT.iterdir(), reverse=True):
        rec_path = folder / "decision_record.json"
        if not rec_path.exists():
            continue
        try:
            rec = json.loads(rec_path.read_text())
            app = rec.get("application", {})
            if app.get("channel") != "Web portal":
                continue
            facility = app.get("facility", {})
            preDisb = [c for c in rec.get("conditions", []) if c.get("stage") != "post-disbursement covenant"]
            fail_checks = [
                {"rule_id": c["rule_id"], "name": c.get("name",""), "actual": c.get("actual",""),
                 "threshold": c.get("threshold",""), "status": c.get("status","")}
                for c in rec.get("policy_checks", []) if c.get("status") in ("FAIL", "FLAG")
            ]
            hitl_cleared = False
            hitl_reason = ""
            for h in rec.get("human_decisions", []):
                if h.get("gate") == "data_validation" and h.get("decision") == "PROCEED":
                    hitl_cleared = True
                    for g in rec.get("gates", []):
                        if g.get("gate") == "data_validation":
                            hitl_reason = g.get("reason", "")
                    break
            results.append({
                "app_id":         rec.get("case_id"),
                "borrower_name":  app.get("borrower", {}).get("legal_name", ""),
                "facility":       (facility.get("type", "") + " · USD " +
                                   f"{facility.get('amount_usd', 0):,.0f}"),
                "submitted_at":   app.get("submitted_on", ""),
                "status":         "complete",
                "decision":       rec.get("final_status"),
                "conditions":     len(preDisb),
                "conditionList":  preDisb,
                "declineReason":  rec.get("recommendation", {}).get("reason", ""),
                "failChecks":     fail_checks,
                "hitlCleared":    hitl_cleared,
                "hitlReason":     hitl_reason,
            })
        except Exception:
            continue

    # Also include any active sessions awaiting approval (portal apps not yet decided)
    seen_ids = {r["app_id"] for r in results}
    for app_id, sid in list(_app_sid.items()):
        s = _sessions.get(sid)
        if not s or s.status not in ("running", "awaiting_approval"):
            continue
        if app_id in seen_ids:
            continue
        # Only include portal apps
        try:
            src = case_source(app_id)
            app_data = json.loads((src["dir"] / "application.json").read_text())
            if app_data.get("channel") != "Web portal":
                continue
            b = app_data.get("borrower", {})
            fac = app_data.get("facility", {})
            gate = (s.pending_gate_info or {}) if s.status == "awaiting_approval" else {}
            results.insert(0, {
                "app_id": app_id,
                "borrower_name": b.get("legal_name", app_id),
                "facility": fac.get("type", "") + " · USD " + f"{fac.get('amount_usd', 0):,.0f}",
                "submitted_at": app_data.get("submitted_on", ""),
                "status": s.status,
                "decision": None,
                "conditions": 0,
                "conditionList": [],
                "declineReason": "",
                "failChecks": [],
                "hitlCleared": False,
                "hitlReason": "",
                "pendingGate": gate.get("gate_type", "") if gate else "",
                "requiredRole": gate.get("required_role", "") if gate else "",
                "recommendation": gate.get("recommendation", "") if gate else "",
            })
            seen_ids.add(app_id)
        except Exception:
            continue
    return results


@app.get("/api/audit/{app_id}")
def get_audit_log(app_id: str):
    f = out_dir(app_id) / "audit_log.jsonl"
    if not f.exists():
        raise HTTPException(404, "Audit log not found")
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


@app.get("/api/audit/{app_id}/verified")
def get_audit_verified(app_id: str):
    """Audit log plus hash-chain verification, for the home-page UI."""
    f = out_dir(app_id) / "audit_log.jsonl"
    if not f.exists():
        raise HTTPException(404, "Audit log not found")
    ok, msg = verify_chain(f)
    return {"entries": get_audit_log(app_id), "chain_ok": ok, "chain_message": msg}


@app.get("/api/pending-approvals")
def get_pending_approvals():
    """Active sessions that are paused at a human gate, waiting for admin approval."""
    result = []
    for app_id, sid in list(_app_sid.items()):
        s = _sessions.get(sid)
        if not s or s.status != "awaiting_approval":
            continue
        gate = s.pending_gate_info or {}
        # Get borrower name from application
        borrower = app_id
        amount_usd = 0
        try:
            src = case_source(app_id)
            app_data = json.loads((src["dir"] / "application.json").read_text())
            borrower = app_data.get("borrower", {}).get("legal_name", app_id)
            amount_usd = app_data.get("facility", {}).get("amount_usd", 0)
        except Exception:
            pass
        result.append({
            "app_id": app_id,
            "session_id": sid,
            "borrower": borrower,
            "amount_usd": amount_usd,
            "gate_type": gate.get("gate_type"),
            "required_role": gate.get("required_role"),
            "reason": gate.get("reason", ""),
            "recommendation": gate.get("recommendation"),
            "risk_rating": gate.get("risk_rating"),
            "risk_grade": gate.get("risk_grade"),
        })
    return result


class RunRequest(BaseModel):
    llm_mode: str = "auto"
    approver: str = "web"


@app.post("/api/run/{app_id}")
def start_run(app_id: str, req: RunRequest = RunRequest()):
    case_source(app_id)
    if req.llm_mode not in ("auto", "mock", "claude", "openrouter", "low_confidence") or req.approver not in ("web", "scripted"):
        raise HTTPException(400, "Bad run options")
    if req.llm_mode == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "Set ANTHROPIC_API_KEY to use Claude directly")
    if req.llm_mode == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        raise HTTPException(400, "Set OPENROUTER_API_KEY to use OpenRouter")
    s = Session(app_id, req.llm_mode, req.approver)
    _sessions[s.id] = s
    _app_sid[app_id] = s.id
    threading.Thread(target=_run_pipeline, args=(s,), daemon=True).start()
    return {"session_id": s.id}


@app.get("/api/stream/{session_id}")
async def event_stream(session_id: str):
    s = _sessions.get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    async def generate():
        loop = asyncio.get_event_loop()
        while True:
            try:
                ev = await loop.run_in_executor(None, lambda: s._q.get(timeout=25))
            except Exception:
                yield "data: {\"type\":\"ping\"}\n\n"
                continue
            if ev is None:
                yield "data: {\"type\":\"done\"}\n\n"
                break
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ApproveRequest(BaseModel):
    name:      str
    role:      str
    decision:  str
    rationale: str


@app.post("/api/approve/{session_id}")
def submit_approval(session_id: str, body: ApproveRequest):
    s = _sessions.get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if s.status != "awaiting_approval":
        raise HTTPException(400, "Session is not awaiting approval")

    action = body.model_dump()
    errors = validate_human_action(s._orig_gate, action, s.pending_case)
    if errors:
        return {"ok": False, "errors": errors}

    s._resp = action
    s._resp_ev.set()
    return {"ok": True}


@app.get("/api/session/{app_id}")
def get_session_status(app_id: str):
    sid = _app_sid.get(app_id)
    if not sid or sid not in _sessions:
        return {"session_id": None, "status": "idle", "pending_gate": None}
    s = _sessions[sid]
    return {
        "session_id":   sid,
        "status":       s.status,
        "pending_gate": s.pending_gate_info,
        "error":        s.error,
    }


@app.get("/api/decisions")
def decision_options():
    return {"credit": CREDIT_DECISIONS, "compliance": COMPLIANCE_DECISIONS}


@app.get("/api/decision-log")
def decision_log():
    """All completed human decisions across every case, with timestamps from the audit log."""
    rows = []
    seen_ids: set[str] = set()  # deduplicate: demo sub-runs (redteam/, policy-change/) share case_ids
    # scan both sample output and golden output dirs
    search_roots = [OUT, OUT / "golden"]
    for root in search_roots:
        if not root.exists():
            continue
        # Only direct children of root, not nested demo sub-runs
        for rec_path in sorted(p / "decision_record.json" for p in root.iterdir()
                               if p.is_dir() and (p / "decision_record.json").exists()):
            try:
                rec = json.loads(rec_path.read_text())
            except Exception:
                continue
            if not rec.get("human_decisions"):
                continue
            cid = rec.get("case_id", "")
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            # build a ts map from the audit log: action -> ts
            ts_map: dict[str, str] = {}
            audit_path = rec_path.parent / "audit_log.jsonl"
            if audit_path.exists():
                for line in audit_path.read_text().splitlines():
                    try:
                        e = json.loads(line)
                        if e.get("actor_type") == "human" and "decision" in e.get("action", ""):
                            key = f"{e['actor']}:{e['action']}"
                            ts_map[key] = e.get("ts", "")
                    except Exception:
                        pass
            app_data = rec.get("application", {})
            b = app_data.get("borrower", {})
            f = app_data.get("facility", {})
            decisions = []
            for h in rec["human_decisions"]:
                gate_action = f"{h['gate']}_decision"
                key = f"{h['name']}:{gate_action}"
                decisions.append({
                    "gate": h["gate"],
                    "decided_by": h["name"],
                    "role": h["role"],
                    "required_role": h.get("required_role", ""),
                    "decision": h["decision"],
                    "rationale": h.get("rationale", ""),
                    "override": h.get("override", False),
                    "decided_at": ts_map.get(key, rec.get("as_of", "")),
                })
            rows.append({
                "case_id": rec["case_id"],
                "borrower": b.get("legal_name", rec["case_id"]),
                "sector": b.get("sector", ""),
                "facility_type": f.get("type", ""),
                "amount_usd": f.get("amount_usd", 0),
                "final_status": rec.get("final_status", ""),
                "as_of": rec.get("as_of", ""),
                "decisions": decisions,
            })
    # newest first
    rows.sort(key=lambda r: r["as_of"] or "", reverse=True)
    return rows


@app.get("/api/approvers")
def list_approvers():
    """Deduplicated list of {name, role} from demo_approvals.json, sorted by role then name."""
    raw = json.loads((PROTO / "data" / "demo_approvals.json").read_text())
    seen: dict[str, str] = {}
    for case in raw.values():
        if isinstance(case, dict):
            for gate_entries in case.values():
                for entry in gate_entries:
                    if isinstance(entry, dict) and "name" in entry and "role" in entry:
                        seen[entry["name"]] = entry["role"]
    order = ["Compliance Officer", "Senior Analyst", "Senior Credit Manager", "Regional Credit Committee", "Board Credit Committee", "Credit Analyst"]
    approvers = sorted(seen.items(), key=lambda x: (order.index(x[1]) if x[1] in order else 99, x[0]))
    return [{"name": n, "role": r} for n, r in approvers]


@app.get("/api/rag/status")
def rag_status():
    """Return the RAG layer status: whether vector search (Qdrant + Voyage AI) is active."""
    from loanagent.rag import get_knowledge_base, _auth_key, QDRANT_DEFAULT_URL, _Qdrant
    import os
    from datetime import date
    key_set = bool(_auth_key())
    qdrant_url = os.environ.get("QDRANT_URL", QDRANT_DEFAULT_URL)
    qdrant_api_key = os.environ.get("QDRANT_API_KEY", "")
    qdrant_alive = _Qdrant(qdrant_url, api_key=qdrant_api_key).alive() if key_set else False
    if key_set and qdrant_alive:
        try:
            kb = get_knowledge_base(PROTO / "data" / "policy", date.today().isoformat())
            if hasattr(kb, "rag_status"):
                return kb.rag_status()
        except Exception as exc:
            return {"vector_ready": False, "error": str(exc), "key_set": key_set, "qdrant_alive": qdrant_alive}
    return {
        "vector_ready": False,
        "key_set": key_set,
        "qdrant_alive": qdrant_alive,
        "qdrant_url": qdrant_url,
        "error": (None if key_set and qdrant_alive else
                  ("No OPENROUTER_API_KEY / VOYAGE_API_KEY / ANTHROPIC_API_KEY" if not key_set else f"Qdrant not reachable at {qdrant_url}")),
    }


# ── Policy document library ──────────────────────────────────────────────────
POLICY_DOCS_DIR = PROTO / "data" / "policy" / "docs"
POLICY_MAIN_DIR = PROTO / "data" / "policy"

_POLICY_DISPLAY_NAMES = {
    "credit_policy.md": "Commercial Credit Policy",
    "credit_policy_v3.3.md": "Commercial Credit Policy v3.3",
    "delegation_of_authority.md": "Delegation of Authority Matrix",
    "kyc_aml_cdd_policy.md": "KYC, AML & Customer Due Diligence",
    "enhanced_due_diligence_pep.md": "Enhanced Due Diligence & PEP Procedure",
    "sanctions_screening.md": "Sanctions Screening Procedure",
    "collateral_valuation_policy.md": "Collateral & Valuation Policy",
    "risk_rating_methodology.md": "Internal Risk Rating Methodology",
    "risk_appetite_concentration.md": "Risk Appetite Statement & Concentration Limits",
    "product_programme_guide.md": "Product Programme Guide & Conditions Library",
}


def _count_clauses(content: str) -> int:
    import re
    return len(re.findall(r"^### [A-Z]{2,4}-\d+\.\d+", content, re.MULTILINE))


@app.get("/api/policy/docs")
def list_policy_docs():
    """List all policy documents (main versioned + docs library), with metadata."""
    import re
    result = []
    # Main versioned files
    for fname in ["credit_policy.md", "credit_policy_v3.3.md"]:
        p = POLICY_MAIN_DIR / fname
        if p.exists():
            content = p.read_text(encoding="utf-8")
            result.append({
                "name": fname,
                "display_name": _POLICY_DISPLAY_NAMES.get(fname, fname),
                "folder": "versioned",
                "editable": True,
                "clause_count": _count_clauses(content),
                "size_bytes": p.stat().st_size,
                "last_modified": int(p.stat().st_mtime * 1000),
            })
    # Supplementary docs
    if POLICY_DOCS_DIR.exists():
        for p in sorted(POLICY_DOCS_DIR.glob("*.md")):
            content = p.read_text(encoding="utf-8")
            result.append({
                "name": p.name,
                "display_name": _POLICY_DISPLAY_NAMES.get(p.name, p.stem.replace("_", " ").title()),
                "folder": "docs",
                "editable": True,
                "clause_count": _count_clauses(content),
                "size_bytes": p.stat().st_size,
                "last_modified": int(p.stat().st_mtime * 1000),
            })
    return result


@app.get("/api/policy/docs/{name}")
def get_policy_doc(name: str):
    """Return the raw markdown content of a policy document."""
    # Prevent path traversal
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid name")
    for folder in [POLICY_DOCS_DIR, POLICY_MAIN_DIR]:
        p = folder / name
        if p.exists() and p.suffix == ".md":
            content = p.read_text(encoding="utf-8")
            return {
                "name": name,
                "display_name": _POLICY_DISPLAY_NAMES.get(name, name),
                "folder": "docs" if folder == POLICY_DOCS_DIR else "versioned",
                "content": content,
                "clause_count": _count_clauses(content),
                "last_modified": int(p.stat().st_mtime * 1000),
            }
    raise HTTPException(status_code=404, detail="Document not found")


class PolicyDocBody(BaseModel):
    content: str


@app.put("/api/policy/docs/{name}")
def save_policy_doc(name: str, body: PolicyDocBody):
    """Save updated markdown content for a policy document."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid name")
    for folder in [POLICY_DOCS_DIR, POLICY_MAIN_DIR]:
        p = folder / name
        if p.exists() and p.suffix == ".md":
            p.write_text(body.content, encoding="utf-8")
            return {
                "ok": True,
                "name": name,
                "clause_count": _count_clauses(body.content),
                "last_modified": int(p.stat().st_mtime * 1000),
                "note": "RAG index will be rebuilt automatically on next pipeline run (SHA-256 changed).",
            }
    raise HTTPException(status_code=404, detail="Document not found")


# ── Background jobs (evals and demos run the project's own scripts) ───────────
_jobs: dict[str, dict] = {}


def _start_job(key: str, cmds: list[list[str]]) -> dict:
    job = _jobs.get(key)
    if job and job["status"] == "running":
        return job
    job = {"status": "running", "log": "", "started": time.time(), "returncode": None}
    _jobs[key] = job

    def work():
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        for cmd in cmds:
            job["log"] += "$ " + " ".join(cmd[1:]) + "\n"
            p = subprocess.Popen([sys.executable, *cmd[1:]], cwd=PROTO, env=env, text=True, encoding="utf-8",
                                 errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in p.stdout:
                job["log"] += line
            p.wait()
            job["returncode"] = p.returncode
            if p.returncode != 0:
                break
        job["status"] = "done" if job["returncode"] == 0 else "failed"
        job["seconds"] = round(time.time() - job["started"], 1)

    threading.Thread(target=work, daemon=True).start()
    return job


CATEGORIES = ("real", "corner", "jailbreak")


def _category_of(case_id: str):
    gt = GOLDEN / case_id / "ground_truth.json"
    return json.loads(gt.read_text()).get("category") if gt.exists() else None


def _by_category(cases: list[dict]) -> dict:
    """Same breakdown as evals/run_evals.py writes into summary.by_category."""
    def pct(a, b):
        return round(100 * a / b, 1) if b else None
    out = {}
    for k in CATEGORIES:
        g = [c for c in cases if c.get("category") == k and "error" not in c]
        if not g:
            continue
        crit = [f for c in g for f in c["fields"] if f["critical"]]
        pol = [v for c in g for v in c["policy"].values()]
        out[k] = {"cases": len(g),
                  "recommendation_agreement_pct": pct(sum(c["recommendation"]["expected"] == c["recommendation"]["actual"] for c in g), len(g)),
                  "unsafe_recommendations": sum(c["recommendation"]["unsafe"] for c in g),
                  "policy_status_exact_pct": pct(sum(v["expected"] == v["actual"] for v in pol), len(pol)),
                  "injection_detected": sum(bool(c["findings"].get("prompt_injection_detected")) for c in g),
                  "critical_field_accuracy_pct": pct(sum(f["correct"] for f in crit), len(crit))}
    return out


@app.get("/api/evals")
def list_evals():
    runs = []
    for d in sorted(RESULTS.iterdir()) if RESULTS.exists() else []:
        f = d / "results.json"
        if f.exists():
            r = json.loads(f.read_text())
            s = {k: v for k, v in r["summary"].items() if k != "per_clause"}
            for c in r["cases"]:      # runs recorded before categories existed take them from the golden set
                c["category"] = c.get("category") or _category_of(c["case_id"])
            if "by_category" not in s:
                s["by_category"] = _by_category(r["cases"])
            cases = [{k: c.get(k) for k in ("case_id", "category", "style", "planted", "recommendation", "routing", "error", "seconds")}
                     for c in r["cases"]]
            runs.append({"label": r["label"], "llm": r["llm"], "run_at": r.get("run_at"), "summary": s,
                         "per_clause": r["summary"].get("per_clause", {}), "cases": cases})
    return runs


class EvalRequest(BaseModel):
    llm: str = "mock"
    only: str = ""


@app.post("/api/evals/run")
def run_evals(req: EvalRequest = EvalRequest()):
    if req.llm not in ("mock", "claude", "openrouter"):
        raise HTTPException(400, "llm must be mock, claude, or openrouter")
    if req.llm == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "Set ANTHROPIC_API_KEY to run evals with Claude")
    if req.llm == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        raise HTTPException(400, "Set OPENROUTER_API_KEY to run evals with OpenRouter")
    if req.llm == "mock":
        label = "mock"
    elif req.llm == "openrouter":
        label = os.environ.get("LOAN_AGENT_MODEL", "openrouter").replace("/", "-")
    else:
        label = "claude-live"
    cmd = ["python", "evals/run_evals.py", "--llm", req.llm, "--label", label]
    if req.only:
        cmd += ["--only", req.only]
    return _start_job("evals", [cmd, ["python", "evals/run_evals.py", "--report"]])


@app.get("/api/evals/status")
def eval_status():
    return _jobs.get("evals", {"status": "idle", "log": ""})


@app.get("/api/evals/report")
def eval_report():
    f = RESULTS / "REPORT.md"
    return {"markdown": f.read_text(encoding="utf-8") if f.exists() else "No report yet. Run the eval first."}


DEMOS = {
    "redteam":       {"cmd": ["python", "run_demo.py", "--redteam-demo", "--llm", "mock"],
                      "cases": ["output/redteam/APP-2026-0142", "output/redteam/without-attack/APP-2026-0142"]},
    "policy-change": {"cmd": ["python", "run_demo.py", "--policy-change-demo", "--llm", "mock"],
                      "cases": ["output/policy-change/2026-10-16/APP-2026-0157", "output/policy-change/2026-11-02/APP-2026-0157"]},
    "tamper":        {"cmd": ["python", "run_demo.py", "--tamper-demo"], "cases": []},
    "replay":        {"cmd": ["python", "run_demo.py", "--replay", "output/APP-2026-0157"], "cases": []},
    "tests":         {"cmd": ["python", "-m", "unittest", "discover", "-s", "tests", "-v"], "cases": []},
}


@app.post("/api/demos/{name}")
def run_demo(name: str):
    if name not in DEMOS:
        raise HTTPException(404, "Unknown demo")
    if name == "replay" and not (OUT / "APP-2026-0157" / "decision_record.json").exists():
        raise HTTPException(400, "Run APP-2026-0157 first so there is a decision to replay")
    return _start_job(f"demo:{name}", [DEMOS[name]["cmd"]])


@app.get("/api/demos/{name}")
def demo_status(name: str):
    if name not in DEMOS:
        raise HTTPException(404, "Unknown demo")
    job = _jobs.get(f"demo:{name}", {"status": "idle", "log": ""})
    outs = []
    if job.get("status") == "done":
        for rel in DEMOS[name]["cases"]:
            f = PROTO / rel / "decision_record.json"
            if f.exists():
                r = json.loads(f.read_text())
                outs.append({"path": rel, "recommendation": r["recommendation"]["action"],
                             "route": [g["role"] for g in r["gates"]], "policy": r.get("policy", {}).get("version"),
                             "security_flags": len(r.get("security_flags", [])),
                             "conditions": len(r.get("conditions", []))})
    return {**job, "outputs": outs}


def _category_run(runs: list[dict]):
    """Newest eval run that covers the whole golden set, for the per-category tiles on the home page."""
    total = sum(1 for d in GOLDEN.glob("GS-*") if d.is_dir())
    full = [r for r in runs if sum(v["cases"] for v in r["summary"]["by_category"].values()) >= total]
    if not full:
        return None
    r = max(full, key=lambda r: r["run_at"] or "")
    return {"label": r["label"], "llm": r["llm"], "by_category": r["summary"]["by_category"]}


@app.get("/api/overview")
def overview():
    runs = list_evals()
    pick = next((r for r in runs if r["label"] == "claude-opus-5-5"), None) or (runs[-1] if runs else None)
    return {
        "samples": sum(1 for d in DATA.iterdir() if d.is_dir()),
        "golden": sum(1 for d in GOLDEN.glob("GS-*") if d.is_dir()),
        "categories": {k: sum(1 for d in GOLDEN.glob("GS-*") if d.is_dir() and _category_of(d.name) == k) for k in CATEGORIES},
        "eval_runs": len(runs),
        "cat_run": _category_run(runs),
        "headline": {"label": pick["label"], **pick["summary"]} if pick else None,
        "claude_key_set": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY")),
        "openrouter_key_set": bool(os.environ.get("OPENROUTER_API_KEY")),
        "llm_provider": ("openrouter" if os.environ.get("OPENROUTER_API_KEY") else
                         "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock"),
        "as_of": AS_OF,
    }


# ── Serve SPA (mount last so API routes take precedence) ─────────────────────
STATIC = Path(__file__).parent / "static"
STATIC.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    print("Loan Lifecycle Manager: open http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
