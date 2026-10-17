"""Knowledge layer: retrieval over the credit policy, with versions.

Each policy version has its text (clauses with IDs) and machine-readable parameters (thresholds,
authority limits) in data/policy/registry.json. A case uses the version in force on its decision date
and records it, so a past decision can be replayed against the policy that applied at the time.

Retrieval is a small BM25 index over clause-level chunks. At about 20 clauses with stable IDs, exact
clause lookup plus keyword ranking is all that is needed; a vector + keyword hybrid index earns its
place when the corpus grows to product notes, regulatory circulars and precedent memos.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Clause:
    id: str
    title: str
    text: str
    source: str
    line: int


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class PolicyKnowledgeBase:
    def __init__(self, path: Path, version: str = "v3.2", params: dict | None = None, effective_from: str = ""):
        self.path = path
        self.clauses: dict[str, Clause] = {}
        lines = path.read_text().splitlines()
        current = None
        for i, line in enumerate(lines):
            m = re.match(r"^### (POL-\d+\.\d+) (.+)$", line)
            if m:
                current = Clause(m.group(1), m.group(2).strip(), "", path.name, i + 1)
                self.clauses[current.id] = current
            elif current and line.strip() and not line.startswith("#"):
                current.text = (current.text + " " + line.strip()).strip()
        self._docs = {cid: _tokens(c.title + " " + c.text) for cid, c in self.clauses.items()}
        self._avg = sum(len(t) for t in self._docs.values()) / max(len(self._docs), 1)
        df = Counter(tok for toks in self._docs.values() for tok in set(toks))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.version = version
        self.effective_from = effective_from
        self.params = params or {}
        self.sha256 = hashlib.sha256((path.read_text() + json.dumps(self.params, sort_keys=True)).encode()).hexdigest()

    @classmethod
    def for_date(cls, policy_dir: Path, as_of: str, version: str | None = None) -> "PolicyKnowledgeBase":
        """The policy version in force on `as_of` (or a pinned version, for replay)."""
        reg = json.loads((policy_dir / "registry.json").read_text())["versions"]
        if version:
            v = next(x for x in reg if x["version"] == version)
        else:
            live = [x for x in reg if date.fromisoformat(x["effective_from"]) <= date.fromisoformat(as_of)]
            v = max(live, key=lambda x: x["effective_from"])
        return cls(policy_dir / v["file"], v["version"], v["params"], v["effective_from"])

    def p(self, key: str):
        return self.params[key]

    def ref(self, clause_id: str) -> str:
        return f"{clause_id}@{self.version}"

    def authority(self) -> list[tuple[float, str]]:
        return [(float("inf") if lim is None else lim, role) for lim, role in self.params["authority_limits_usd"]]

    def get(self, clause_id: str) -> Clause:
        return self.clauses[clause_id]

    def search(self, query: str, k: int = 3) -> list[tuple[Clause, float]]:
        q = _tokens(query)
        scores = []
        for cid, toks in self._docs.items():
            tf = Counter(toks)
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self._idf[t] * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(toks) / self._avg))
            scores.append((self.clauses[cid], s))
        scores.sort(key=lambda x: -x[1])
        return [x for x in scores[:k] if x[1] > 0]
