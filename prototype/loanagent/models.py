"""Shared data structures passed between agents."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class Evidence:
    """Where a fact came from: document, line number and the exact text."""
    source: str
    line: int | None = None
    quote: str = ""

    def cite(self) -> str:
        loc = f"{self.source}:{self.line}" if self.line else self.source
        return f"[{loc}]"


@dataclass
class ExtractedField:
    name: str
    value: Any
    evidence: Evidence
    confidence: float = 1.0
    citation_verified: bool = True
    verify_note: str = ""


@dataclass
class Finding:
    """A missing item, policy result, due diligence issue or risk observation."""
    agent: str
    category: str            # missing_info | due_diligence | policy | risk | conduct
    severity: str            # info | low | medium | high | critical
    title: str
    detail: str
    policy_ref: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    curable: bool = True     # can it become a condition precedent instead of a blocker?
    status: str = "open"     # open | pass | fail | cleared

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PolicyCheck:
    rule_id: str
    name: str
    status: str              # PASS | FLAG | FAIL | NOT_EVALUATED
    actual: str
    threshold: str
    clause_text: str
    evidence: list[Evidence] = field(default_factory=list)
    curable: bool = False
    note: str = ""
    policy_version: str = ""

    @property
    def ref(self) -> str:
        return f"{self.rule_id}@{self.policy_version}" if self.policy_version else self.rule_id


@dataclass
class Condition:
    id: str
    text: str
    source_ref: str
    owner: str
    due: str
    stage: str = "pre-disbursement"   # pre-approval | pre-disbursement | post-disbursement covenant
    status: str = "open"


@dataclass
class CaseFile:
    """Everything known about one application. Agents read from and write to it."""
    application: dict
    as_of: str
    documents: dict[str, dict] = field(default_factory=dict)    # filename -> {type, lines, masked_text}
    extracted: dict[str, dict[str, ExtractedField]] = field(default_factory=dict)  # doc_type -> fields
    findings: list[Finding] = field(default_factory=list)
    policy_checks: list[PolicyCheck] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    recommendation: dict = field(default_factory=dict)
    conditions: list[Condition] = field(default_factory=list)
    human_decisions: list[dict] = field(default_factory=list)
    rm_request: str = ""
    checklist: dict = field(default_factory=dict)   # required docs, gates, flags set by agents

    @property
    def app_id(self) -> str:
        return self.application["application_id"]

    def field(self, doc_type: str, name: str):
        f = self.extracted.get(doc_type, {}).get(name)
        return f.value if f else None

    def ev(self, doc_type: str, name: str) -> list[Evidence]:
        f = self.extracted.get(doc_type, {}).get(name)
        return [f.evidence] if f else []
