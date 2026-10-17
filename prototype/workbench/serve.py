#!/usr/bin/env python3
"""Reviewer workbench: the analyst's and approver's screen, served locally with the standard library.

  python workbench/serve.py            # then open http://localhost:8765
  python workbench/serve.py --port 9000

What it shows: every extracted value next to the source line it came from, the policy checks with the
clause and version they cite, findings, conditions, and the approval gates. Approvals go through the
same controls as the command-line demo (segregation of duties, delegated authority, override
rationale); blocked attempts are kept and written to the audit log when the case is decided.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from loanagent.audit import verify_chain                                   # noqa: E402
from loanagent.models import CaseFile                                       # noqa: E402
from loanagent.orchestrator import ScriptedApprover, run_case, validate_human_action  # noqa: E402
from loanagent.replay import ReplayLLM                                      # noqa: E402

APPS = ROOT / "data" / "applications"
OUT = ROOT / "output" / "workbench"
AS_OF = "2026-10-16"
BLOCKED: dict[str, dict[str, list]] = {}      # case id -> gate -> blocked attempts (kept for the audit log)
ACCEPTED: dict[str, dict[str, dict]] = {}     # case id -> gate -> accepted action


def _case_dir(case_id: str) -> Path:
    d = APPS / case_id
    if not d.is_dir() or "/" in case_id or ".." in case_id:
        raise KeyError(case_id)
    return d


PENDING: set[str] = set()                    # cases waiting at a gate in this session


def prepare(case_id: str, llm: str) -> dict:
    """Run the agents up to the first human gate."""
    run_case(_case_dir(case_id), None, OUT, as_of=AS_OF, llm_mode=llm, verbose=False, prepare_only=True)
    BLOCKED[case_id], ACCEPTED[case_id] = {}, {}
    PENDING.add(case_id)
    return load(case_id)


def load(case_id: str) -> dict:
    out = OUT / case_id
    decided = (out / "decision_record.json").exists() and case_id not in PENDING
    record = json.loads((out / ("decision_record.json" if decided else "pending_record.json")).read_text())
    docs = {p.name: p.read_text().splitlines() for p in sorted((_case_dir(case_id) / "documents").glob("*.txt"))}
    audit, chain = [], None
    if decided:
        audit = [json.loads(l) for l in (out / "audit_log.jsonl").read_text().splitlines() if l.strip()]
        chain = verify_chain(out / "audit_log.jsonl")[1]
    return {"decided": decided, "record": record, "extracted": json.loads((out / "extracted_fields.json").read_text()),
            "documents": docs, "audit": audit, "audit_verification": chain,
            "blocked": BLOCKED.get(case_id, {}), "accepted": ACCEPTED.get(case_id, {})}


def decide(case_id: str, gate: str, action: dict) -> dict:
    """Check one human action against the controls. When every gate is done, run the case to its end."""
    rec = json.loads((OUT / case_id / "pending_record.json").read_text())
    g = next(x for x in rec["gates"] if x["gate"] == gate)
    case = CaseFile(rec["application"], rec["as_of"])
    case.recommendation = rec["recommendation"]
    errors = validate_human_action(g, action, case)
    if errors:
        BLOCKED.setdefault(case_id, {}).setdefault(gate, []).append({**action, "errors": errors})
        return {"accepted": False, "errors": errors, "decided": False}
    ACCEPTED.setdefault(case_id, {})[gate] = action
    done = len(ACCEPTED[case_id]) == len(rec["gates"]) or (gate == "compliance" and action["decision"] == "EDD NOT CLEARED")
    if done:
        keep = ("name", "role", "decision", "rationale")
        script = {k: [{x: v[x] for x in keep} for v in BLOCKED.get(case_id, {}).get(k, [])] + [{x: a[x] for x in keep}]
                  for k, a in ACCEPTED[case_id].items()}
        extracted = json.loads((OUT / case_id / "extracted_fields.json").read_text())
        # the agents' work is not redone: the recorded extraction is replayed, so the decision is made on
        # exactly the evidence the reviewer saw
        run_case(_case_dir(case_id), ScriptedApprover(script), OUT, as_of=AS_OF, verbose=False,
                 llm=ReplayLLM(extracted, rec["controls"]["model"]))
        PENDING.discard(case_id)
    return {"accepted": True, "errors": [], "decided": done}


class Handler(BaseHTTPRequestHandler):
    llm = "mock"

    def _send(self, code: int, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if self.path == "/api/cases":
                cases = []
                for d in sorted(p for p in APPS.iterdir() if p.is_dir()):
                    app = json.loads((d / "application.json").read_text())
                    rec = OUT / d.name / "decision_record.json"
                    status = json.loads(rec.read_text())["final_status"] if rec.exists() and d.name not in PENDING else None
                    cases.append({"id": d.name, "borrower": app["borrower"]["legal_name"], "amount": app["facility"]["amount_usd"],
                                  "type": app["facility"]["type"], "status": status})
                return self._send(200, cases)
            if self.path.startswith("/api/case/"):
                cid = self.path.split("/")[3]
                _case_dir(cid)
                if not (OUT / cid / "pending_record.json").exists():
                    return self._send(200, prepare(cid, self.llm))
                return self._send(200, load(cid))
            if self.path == "/api/evals":
                res = {}
                for label in ("baseline-mock", "mock", "claude-opus-5-5-extract-v2", "claude-opus-5-5"):
                    f = ROOT / "evals" / "results" / label / "results.json"
                    if f.exists():
                        r = json.loads(f.read_text())
                        res[label] = {"summary": r["summary"], "run_at": r["run_at"],
                                      "cases": [{k: c.get(k) for k in ("case_id", "style", "planted", "recommendation", "routing", "error")}
                                                for c in r["cases"]]}
                return self._send(200, res)
            self._send(404, {"error": "not found"})
        except KeyError:
            self._send(404, {"error": "unknown case"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            parts = self.path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "case"] and parts[3] == "reset":
                return self._send(200, prepare(parts[2], self.llm))
            if len(parts) == 4 and parts[:2] == ["api", "case"] and parts[3] == "decide":
                return self._send(200, decide(parts[2], body["gate"], body["action"]))
            self._send(404, {"error": "not found"})
        except (KeyError, StopIteration, ValueError) as e:
            self._send(400, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--llm", choices=["mock", "claude"], default="mock")
    a = ap.parse_args()
    Handler.llm = a.llm
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Reviewer workbench on http://localhost:{a.port}  (model: {a.llm}; Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
