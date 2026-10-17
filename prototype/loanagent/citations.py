"""Citation checker.

Every value a model extracts must be backed by the line it cites. This module checks that the cited
line really contains the value, so a model that misreads, invents or mis-cites a number is caught
before the number reaches the policy rules. A value that cannot be verified is withheld from the
rules and sent to an analyst; it is never used silently.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .models import ExtractedField

SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
DATE_FORMATS = ["%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y", "%d/%m/%Y", "%d.%m.%Y"]


def _number_forms(v: float) -> set[str]:
    """Ways a number can appear in a document: 9800000, 9,800,000, 9.8, 1.18, 62."""
    forms = set()
    if float(v).is_integer():
        n = int(v)
        forms |= {str(n), f"{n:,}"}
    else:
        forms |= {f"{v:g}", f"{v:.2f}", f"{v:.1f}"}
    return forms


def _numbers_in(text: str) -> set[str]:
    return {m.replace(" ", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _values_in(text: str) -> list[float]:
    """Numbers in a line, including scaled forms such as 9.8m or 1.2 million."""
    out = []
    for num, suffix in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|mn|million|m|bn|billion)?\b", text, re.I):
        try:
            x = float(num.replace(",", ""))
        except ValueError:
            continue
        out.append(x)
        if suffix:
            out.append(x * SCALE[suffix.lower()])
    return out


def _contains_number(text: str, v: float) -> bool:
    if any(f in _numbers_in(text) for f in _number_forms(v)):
        return True
    return any(abs(x - float(v)) <= max(1e-9, abs(float(v)) * 1e-9) for x in _values_in(text))


def _dates_in(text: str) -> set[date]:
    found = set()
    candidates = re.findall(r"\d{4}-\d{2}-\d{2}|\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{4}|[A-Za-z]{3,9} \d{1,2}, \d{4}|\d{1,2}[/.]\d{1,2}[/.]\d{4}", text)
    for c in candidates:
        for fmt in DATE_FORMATS:
            try:
                found.add(datetime.strptime(c, fmt).date())
                break
            except ValueError:
                continue
    return found


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def verify(field: ExtractedField, lines: list[str]) -> tuple[bool, str]:
    """Return (verified, reason). `lines` are the masked document lines the model saw."""
    ev = field.evidence
    value = field.value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        # table rows (e.g. directors): every row's first column must appear somewhere in the document
        doc = _norm("\n".join(lines))
        missing = [r for r in value if _norm(next(iter(r.values()), "")) not in doc]
        return (not missing, "" if not missing else f"{len(missing)} row(s) not found in the document")
    if not ev.line or not (0 < ev.line <= len(lines)):
        return False, "no valid line cited"
    text = lines[ev.line - 1]
    if isinstance(value, bool):
        return True, ""
    if isinstance(value, (int, float)):
        return (_contains_number(text, value), "" if _contains_number(text, value) else
                f"cited line {ev.line} does not contain {value:,}")
    if isinstance(value, list):
        bad = [x for x in value if not _contains_number(text, float(x))]
        return (not bad, "" if not bad else f"cited line {ev.line} does not contain {bad}")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        ok = date.fromisoformat(value) in _dates_in(text)
        return ok, "" if ok else f"cited line {ev.line} does not contain the date {value}"
    iso = re.findall(r"\d{4}-\d{2}-\d{2}", str(value))
    if iso:
        # text holding dates the model normalised to ISO, e.g. a statement period "2025-10-01 to 2026-09-30":
        # every date must be on the cited line in some format
        on_line = _dates_in(text)
        bad = [d for d in iso if date.fromisoformat(d) not in on_line]
        return (not bad, "" if not bad else f"cited line {ev.line} does not contain the date(s) {', '.join(bad)}")
    ok = _norm(value) in _norm(text) or _words_on_line(str(value), text)
    return ok, "" if ok else f"cited line {ev.line} does not contain '{value}'"


STOP = {"a", "an", "the", "and", "of", "by", "is", "as", "on", "in", "to", "for", "with"}


def _words_on_line(value: str, text: str) -> bool:
    """Text the model lightly rephrased ("Oakridge Valuers, empanelled valuer" from "Oakridge Valuers, an
    empanelled valuer"): every content word of the value must be on the cited line."""
    words = lambda s: {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP}
    v = words(value)
    return bool(v) and v <= words(text)
