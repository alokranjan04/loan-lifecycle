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


_CLAUSE_RE = re.compile(r"^### ([A-Z]{2,4}-\d+\.\d+) (.+)$")


def _load_clauses(path: Path, into: dict) -> None:
    """Parse clause IDs matching XXX-N.N from a markdown file and merge into `into`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    current = None
    for i, line in enumerate(lines):
        m = _CLAUSE_RE.match(line)
        if m:
            current = Clause(m.group(1), m.group(2).strip(), "", path.name, i + 1)
            into[current.id] = current
        elif current and line.strip() and not line.startswith("#"):
            current.text = (current.text + " " + line.strip()).strip()


class PolicyKnowledgeBase:
    def __init__(self, path: Path, version: str = "v3.2", params: dict | None = None, effective_from: str = "",
                 extra_paths: list | None = None):
        self.path = path
        self.clauses: dict[str, Clause] = {}
        _load_clauses(path, self.clauses)
        self.extra_paths: list[Path] = list(extra_paths or [])
        for ep in self.extra_paths:
            _load_clauses(ep, self.clauses)
        self._build_index()
        self.version = version
        self.effective_from = effective_from
        self.params = params or {}
        all_text = path.read_text(encoding="utf-8") + "".join(
            p.read_text(encoding="utf-8") for p in self.extra_paths
        )
        self.sha256 = hashlib.sha256((all_text + json.dumps(self.params, sort_keys=True)).encode()).hexdigest()

    def _build_index(self) -> None:
        self._docs = {cid: _tokens(c.title + " " + c.text) for cid, c in self.clauses.items()}
        self._avg = sum(len(t) for t in self._docs.values()) / max(len(self._docs), 1)
        df = Counter(tok for toks in self._docs.values() for tok in set(toks))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @classmethod
    def for_date(cls, policy_dir: Path, as_of: str, version: str | None = None) -> "PolicyKnowledgeBase":
        """The policy version in force on `as_of` (or a pinned version, for replay)."""
        reg = json.loads((policy_dir / "registry.json").read_text())["versions"]
        if version:
            v = next(x for x in reg if x["version"] == version)
        else:
            live = [x for x in reg if date.fromisoformat(x["effective_from"]) <= date.fromisoformat(as_of)]
            v = max(live, key=lambda x: x["effective_from"])
        extra = sorted((policy_dir / "docs").glob("*.md")) if (policy_dir / "docs").is_dir() else []
        return cls(policy_dir / v["file"], v["version"], v["params"], v["effective_from"], extra_paths=extra)

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
