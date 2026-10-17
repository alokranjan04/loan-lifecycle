"""PII masking applied to every document before it reaches a model.

Identifiers are swapped for tokens ([ID_1], [ACCT_1], ...) and kept in a per-case vault that never
leaves the bank boundary. Extracted values are unmasked after the model returns.
"""
from __future__ import annotations

import re

PATTERNS = [
    ("REG", re.compile(r"\b[A-Z]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")),   # company registration number
    ("ID", re.compile(r"\b[A-Z]{2}-[A-Z]{2}\d{6}\b")),                   # driver licence style
    ("ID", re.compile(r"(?<=Passport )[A-Z]?\d{6,9}\b")),                # passport numbers
    ("ACCT", re.compile(r"\b\d{9,18}\b")),                               # bank account numbers
]


class PIIVault:
    def __init__(self):
        self.forward: dict[str, str] = {}
        self.reverse: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    def _token(self, kind: str, value: str) -> str:
        if value not in self.forward:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            tok = f"[{kind}_{self.counts[kind]}]"
            self.forward[value] = tok
            self.reverse[tok] = value
        return self.forward[value]

    def mask(self, text: str) -> str:
        for kind, pat in PATTERNS:
            text = pat.sub(lambda m, k=kind: self._token(k, m.group(0)), text)
        return text

    def unmask(self, value):
        if isinstance(value, str):
            return re.sub(r"\[[A-Z]+_\d+\]", lambda m: self.reverse.get(m.group(0), m.group(0)), value)
        if isinstance(value, list):
            return [self.unmask(v) for v in value]
        if isinstance(value, dict):
            return {k: self.unmask(v) for k, v in value.items()}
        return value

    @property
    def total(self) -> int:
        return len(self.forward)


# ---------------------------------------------------------------------------------------------
# Prompt-injection screen
# ---------------------------------------------------------------------------------------------
# Borrower documents are untrusted. Text that addresses an AI system or tries to give instructions is
# flagged, recorded in the audit log, and replaced in the copy the model sees. This is one layer only:
# the stronger guarantee is structural (the model's output is schema-checked data, it can never set a
# policy result, a route or a decision). In production a managed classifier such as Azure AI Content
# Safety Prompt Shields would sit alongside this list.
INJECTION_PATTERNS = [
    re.compile(r"\b(ignore|disregard|override|forget|bypass)\b.{0,40}\b(instructions?|polic(y|ies)|rules|previous|above|guidelines)\b", re.I),
    re.compile(r"\b(system|developer|admin)\s+(note|prompt|message|instruction)s?\b", re.I),
    re.compile(r"\bnote\s+(to|for)\s+(the\s+)?(ai|automated|assistant|model|llm|reviewer|bot)\b", re.I),
    re.compile(r"\b(you are|act as|pretend to be)\b.{0,30}\b(assistant|ai|model|reviewer)\b", re.I),
    re.compile(r"\b(recommend|grant)\s+(approval|approving)\b", re.I),
    re.compile(r"\btreat\s+this\s+(application|case|borrower)\s+as\b", re.I),
    re.compile(r"\bdo not (mention|disclose|reveal) this\b", re.I),
    # added after the jailbreak cases GS-034 to GS-039 got past the list above
    re.compile(r"\b(already|pre-?)\s*(been\s+)?(approved|cleared|sanctioned|authori[sz]ed)\b", re.I),       # fake prior approval
    re.compile(r"\b(skip|suppress|bypass|do not flag|don't flag|mark all)\b.{0,50}\b(screening|checks?|compliance|pep|sanctions|match(es)?|passed)\b", re.I),
    re.compile(r"\b(developer|jailbreak|god|unrestricted|debug)\s+mode\b|\bwith no restrictions\b", re.I),   # role-play
    re.compile(r"\boutput\s+(approve|approval|decline)\b", re.I),
    re.compile(r"\b(when|while)\s+(extracting|summari[sz]ing|processing|reviewing)\b", re.I),               # telling the reader what to extract
    re.compile(r"\b(record|report|enter|set)\s+the\s+[a-z ]{0,30}\bas\s+(usd|eur|gbp|\$)", re.I),
    re.compile(r'"\s*(policy_override|override|recommendation|decision|authority|approved?)"\s*:', re.I),   # machine-readable override
    re.compile(r"\b(ignora|ignorez|ignoriere|ignorare|aprueba|apruebe|approuvez|genehmigen)\b", re.I),         # common non-English phrasing
]
QUARANTINE = "[REMOVED: instruction-like text quarantined for analyst review]"


def scan_for_injection(lines: list[str]) -> list[dict]:
    hits = []
    for i, line in enumerate(lines, 1):
        rules = [p.pattern for p in INJECTION_PATTERNS if p.search(line)]
        if rules:
            hits.append({"line": i, "text": line.strip(), "rules_matched": len(rules)})
    return hits
