"""FastAPI web server wrapping the loan-lifecycle agent pipeline.

Exposes:
  GET  /api/applications            – list all applications
  GET  /api/applications/<id>       – full application JSON
  POST /api/run/<id>                – start pipeline in background thread
  GET  /api/stream/<sid>            – SSE stream of pipeline events
  POST /api/approve/<sid>           – submit human approval decision
  GET  /api/session/<id>            – current session status for an app
  GET  /api/results/<id>            – decision_record.json after completion
  GET  /api/audit/<id>              – audit_log.jsonl parsed
  GET  /                            – serves the SPA (static/index.html)
"""
from __future__ import annotations

import asyncio
import json
import queue
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

from loanagent.orchestrator import (          # noqa: E402
    CREDIT_DECISIONS, COMPLIANCE_DECISIONS,
    run_case, validate_human_action,
)
from loanagent import models                  # noqa: E402

DATA = PROTO / "data" / "applications"
OUT  = PROTO / "output"
OUT.mkdir(exist_ok=True)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Loan Lifecycle Manager")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ── Session store (in-process; fine for demo) ─────────────────────────────────
_sessions:  dict[str, Session] = {}
_app_sid:   dict[str, str]     = {}   # app_id → latest session id


class Session:
    def __init__(self, app_id: str, llm_mode: str = "auto"):
        self.id          = uuid.uuid4().hex[:8]
        self.app_id      = app_id
        self.llm_mode    = llm_mode
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


# ── Web approver ──────────────────────────────────────────────────────────────
class WebApprover:
    def __init__(self, s: Session):
        self.s = s

    def ask(self, gate: dict, case, attempt: int) -> dict:
        self.s._orig_gate       = gate
        self.s.pending_gate_info = {
            "gate_type":     gate["gate"],          # "compliance" | "credit"
            "required_role": gate["role"],
            "reason":        gate.get("reason", ""),
            "attempt":       attempt,
            "recommendation": (case.recommendation or {}).get("action"),
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
        if not self.s._resp_ev.wait(timeout=600):
            raise TimeoutError("Approval timed out after 10 minutes")

        resp = self.s._resp
        self.s._resp   = None
        self.s.status  = "running"
        self.s.push({"type": "status", "data": {"status": "running"}})
        return resp


# ── Audit tailer ──────────────────────────────────────────────────────────────
def _tail_audit(session: Session, audit_path: Path) -> None:
    """Tail audit_log.jsonl and push progress events to the session queue."""
    deadline = time.monotonic() + 60
    while not audit_path.exists():
        if time.monotonic() > deadline:
            return
        time.sleep(0.15)

    pos = 0
    while session.status in ("pending", "running", "awaiting_approval"):
        try:
            size = audit_path.stat().st_size
        except FileNotFoundError:
            time.sleep(0.2)
            continue
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
        time.sleep(0.2)


# ── Pipeline runner ───────────────────────────────────────────────────────────
def _run_pipeline(session: Session) -> None:
    audit_path = OUT / session.app_id / "audit_log.jsonl"
    tailer = threading.Thread(target=_tail_audit, args=(session, audit_path), daemon=True)
    tailer.start()

    try:
        session.status = "running"
        session.push({"type": "status", "data": {"status": "running"}})
        run_case(
            app_dir    = DATA / session.app_id,
            approver   = WebApprover(session),
            out_root   = OUT,
            llm_mode   = session.llm_mode,
            verbose    = False,
        )
        session.status = "complete"
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


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/api/applications")
def list_applications():
    result = []
    for d in sorted(DATA.iterdir()):
        f = d / "application.json"
        if not d.is_dir() or not f.exists():
            continue
        data = json.loads(f.read_text())
        rec  = None
        rf   = OUT / d.name / "decision_record.json"
        if rf.exists():
            rec = json.loads(rf.read_text())
        result.append({
            "id":            d.name,
            "borrower":      data["borrower"]["legal_name"],
            "sector":        data["borrower"]["sector"],
            "amount_usd":    data["facility"]["amount_usd"],
            "facility_type": data["facility"]["type"],
            "submitted_on":  data.get("submitted_on"),
            "rm":            data.get("relationship_manager"),
            "analyst":       data.get("credit_analyst"),
            "has_result":    rec is not None,
            "final_status":  rec.get("final_status") if rec else None,
        })
    return result


@app.get("/api/applications/{app_id}")
def get_application(app_id: str):
    f = DATA / app_id / "application.json"
    if not f.exists():
        raise HTTPException(404, "Application not found")
    return json.loads(f.read_text())


@app.get("/api/results/{app_id}")
def get_results(app_id: str):
    f = OUT / app_id / "decision_record.json"
    if not f.exists():
        raise HTTPException(404, "Results not found — run the pipeline first")
    return json.loads(f.read_text())


@app.get("/api/audit/{app_id}")
def get_audit_log(app_id: str):
    f = OUT / app_id / "audit_log.jsonl"
    if not f.exists():
        raise HTTPException(404, "Audit log not found")
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


class RunRequest(BaseModel):
    llm_mode: str = "auto"


@app.post("/api/run/{app_id}")
def start_run(app_id: str, req: RunRequest = RunRequest()):
    if not (DATA / app_id).exists():
        raise HTTPException(404, "Application not found")
    s = Session(app_id, req.llm_mode)
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


# ── Serve SPA (mount last so API routes take precedence) ─────────────────────
STATIC = Path(__file__).parent / "static"
STATIC.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True,
                reload_dirs=[str(Path(__file__).parent)])
