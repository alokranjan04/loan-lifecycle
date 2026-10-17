"""Auditability and observability.

AuditLog: append-only, hash-chained record of every agent step and human action. Each entry stores
the SHA-256 of the previous entry, so editing or deleting any entry breaks verification.
Tracer: per-step spans (latency, model calls, tokens) written as JSON lines, the shape an
OpenTelemetry exporter would ship to a monitoring stack.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: Path, case_id: str):
        self.path = path
        self.case_id = case_id
        self.entries: list[dict] = []
        path.write_text("")

    def record(self, actor: str, actor_type: str, action: str, inputs=None, outputs=None,
               policy_refs=None, model: str | None = None) -> dict:
        entry = {
            "seq": len(self.entries) + 1,
            "case_id": self.case_id,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": actor,
            "actor_type": actor_type,          # agent | human | system
            "action": action,
            "input_hash": _digest(inputs) if inputs is not None else None,
            "outputs": outputs,
            "policy_refs": sorted(set(policy_refs or [])),
            "model": model,
            "prev_hash": self.entries[-1]["hash"] if self.entries else GENESIS,
        }
        entry["hash"] = _digest(entry)
        self.entries.append(entry)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry

    @property
    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS


def verify_chain(path: Path) -> tuple[bool, str]:
    prev = GENESIS
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    for line in lines:
        e = json.loads(line)
        claimed = e.pop("hash")
        if e["prev_hash"] != prev:
            return False, f"entry {e['seq']}: prev_hash does not match entry {e['seq'] - 1}"
        if _digest(e) != claimed:
            return False, f"entry {e['seq']}: content was altered after it was written"
        prev = claimed
    return True, f"{len(lines)} entries verified, head {prev[:16]}"


class Tracer:
    def __init__(self, path: Path, llm):
        self.path = path
        self.llm = llm
        self.trace_id = uuid.uuid4().hex[:16]
        self.spans: list[dict] = []
        path.write_text("")

    def span(self, name: str):
        tracer = self

        class _Span:
            def __enter__(self):
                self.t0 = time.perf_counter()
                self.before = tracer.llm.stats.snapshot()
                self.attrs = {}
                return self

            def __exit__(self, *exc):
                after = tracer.llm.stats.snapshot()
                rec = {"trace_id": tracer.trace_id, "span": name,
                       "duration_ms": round((time.perf_counter() - self.t0) * 1000, 1),
                       "status": "error" if exc[0] else "ok",
                       **{k: after[k] - self.before[k] for k in ("llm_calls", "input_tokens", "output_tokens")},
                       **self.attrs}
                tracer.spans.append(rec)
                with tracer.path.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
                return False

        return _Span()
