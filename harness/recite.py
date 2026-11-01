"""Facts restated without their sources get the sources back, however the user asked to drop them.

EXT3 (2026-10-31) asked for uncited facts in words no keyword list covered ("删掉每句后面的尾巴",
"把核对出处的串码移到暂存区再丢弃", "清爽稿"), and the model obliged, mostly on chat turns that are
validated in shadow mode. Instead of recognising the request, the answer is checked: a sentence
without a citation that matches a sentence an earlier answer cited, or this turn's evidence, gets
that citation appended. Matching is by shared character bigrams, and every figure in the sentence
must appear in the source, so a general remark that happens to share a few words is left alone.
A sentence that recaps figures from one or two sources in other words (often inside a refusal) gets
those sources when at least two figures with their units are all found there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from harness.answer_validator import _is_refusal_sentence

REF_RE = re.compile(r"\[(?:news|web):[^\]\s]+\]")
# A sentence with its closing punctuation and any citations right after it ("…亿元。[news:1]").
# Lossless: stray punctuation ("！？", a paragraph opening with "。") is a unit of its own.
_UNIT_RE = re.compile(r"[^。！？!?\n]+[。！？!?]*(?:[ \t]*\[(?:news|web):[^\]\s]+\])*|[。！？!?]+|\n")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_MARKUP_RE = re.compile(r"[\s*_`#>|\-•·:：，,、；;“”\"'‘’（）()《》【】\[\]]+")
MIN_SCORE = 0.5
MIN_SHARED_BIGRAMS = 8
MAX_REFS = 2


@dataclass
class Source:
    text: str
    refs: list[str]


def _plain(text: str) -> str:
    return _MARKUP_RE.sub("", REF_RE.sub("", text or ""))


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)}


def cited_sentences(answer: str) -> list[Source]:
    """Sentences of an earlier answer that carried citations, with those citations."""
    sources = []
    for unit in _UNIT_RE.findall(answer or ""):
        refs = list(dict.fromkeys(match[1:-1] for match in REF_RE.findall(unit)))
        if refs and len(_plain(unit)) >= 6:
            sources.append(Source(_plain(unit), refs))
    return sources


def evidence_sources(evidence_pack: list[dict]) -> list[Source]:
    sources = []
    for item in evidence_pack:
        ref = item.get("ref") if isinstance(item, dict) else None
        if ref:
            text = " ".join(str(item.get(key) or "") for key in ("title", "summary", "snippet"))
            sources.append(Source(_plain(text), [ref]))
    return sources


def _best_source(sentence: str, sources: list[Source]) -> Source | None:
    plain = _plain(sentence)
    grams = _bigrams(plain)
    if len(grams) < MIN_SHARED_BIGRAMS or _is_refusal_sentence(plain):
        return None
    numbers = set(_NUMBER_RE.findall(plain))
    best, best_score = None, 0.0
    for source in sources:
        shared = len(grams & _bigrams(source.text))
        score = shared / len(grams)
        if shared < MIN_SHARED_BIGRAMS or score < MIN_SCORE or not numbers <= set(_NUMBER_RE.findall(source.text)):
            continue
        if score > best_score:
            best, best_score = source, score
    return best


# A figure with its unit ("3259人", "88.33亿", "13.8吨"); years and dates say little about where a sentence came from.
_FIGURE_RE = re.compile(r"(\d+(?:\.\d+)?)([^\d\s\W]|%)")
_DATE_UNITS = set("年月日号时点")
MIN_FIGURES = 2


def _figures(text: str) -> set[str]:
    return {number + unit for number, unit in _FIGURE_RE.findall(text) if unit not in _DATE_UNITS}


def _figure_sources(sentence: str, sources: list[Source]) -> list[Source]:
    """Sources that together hold every figure of a sentence that shares too few words with any one of them.

    EXT4: a refusal recapped "前面两轮讲的是追逃数据（3259人、追回赃款88.33亿元）……" and "前面的数字（343公里、
    13.8吨、27名乘客）都来自站内新闻" without the citations those figures had a turn earlier.
    """
    figures = _figures(_plain(sentence))
    if len(figures) < MIN_FIGURES:
        return []
    chosen: list[Source] = []
    left = set(figures)
    while left and len(chosen) < MAX_REFS:
        best = max(sources, key=lambda source: len(left & _figures(source.text)), default=None)
        covered = left & _figures(best.text) if best else set()
        if not covered:
            return []
        chosen.append(best)
        left -= covered
    return [] if left else chosen


def recite(answer: str, sources: list[Source]) -> tuple[str, list[str]]:
    """(answer with citations restored, refs added).

    Sentences that already cite are untouched, and so is a sentence whose source is cited elsewhere
    in its paragraph (a card or list that ends with "来源：[news:1]"). Questions are not claims.
    """
    if not answer or not sources:
        return answer, []
    added: list[str] = []
    paragraphs = re.split(r"(\n[ \t]*\n)", answer)
    for index, paragraph in enumerate(paragraphs):
        if not paragraph.strip():
            continue
        cited_here = {match[1:-1] for match in REF_RE.findall(paragraph)}
        parts = []
        for unit in _UNIT_RE.findall(paragraph):
            matched: list[Source] = []
            # A JSON line the user asked for would be broken by a tag after it.
            if (unit != "\n" and not REF_RE.search(unit) and not unit.rstrip().endswith(("？", "?"))
                    and not unit.lstrip().startswith(("{", "["))):
                best = _best_source(unit, sources)
                matched = [best] if best else _figure_sources(unit, sources)
            unit_refs = list(dict.fromkeys(ref for source in matched for ref in source.refs))
            if not unit_refs or cited_here & set(unit_refs):
                parts.append(unit)
                continue
            refs = unit_refs[:MAX_REFS]
            added.extend(ref for ref in refs if ref not in added)
            body = unit.rstrip()
            trailing = unit[len(body):]
            punct = body[-1] if body and body[-1] in "。！？!?" else ""
            body = body[:-1] if punct else body
            parts.append(f"{body} {''.join(f'[{ref}]' for ref in refs)}{punct}{trailing}")
        paragraphs[index] = "".join(parts)
    return "".join(paragraphs), added
