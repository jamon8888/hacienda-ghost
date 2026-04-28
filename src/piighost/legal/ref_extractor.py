"""Regex-based extractor for French legal references.

Ported from the user's legal-hallucination-checker skill
(scripts/extract_references.py). Pure-function — no I/O.
"""
from __future__ import annotations

import re

from piighost.legal.reference_models import LegalReference, LegalRefType


# Code name → official name mapping (from skill's CODE_ALIASES)
_CODE_ALIASES = {
    "c. civ.": "Code civil",
    "c. civ": "Code civil",
    "code civ.": "Code civil",
    "c. pén.": "Code pénal",
    "c. pen.": "Code pénal",
    "c. com.": "Code de commerce",
    "c. trav.": "Code du travail",
    "c. conso.": "Code de la consommation",
    "c. pr. pén.": "Code de procédure pénale",
    "cpp": "Code de procédure pénale",
    "cgi": "Code général des impôts",
    "csp": "Code de la santé publique",
    "cpi": "Code de la propriété intellectuelle",
}


def _normalize_code(raw: str) -> str:
    lower = raw.lower().strip().rstrip(".")
    for alias, official in _CODE_ALIASES.items():
        if alias.rstrip(".") in lower:
            return official
    return raw.strip()


# Regex patterns (compiled once)
_RE_ARTICLE_CODE = re.compile(
    r"(?:l')?articles?\s+([LRDA]\.?\s*)?(\d+(?:-\d+)*)"
    r"(?:\s+et\s+(\d+(?:-\d+)*))?"
    r"\s+du\s+(Code\s+[\w\s'-]+?)"
    r"(?=\s*[,\.\);]|\s+(?:et|qui|dispose|prévoit|énonce)|\s*$)",
    re.I,
)
_RE_ART_ABBREV = re.compile(
    r"art\.?\s+([LRDA]\.?\s*)?(\d+(?:-\d+)*)\s+(?:du\s+)?(C\.\s*[\w\s\.]+?)(?=\s|$)",
    re.I,
)
_RE_LOI = re.compile(
    r"loi\s+n[°o]?\s*(\d{2,4}[-–]\d+)\s+du\s+(\d{1,2}\s+\w+\s+\d{4})",
    re.I,
)
_RE_DECRET = re.compile(
    r"décrets?\s+n[°o]?\s*(\d{2,4}[-–]\d+)(?:\s+du\s+(\d{1,2}\s+\w+\s+\d{4}))?",
    re.I,
)
_RE_ORDONNANCE = re.compile(
    r"ordonnance\s+n[°o]?\s*(\d{2,4}[-–]\d+)(?:\s+du\s+(\d{1,2}\s+\w+\s+\d{4}))?",
    re.I,
)
_RE_JURISPRUDENCE = re.compile(
    r"(Cass\.?\s*(?:ass\.?\s*plén\.?|civ\.?\s*\d(?:re|e|ère)?|com\.?|crim\.?|soc\.?|ch\.?\s*mixte))"
    r"[,\s]+(\d{1,2}\s+\w+\s+\d{4})"
    r"[,\s]+n[°o]?\s*(\d{2}[-–]\d+\.?\d*)",
    re.I,
)


def extract_references(text: str) -> list[LegalReference]:
    """Extract all legal references in *text*.

    Returns a list of LegalReference with sequential ref_id starting at 1.
    Order follows source position. Empty list if no refs found.
    """
    if not text:
        return []
    refs: list[LegalReference] = []
    next_id = 1

    def _add(ref_type: LegalRefType, raw_text: str, position: int, **fields):
        nonlocal next_id
        refs.append(LegalReference(
            ref_id=next_id, ref_type=ref_type,
            raw_text=raw_text, position=position, **fields,
        ))
        next_id += 1

    # Articles in codes (full form) — also handles "X et Y du Code …"
    for m in _RE_ARTICLE_CODE.finditer(text):
        prefix = (m.group(1) or "").strip()
        numero = m.group(2)
        if prefix:
            numero = f"{prefix} {numero}".strip()
        code_name = _normalize_code(m.group(4))
        # Position points to "article" itself (skip optional "l'" prefix)
        raw = m.group(0)
        offset = 0
        lower_raw = raw.lower()
        if lower_raw.startswith("l'"):
            offset = 2
        art_position = m.start() + offset
        _add(
            LegalRefType.ARTICLE_CODE,
            raw_text=raw,
            position=art_position,
            numero=numero,
            code=code_name,
        )
        # Second article in "art. X et Y du Code …"
        second = m.group(3)
        if second:
            numero2 = f"{prefix} {second}".strip() if prefix else second
            # position: locate the second number inside the match
            second_pos = m.start() + m.group(0).find(second, len(m.group(2)))
            _add(
                LegalRefType.ARTICLE_CODE,
                raw_text=second,
                position=second_pos,
                numero=numero2,
                code=code_name,
            )

    # Articles abbreviated form
    for m in _RE_ART_ABBREV.finditer(text):
        prefix = (m.group(1) or "").strip()
        numero = m.group(2)
        if prefix:
            numero = f"{prefix} {numero}".strip()
        _add(
            LegalRefType.ARTICLE_CODE,
            raw_text=m.group(0),
            position=m.start(),
            numero=numero,
            code=_normalize_code(m.group(3)),
        )

    # Lois
    for m in _RE_LOI.finditer(text):
        _add(
            LegalRefType.LOI,
            raw_text=m.group(0),
            position=m.start(),
            text_id=m.group(1).replace("–", "-"),
            date=m.group(2),
        )

    # Décrets
    for m in _RE_DECRET.finditer(text):
        _add(
            LegalRefType.DECRET,
            raw_text=m.group(0),
            position=m.start(),
            text_id=m.group(1).replace("–", "-"),
            date=m.group(2),
        )

    # Ordonnances
    for m in _RE_ORDONNANCE.finditer(text):
        _add(
            LegalRefType.ORDONNANCE,
            raw_text=m.group(0),
            position=m.start(),
            text_id=m.group(1).replace("–", "-"),
            date=m.group(2),
        )

    # Jurisprudence
    for m in _RE_JURISPRUDENCE.finditer(text):
        _add(
            LegalRefType.JURISPRUDENCE,
            raw_text=m.group(0),
            position=m.start(),
            juridiction="Cour de cassation",
            formation=m.group(1),
            date=m.group(2),
            pourvoi=m.group(3).replace("–", "-"),
        )

    # Sort by position, re-number
    refs.sort(key=lambda r: r.position)
    for i, r in enumerate(refs, start=1):
        r.ref_id = i
    return refs
