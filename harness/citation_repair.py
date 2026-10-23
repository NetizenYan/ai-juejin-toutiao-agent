"""Repair near-miss citations in model answers before validation.

The local model often cites the right article in the wrong form: full-width brackets
(［news:rmrb:…］), the hash without its source ([news:60c32c906a6f8970]), the wrong source
(news:jjrb:<an rmrb hash>) or a hash with one or two characters dropped or changed. Each of
these failed validation as missing/invalid citation and pushed the answer to the template
fallback. A citation is rewritten only when it maps to exactly one ref of this turn's evidence
pack; anything else is left untouched for the validator to reject.
"""
from __future__ import annotations

import re

FULLWIDTH_CITATION_RE = re.compile(r"[［【〔]\s*(news:[A-Za-z0-9:_\-]+)\s*[］】〕]")
CITATION_RE = re.compile(r"\[(news:[A-Za-z0-9:_\-]+)\]")
MAX_HASH_EDIT_DISTANCE = 2
MIN_HASH_CHARS = 8


def _hash_part(ref: str) -> str:
    return ref.rsplit(":", 1)[-1]


def _edit_distance(a: str, b: str, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _resolve(cited: str, refs: list[str]) -> str | None:
    if cited in refs:
        return cited
    cited_hash = _hash_part(cited)
    if len(cited_hash) < MIN_HASH_CHARS:
        return None  # "[news:rmrb]" names no article
    same_hash = [ref for ref in refs if _hash_part(ref) == cited_hash]
    if len(same_hash) == 1:
        return same_hash[0]  # missing or wrong source prefix
    near = [ref for ref in refs if _edit_distance(_hash_part(ref), cited_hash, MAX_HASH_EDIT_DISTANCE) <= MAX_HASH_EDIT_DISTANCE]
    if len(near) == 1:
        return near[0]
    return None


def repair_citations(answer: str, refs: list[str]) -> tuple[str, list[dict]]:
    """Return the answer with repairable citations fixed, and what was changed."""
    repairs: list[dict] = []
    if not answer:
        return answer, repairs

    def fullwidth(match: re.Match) -> str:
        repairs.append({"from": match.group(0), "to": f"[{match.group(1)}]", "kind": "fullwidth_brackets"})
        return f"[{match.group(1)}]"

    text = FULLWIDTH_CITATION_RE.sub(fullwidth, answer)
    known = list(dict.fromkeys(ref for ref in refs if ref))

    def fix(match: re.Match) -> str:
        cited = match.group(1)
        target = _resolve(cited, known)
        if target is None or target == cited:
            return match.group(0)
        repairs.append({"from": cited, "to": target, "kind": "ref"})
        return f"[{target}]"

    return CITATION_RE.sub(fix, text), repairs
