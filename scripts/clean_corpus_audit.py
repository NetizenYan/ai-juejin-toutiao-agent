#!/usr/bin/env python3
"""Read-only audit of the v2 clean corpus (clean_merged_recent_econ.jsonl).

This script is STRICTLY READ-ONLY. It never:
  - modifies MySQL / PostgreSQL / Qdrant,
  - rebuilds news_chunks_v2,
  - reads the raw 3G source data,
  - performs embedding or Qdrant upsert.

It only reads:
  - the clean corpus jsonl,
  - existing eval gold files,
  - existing A/B failure / diagnosis reports,
and (optionally, read-only) counts rows in PG / points in Qdrant for reconciliation.

Outputs a Markdown + JSON report.

Usage:
  python scripts/clean_corpus_audit.py \
      --corpus work/econ_rag_experiment/clean_merged_recent_econ.jsonl \
      --output-md eval/reports/clean_corpus_audit_20260622.md \
      --output-json eval/reports/clean_corpus_audit_20260622.json
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import difflib
import glob
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

# ---- optional fast fuzzy matcher -------------------------------------------------
try:
    from rapidfuzz import fuzz as _rf_fuzz

    HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_RAPIDFUZZ = False

TODAY = dt.date(2026, 6, 22)  # audit reference date
EARLIEST_VALID_YEAR = 1949

# Tail-noise markers commonly left over from scraping.
NOISE_PATTERNS = [
    "责任编辑", "责编", "编辑：", "编辑:", "主编", "审核", "校对",
    "下载客户端", "客户端下载", "扫码", "二维码", "扫一扫",
    "版权声明", "版权所有", "未经授权", "转载请注明", "本文来源", "稿件来源",
    "原标题", "点击下载", "更多精彩", "关注我们", "微信公众号", "新闻热线",
]
NOISE_RE = re.compile("|".join(re.escape(p) for p in NOISE_PATTERNS))
HTML_RE = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?>|&[a-zA-Z]{2,8};|&#\d{2,5};")
URL_RE = re.compile(r"https?://|www\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
WS_RE = re.compile(r"\s+")

# Characters considered "normal" for a Chinese economic-news corpus.
CJK_RE = re.compile(
    r"[一-鿿㐀-䶿]"  # CJK ideographs
)
NORMAL_CHAR_RE = re.compile(
    r"[一-鿿㐀-䶿"          # CJK
    r"　-〿＀-￯"           # CJK punctuation / fullwidth forms
    r"a-zA-Z0-9"
    r"\s"
    r"\.,;:!\?\-\(\)\[\]{}\"'%/、，。；：！？（）【】「」『』《》—…·．°￥$@#&*+=_~|^<>]"
)
# Private-use / replacement chars are a strong garble signal.
SUSPECT_CHAR_RE = re.compile(r"[�-]")


# ---------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------
def norm_ws(text: str) -> str:
    return WS_RE.sub(" ", (text or "").strip())


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def is_similar(a: str, b: str, threshold: float) -> bool:
    """Threshold test with cheap pre-filters so the difflib fallback stays fast."""
    if not a or not b:
        return False
    # length gate (real_quick_ratio upper bound): 2*min/(la+lb) >= threshold
    la, lb = len(a), len(b)
    if 2.0 * min(la, lb) / (la + lb) < threshold:
        return False
    if HAVE_RAPIDFUZZ:
        return _rf_fuzz.ratio(a, b) / 100.0 >= threshold
    sm = difflib.SequenceMatcher(None, a, b)
    if sm.quick_ratio() < threshold:  # O(n) multiset upper bound
        return False
    return sm.ratio() >= threshold


def pct(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def percentiles(values, ps):
    """Simple nearest-rank percentiles over a sorted list of numbers."""
    if not values:
        return {p: 0 for p in ps}
    s = sorted(values)
    out = {}
    for p in ps:
        if p <= 0:
            out[p] = s[0]
        elif p >= 100:
            out[p] = s[-1]
        else:
            k = max(0, min(len(s) - 1, int(math.ceil(p / 100.0 * len(s))) - 1))
            out[p] = s[k]
    return out


_GARBLE_CTRL_RE = re.compile(r"[\u0000-\u0008\u000e-\u001f\u007f-\u009f\ue000-\uf8ff]")
_LATIN_ALPHA_RE = re.compile(r"[A-Za-z]")
# Strong tail-trailer markers; only flagged when they appear at the END of the body,
# so legitimate in-body mentions (e.g. "微信公众号") are NOT counted as noise.
_TAIL_NOISE = (
    "责任编辑", "责编", "版权声明", "版权所有", "未经授权", "转载请注明",
    "下载客户端", "客户端下载", "扫码", "二维码", "扫一扫", "点击下载",
    "新闻热线", "稿件来源", "本文来源", "（编辑", "(编辑",
)


def is_garbled(text: str) -> bool:
    """Conservative mojibake detection. Flags only strong signals (replacement char,
    control/private-use runs, or a 'should-be-Chinese' doc with ~no CJK) — NOT ordinary
    typographic punctuation such as the curly quotes 全角引号 “ ” ‘ ’ or dashes — and …."""
    if not text:
        return False
    sample = text[:1000]
    if "�" in sample:  # Unicode replacement char => decode failure
        return True
    bad = len(_GARBLE_CTRL_RE.findall(sample))
    if bad >= 3 and bad / len(sample) > 0.02:
        return True
    if len(sample) >= 40:
        cjk = len(CJK_RE.findall(sample))
        latin = len(_LATIN_ALPHA_RE.findall(sample))
        if cjk == 0 and latin / len(sample) < 0.3:
            return True
    return False


def has_tail_noise(content: str, window: int = 160) -> bool:
    if not content:
        return False
    tail = content[-window:]
    return any(p in tail for p in _TAIL_NOISE)


def parse_date(row: dict):
    """Return (date_or_None, status) where status in valid/missing/unparseable/future/too_old."""
    raw = row.get("publish_time")
    d = None
    if raw:
        s = str(raw).strip()
        for fmt, cut in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19),
                         ("%Y-%m-%d", 10), ("%Y/%m/%d", 10)):
            try:
                d = dt.datetime.strptime(s[:cut], fmt).date()
                break
            except Exception:
                continue
        if d is None:
            m = re.match(r"(\d{4})\D(\d{1,2})\D(\d{1,2})", s)
            if m:
                try:
                    d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except Exception:
                    d = None
    if d is None and row.get("publish_ts"):
        try:
            d = dt.datetime.fromtimestamp(int(row["publish_ts"])).date()
        except Exception:
            d = None
    if d is None:
        return None, ("missing" if not raw and not row.get("publish_ts") else "unparseable")
    if d > TODAY:
        return d, "future"
    if d.year < EARLIEST_VALID_YEAR:
        return d, "too_old"
    return d, "valid"


# ---------------------------------------------------------------------------------
# section 1 + 2 : load corpus, base stats, quality flags
# ---------------------------------------------------------------------------------
def load_and_scan(corpus_path: Path):
    docs = []  # lightweight per-doc records kept for dedup / gold
    parse_errors = 0
    field_presence = collections.Counter()
    source_dist = collections.Counter()
    year_dist = collections.Counter()
    month_dist = collections.Counter()
    content_type_dist = collections.Counter()
    section_dist = collections.Counter()
    category_dist = collections.Counter()
    date_status = collections.Counter()

    content_lengths = []
    quality = collections.Counter()
    examples = collections.defaultdict(list)  # flag -> few example doc_ids

    has_content_type_field = False

    with corpus_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                parse_errors += 1
                continue
            if not isinstance(row, dict):
                parse_errors += 1
                continue

            for k in row:
                field_presence[k] += 1

            doc_id = row.get("doc_id") or row.get("evidence_id") or row.get("source_doc_id") or ""
            evidence_id = (row.get("evidence_id") or "").strip()
            title = (row.get("title") or "").strip()
            content = (row.get("content") or "").strip()
            source = (row.get("source") or "").strip() or "(unknown)"

            source_dist[source] += 1
            if row.get("section"):
                section_dist[str(row["section"])] += 1
            if row.get("category"):
                category_dist[str(row["category"])] += 1
            if "content_type" in row and row.get("content_type") is not None:
                has_content_type_field = True
                content_type_dist[str(row["content_type"])] += 1

            d, dstatus = parse_date(row)
            date_status[dstatus] += 1
            if d is not None:
                year_dist[d.year] += 1
                month_dist[f"{d.year}-{d.month:02d}"] += 1

            clen = len(content)
            content_lengths.append(clen)

            # quality flags
            flags = []
            if not title:
                quality["empty_title"] += 1
                flags.append("empty_title")
            if not content:
                quality["empty_content"] += 1
                flags.append("empty_content")
            if 0 < clen < 80:
                quality["too_short_lt80"] += 1
            if 0 < clen < 200:
                quality["too_short_lt200"] += 1
            if 0 < clen < 500:
                quality["too_short_lt500"] += 1
            if dstatus in ("missing", "unparseable", "future", "too_old"):
                quality[f"date_{dstatus}"] += 1
            if title and is_garbled(title):
                quality["title_garbled"] += 1
                flags.append("title_garbled")
            if content and is_garbled(content):
                quality["content_garbled"] += 1
                flags.append("content_garbled")
            if content and HTML_RE.search(content):
                quality["html_residue"] += 1
                flags.append("html_residue")
            if content and URL_RE.search(content):
                quality["url_residue"] += 1
                flags.append("url_residue")
            if content and has_tail_noise(content):
                quality["tail_noise"] += 1
                flags.append("tail_noise")

            for fl in flags:
                if len(examples[fl]) < 5:
                    examples[fl].append(doc_id or evidence_id)

            docs.append({
                "doc_id": doc_id,
                "evidence_id": evidence_id,
                "title": title,
                "source": source,
                "date": d.isoformat() if d else None,
                "date_status": dstatus,
                "clen": clen,
                "title_hash": sha1(norm_ws(title)) if title else "",
                "content_hash": sha1(norm_ws(content)) if content else "",
                "content_head": norm_ws(content)[:1000],
            })

    return {
        "docs": docs,
        "parse_errors": parse_errors,
        "field_presence": field_presence,
        "source_dist": source_dist,
        "year_dist": year_dist,
        "month_dist": month_dist,
        "content_type_dist": content_type_dist,
        "has_content_type_field": has_content_type_field,
        "section_dist": section_dist,
        "category_dist": category_dist,
        "date_status": date_status,
        "content_lengths": content_lengths,
        "quality": quality,
        "examples": examples,
    }


# ---------------------------------------------------------------------------------
# section 3 : duplicate detection
# ---------------------------------------------------------------------------------
class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def detect_duplicates(docs, *, window=4, title_sim=0.90, content_sim=0.95, max_examples=30):
    # exact duplicates
    by_chash = collections.defaultdict(list)
    by_thash = collections.defaultdict(list)
    for i, d in enumerate(docs):
        if d["content_hash"]:
            by_chash[d["content_hash"]].append(i)
        if d["title_hash"]:
            by_thash[d["title_hash"]].append(i)

    exact_content_groups = [idxs for idxs in by_chash.values() if len(idxs) > 1]
    exact_title_groups = [idxs for idxs in by_thash.values() if len(idxs) > 1]
    dup_content_docs = sum(len(g) - 1 for g in exact_content_groups)
    dup_title_docs = sum(len(g) - 1 for g in exact_title_groups)

    # near duplicates within (source, day) buckets, bounded by a sorted window
    buckets = collections.defaultdict(list)
    for i, d in enumerate(docs):
        if d["date"]:
            buckets[(d["source"], d["date"])].append(i)

    uf = UnionFind()
    near_pairs = 0
    comparisons = 0
    for key, idxs in buckets.items():
        if len(idxs) < 2:
            continue
        # title pass
        by_title = sorted(idxs, key=lambda i: docs[i]["title"])
        for a in range(len(by_title)):
            for b in range(a + 1, min(a + 1 + window, len(by_title))):
                i, j = by_title[a], by_title[b]
                if docs[i]["content_hash"] and docs[i]["content_hash"] == docs[j]["content_hash"]:
                    continue  # already exact
                comparisons += 1
                if is_similar(docs[i]["title"], docs[j]["title"], title_sim):
                    uf.union(i, j)
                    near_pairs += 1
        # content-head pass
        by_head = sorted(idxs, key=lambda i: docs[i]["content_head"][:200])
        for a in range(len(by_head)):
            for b in range(a + 1, min(a + 1 + window, len(by_head))):
                i, j = by_head[a], by_head[b]
                if docs[i]["content_hash"] and docs[i]["content_hash"] == docs[j]["content_hash"]:
                    continue
                comparisons += 1
                if is_similar(docs[i]["content_head"], docs[j]["content_head"], content_sim):
                    uf.union(i, j)
                    near_pairs += 1

    near_groups_map = collections.defaultdict(set)
    for i in list(uf.parent.keys()):
        near_groups_map[uf.find(i)].add(i)
    near_groups = [sorted(g) for g in near_groups_map.values() if len(g) > 1]

    def describe(group):
        return {
            "size": len(group),
            "date": docs[group[0]]["date"],
            "source": docs[group[0]]["source"],
            "examples": [
                {"doc_id": docs[i]["doc_id"], "title": docs[i]["title"][:60], "clen": docs[i]["clen"]}
                for i in group[:4]
            ],
        }

    exact_examples = sorted(exact_content_groups, key=len, reverse=True)[:max_examples]
    near_examples = sorted(near_groups, key=len, reverse=True)[:max_examples]

    return {
        "exact_content_group_count": len(exact_content_groups),
        "exact_title_group_count": len(exact_title_groups),
        "dup_content_docs": dup_content_docs,
        "dup_title_docs": dup_title_docs,
        "near_group_count": len(near_groups),
        "near_pair_count": near_pairs,
        "near_comparisons": comparisons,
        "exact_top_groups": [describe(g) for g in exact_examples],
        "near_top_groups": [describe(g) for g in near_examples],
    }


# ---------------------------------------------------------------------------------
# section 4 : gold evidence coverage
# ---------------------------------------------------------------------------------
def discover_gold_files(eval_dir: Path):
    candidates = []
    for pat in ("gold/**/*.jsonl", "gold/**/*.json", "**/*gold*.jsonl", "**/*gold*.json"):
        for p in eval_dir.glob(pat):
            if "reports" in p.parts:
                continue
            if p.is_file():
                candidates.append(p)
    # de-dup, prefer the retrieval gold
    seen, ordered = set(), []
    for p in sorted(candidates, key=lambda x: (("retrieval" not in x.name), len(str(x)))):
        if p.resolve() not in seen:
            seen.add(p.resolve())
            ordered.append(p)
    return ordered


def load_gold(path: Path):
    cases = []
    with path.open("r", encoding="utf-8") as f:
        if path.suffix == ".jsonl":
            for line in f:
                line = line.strip()
                if line:
                    try:
                        cases.append(json.loads(line))
                    except Exception:
                        pass
        else:
            data = json.load(f)
            if isinstance(data, list):
                cases = data
            elif isinstance(data, dict):
                for key in ("cases", "gold", "data", "items"):
                    if isinstance(data.get(key), list):
                        cases = data[key]
                        break
    return cases


def audit_gold(docs, gold_cases):
    corpus_ev = {d["evidence_id"] for d in docs if d["evidence_id"]}
    ev_to_doc = {d["evidence_id"]: d for d in docs if d["evidence_id"]}

    answerable = 0
    covered_cases = 0
    missing_cases = 0
    short_cases = 0
    quality_mismatch_cases = 0
    ev_total = 0
    ev_found = 0
    missing_examples = []

    for c in gold_cases:
        gold_ids = c.get("gold_evidence_ids") or c.get("gold_evidence") or []
        if isinstance(gold_ids, str):
            gold_ids = [gold_ids]
        should_answer = c.get("should_answer", bool(gold_ids))
        if not gold_ids or should_answer is False:
            continue  # no-answer / refusal cases excluded from coverage denominator
        answerable += 1
        present = [g for g in gold_ids if g in corpus_ev]
        absent = [g for g in gold_ids if g not in corpus_ev]
        ev_total += len(gold_ids)
        ev_found += len(present)
        if absent:
            missing_cases += 1
            if len(missing_examples) < 15:
                missing_examples.append({"id": c.get("id"), "missing": absent, "question": (c.get("question") or "")[:60]})
        else:
            covered_cases += 1
        # quality of matched gold docs
        matched_docs = [ev_to_doc[g] for g in present]
        if matched_docs and any(md["clen"] < 200 for md in matched_docs):
            short_cases += 1
        if matched_docs and any(
            (md["date_status"] not in ("valid",)) or (not md["title"]) for md in matched_docs
        ):
            quality_mismatch_cases += 1

    return {
        "gold_total_cases": len(gold_cases),
        "answerable_cases": answerable,
        "gold_covered_count": covered_cases,
        "gold_missing_count": missing_cases,
        "gold_short_count": short_cases,
        "gold_mismatch_count": quality_mismatch_cases,
        "evidence_refs_total": ev_total,
        "evidence_refs_found": ev_found,
        "gold_coverage_rate_cases": pct(covered_cases, answerable),
        "gold_coverage_rate_refs": pct(ev_found, ev_total),
        "missing_examples": missing_examples,
    }


# ---------------------------------------------------------------------------------
# section 5 : failure attribution from existing diagnosis reports
# ---------------------------------------------------------------------------------
BUCKET_TO_CLASS = {
    "gold_not_in_corpus": "A",
    "possible_gold_issue": "A",
    "chunk_not_indexed": "B",
    "gold_chunk_missing": "B",
    "gold_not_in_top20": "C",
    "gold_in_top20_not_top5": "D",
    "query_rewrite_or_ranking": "E",
    "source_filter_mismatch": "E",
    "date_filter_mismatch": "E",
    "route_mismatch": "F",
    "no_answer_route_error": "F",
}
CLASS_LABELS = {
    "A": "gold 不在 clean corpus",
    "B": "gold 在 corpus，但 chunk 不在 PG/Qdrant",
    "C": "gold chunk 在 Qdrant，但没进 top20",
    "D": "gold 进 top20，但没进 top5",
    "E": "query rewrite / source / date filter 误杀",
    "F": "no-answer / route 误判",
    "U": "未能自动归类（需人工）",
}


def _find_reports(reports_dir: Path, must_contain, prefer):
    files = []
    for p in reports_dir.glob("*.json"):
        name = p.name.lower()
        if all(t in name for t in must_contain):
            files.append(p)
    files.sort(key=lambda p: (0 if any(t in p.name.lower() for t in prefer) else 1, p.name), reverse=False)
    return files


def attribute_failures(reports_dir: Path, corpus_ev: set):
    # locate a v2 diagnosis report that carries a per-case 'diagnostics' list
    candidates = []
    for p in reports_dir.glob("*.json"):
        n = p.name.lower()
        if "diagnosis" in n or "diagnostic" in n:
            candidates.append(p)
    # prefer v2 / bge_m3, then warm, then anything with diagnostics
    def score(p):
        n = p.name.lower()
        return (("v2" in n or "bge_m3" in n), "warm" not in n, n)
    candidates.sort(key=score, reverse=True)

    chosen = None
    diagnostics = []
    summary = {}
    for p in candidates:
        try:
            data = json.load(p.open("r", encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("diagnostics"), list) and data["diagnostics"]:
            chosen = p
            diagnostics = data["diagnostics"]
            summary = {
                "metrics": data.get("metrics", {}),
                "gold_existence_summary": data.get("gold_existence_summary", {}),
            }
            break

    rows = []
    class_counts = collections.Counter()
    if chosen:
        for c in diagnostics:
            gold_ids = c.get("gold_evidence_ids") or []
            ranks = c.get("gold_ranks") or {}
            nn = [r for r in ranks.values() if r is not None]
            in_corpus = all((g in corpus_ev) for g in gold_ids) if gold_ids else None
            buckets = c.get("buckets") or []

            # classification priority: corpus gap (A) > index gap (B) > position (C/D) > filter (E) > route (F)
            cls = None
            if gold_ids and in_corpus is False:
                cls = "A"
            else:
                mapped = [BUCKET_TO_CLASS[b] for b in buckets if b in BUCKET_TO_CLASS]
                for pref in ("B", "C", "D", "E", "F", "A"):
                    if pref in mapped:
                        cls = pref
                        break
                if cls is None:
                    # fall back to rank evidence
                    if gold_ids and not nn:
                        cls = "C"  # exists but never retrieved
                    elif nn and min(nn) > 5:
                        cls = "D"
                    elif c.get("expected_route") and c.get("route") and c["expected_route"] != c["route"]:
                        cls = "F"
                    else:
                        cls = "U"
            class_counts[cls] += 1
            rows.append({
                "id": c.get("id"),
                "case_type": c.get("case_type"),
                "expected_route": c.get("expected_route"),
                "route": c.get("route"),
                "gold_in_corpus": in_corpus,
                "best_rank": (min(nn) if nn else None),
                "buckets": buckets,
                "class": cls,
            })

    return {
        "source_report": str(chosen.relative_to(reports_dir.parent.parent)) if chosen else None,
        "summary": summary,
        "class_counts": dict(class_counts),
        "rows": rows,
    }


# ---------------------------------------------------------------------------------
# section 6 : optional, read-only PG / Qdrant reconciliation
# ---------------------------------------------------------------------------------
def reconcile_db(project_root: Path, corpus_doc_count: int, enabled: bool):
    out = {"attempted": enabled, "qdrant": None, "postgres": None, "notes": []}
    if not enabled:
        out["notes"].append("DB reconciliation disabled (--no-db).")
        return out

    # --- Qdrant (read-only count + 1-point payload sample) ---
    try:
        qurl = os.getenv("QDRANT_URL", "http://localhost:6333")
        collection = os.getenv("RAG_CHUNK_COLLECTION_V2", "news_chunks_v2")
        try:
            from qdrant_client import QdrantClient
        except Exception:
            out["notes"].append("qdrant_client not importable in this interpreter; Qdrant check skipped.")
            raise StopIteration
        client = QdrantClient(url=qurl, timeout=5)
        exists = collection in {c.name for c in client.get_collections().collections}
        if not exists:
            out["qdrant"] = {"collection": collection, "exists": False}
            out["notes"].append(f"Qdrant collection '{collection}' not found (read-only).")
        else:
            cnt = client.count(collection_name=collection, exact=True).count
            pts, _ = client.scroll(collection_name=collection, limit=1, with_payload=True, with_vectors=False)
            payload_keys = sorted((pts[0].payload or {}).keys()) if pts else []
            has_meta = {k: (k in payload_keys) for k in ("title", "source", "date", "publish_time", "evidence_id", "parent_news_id")}
            out["qdrant"] = {
                "collection": collection, "exists": True, "points_count": cnt,
                "payload_keys_sample": payload_keys[:30], "has_meta": has_meta,
                "avg_chunks_per_parent": (round(cnt / corpus_doc_count, 2) if corpus_doc_count else None),
            }
        try:
            client.close()
        except Exception:
            pass
    except StopIteration:
        pass
    except Exception as e:  # pragma: no cover
        out["notes"].append(f"Qdrant read-only check failed: {e!r}")

    # --- PostgreSQL (read-only counts) ---
    dsn = os.getenv("PG_DSN") or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        out["notes"].append("No PG DSN configured (PG_DSN/DATABASE_URL/POSTGRES_DSN); PostgreSQL check skipped.")
        return out
    try:
        try:
            import psycopg
            conn = psycopg.connect(dsn, connect_timeout=5)
        except Exception:
            import psycopg2  # type: ignore
            conn = psycopg2.connect(dsn, connect_timeout=5)
        res = {}
        with conn.cursor() as cur:
            for label, sql in (
                ("news_unified_parent", "SELECT COUNT(*) FROM news_unified"),
                ("news_chunks_meta", "SELECT COUNT(*) FROM news_chunks_meta"),
            ):
                try:
                    cur.execute(sql)
                    res[label] = cur.fetchone()[0]
                except Exception as e:
                    res[label] = f"err: {e!r}"
                    conn.rollback()
        conn.close()
        out["postgres"] = res
    except Exception as e:  # pragma: no cover
        out["notes"].append(f"PostgreSQL read-only check skipped/failed: {e!r}")
    return out


# ---------------------------------------------------------------------------------
# section 7 : recommendation
# ---------------------------------------------------------------------------------
def build_recommendation(report):
    total = report["base"]["parent_docs"]
    q = report["quality"]["counts"]
    cov = report["gold_coverage"]
    dup = report["duplicates"]
    fail = report["failure_attribution"]["class_counts"]

    dup_content_ratio = pct(dup["dup_content_docs"], total)
    too_short_ratio = pct(q.get("too_short_lt200", 0), total)
    missing_date_ratio = pct(
        q.get("date_missing", 0) + q.get("date_unparseable", 0), total
    )
    obvious_noise_ratio = pct(
        q.get("html_residue", 0) + q.get("tail_noise", 0) + q.get("content_garbled", 0), total
    )
    coverage_rate = cov["gold_coverage_rate_refs"]
    ab_class = fail.get("A", 0) + fail.get("B", 0)
    total_failed = sum(fail.values()) if fail else 0

    rules = []

    def rule(name, value, op, threshold, hit):
        rules.append({"rule": name, "value": round(value, 4) if isinstance(value, float) else value,
                      "op": op, "threshold": threshold, "triggered": hit})

    r1 = coverage_rate < 0.95
    rule("gold_coverage_rate < 0.95", coverage_rate, "<", 0.95, r1)
    r2 = dup_content_ratio > 0.10
    rule("duplicate_content_ratio > 0.10", dup_content_ratio, ">", 0.10, r2)
    r3 = too_short_ratio > 0.10
    rule("too_short_ratio(<200) > 0.10", too_short_ratio, ">", 0.10, r3)
    r4 = missing_date_ratio > 0.05
    rule("missing_date_ratio > 0.05", missing_date_ratio, ">", 0.05, r4)
    r5 = obvious_noise_ratio > 0.05
    rule("obvious_noise_ratio > 0.05", obvious_noise_ratio, ">", 0.05, r5)
    r6 = (total_failed > 0) and (pct(ab_class, total_failed) >= 0.30)
    rule("A/B-class failures share >= 0.30", pct(ab_class, total_failed), ">=", 0.30, r6)

    triggered = [r for r in rules if r["triggered"]]

    if any((r1, r2, r4)) or (r6 and ab_class >= 3):
        verdict = "RECLEAN_OR_PATCH"
        headline = "需要重新清洗或局部清洗补丁"
    elif any((r3, r5)):
        verdict = "LOCAL_PATCH"
        headline = "建议做局部清洗补丁（噪声/过短），暂不必全量重洗"
    else:
        verdict = "PROCEED_RETRIEVAL_OPT"
        headline = "数据质量问题不显著，建议进入 3.2-C retrieval optimization"

    actions = []
    if verdict == "PROCEED_RETRIEVAL_OPT":
        actions = [
            "query rewrite（同义/扩写，降低 gold_not_in_top20）",
            "light rerank（top20 → top5，针对 gold_in_top20_not_top5）",
            "source/date filter 边界放宽，避免误杀",
            "no-answer route 阈值校准",
            "bge-m3 multi-query 延迟控制（关键：LatencyP95 超标）",
        ]
    elif verdict == "LOCAL_PATCH":
        actions = [
            "对 tail-noise / HTML 残留做正则补丁清洗（仅 clean corpus，不动原始 3G）",
            "过短正文复核：是否截断或采集不全",
            "随后再做 retrieval optimization",
        ]
    else:
        actions = [
            "定位缺失 gold 对应的原始文档，做针对性补采/重洗（局部）",
            "若缺失/重复/日期问题成规模，再评估是否全量重洗",
            "重洗后才考虑重建 chunk / 索引（本次不做）",
        ]

    return {
        "metrics": {
            "gold_coverage_rate_refs": round(coverage_rate, 4),
            "gold_coverage_rate_cases": round(cov["gold_coverage_rate_cases"], 4),
            "duplicate_content_ratio": round(dup_content_ratio, 4),
            "too_short_ratio_lt200": round(too_short_ratio, 4),
            "missing_date_ratio": round(missing_date_ratio, 4),
            "obvious_noise_ratio": round(obvious_noise_ratio, 4),
            "ab_class_failures": ab_class,
            "total_failed_cases": total_failed,
        },
        "rules": rules,
        "triggered_rules": [r["rule"] for r in triggered],
        "verdict": verdict,
        "headline": headline,
        "need_reclean": verdict == "RECLEAN_OR_PATCH",
        "recommended_actions": actions,
        "answers": {
            "reclean_raw_3g": verdict == "RECLEAN_OR_PATCH",
            "local_clean_patch_only": verdict == "LOCAL_PATCH",
            "prioritize_retrieval_optimization": verdict == "PROCEED_RETRIEVAL_OPT",
            "adjust_chunk_strategy": False,
            "adjust_rerank_query_rewrite": verdict != "RECLEAN_OR_PATCH",
            "reduce_latency": True,  # LatencyP95 gate has been failing in v2 reports
        },
    }


# ---------------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------------
def top_items(counter, n=20):
    return counter.most_common(n)


def render_md(report) -> str:
    b = report["base"]
    q = report["quality"]
    dup = report["duplicates"]
    cov = report["gold_coverage"]
    fa = report["failure_attribution"]
    rec = report["recommendation"]
    L = []
    A = L.append
    A(f"# Clean Corpus Audit — {report['meta']['date']}")
    A("")
    A(f"- corpus: `{report['meta']['corpus']}`")
    A(f"- parent docs: **{b['parent_docs']}**  | parse errors: {b['parse_errors']}")
    A(f"- rapidfuzz: {'yes' if report['meta']['have_rapidfuzz'] else 'no (difflib fallback)'}  "
      f"| generated by `scripts/clean_corpus_audit.py` (read-only)")
    A("")
    A("> 本审计严格只读：未修改 MySQL/PostgreSQL/Qdrant，未重建 news_chunks_v2，未读取原始 3G，未做 embedding / upsert。")
    A("")

    # verdict up top
    A("## 结论速览")
    A("")
    A(f"**判定：{rec['headline']}** (`{rec['verdict']}`)")
    A("")
    A(f"- 是否需要重新清洗原始 3G：**{'是' if rec['answers']['reclean_raw_3g'] else '否'}**")
    A(f"- 是否只需局部清洗补丁：**{'是' if rec['answers']['local_clean_patch_only'] else '否'}**")
    A(f"- 是否优先做 retrieval optimization：**{'是' if rec['answers']['prioritize_retrieval_optimization'] else '否'}**")
    A(f"- 是否调整 chunk 策略：**{'是' if rec['answers']['adjust_chunk_strategy'] else '否'}**")
    A(f"- 是否调整 rerank / query rewrite：**{'是' if rec['answers']['adjust_rerank_query_rewrite'] else '否'}**")
    A(f"- 是否需要降低 latency：**{'是' if rec['answers']['reduce_latency'] else '否'}**")
    A("")

    # 1. base
    A("## 一、语料基础统计")
    A("")
    A(f"- parent docs 总数：**{b['parent_docs']}**")
    A(f"- 平均正文字数：**{b['avg_content_len']}**")
    A("")
    A("正文字数分布：")
    A("")
    A("| min | p25 | p50 | p75 | p90 | p95 | max |")
    A("|---|---|---|---|---|---|---|")
    p = b["content_len_percentiles"]
    A(f"| {p['min']} | {p['p25']} | {p['p50']} | {p['p75']} | {p['p90']} | {p['p95']} | {p['max']} |")
    A("")
    A(f"过短正文：<80 = **{q['counts'].get('too_short_lt80',0)}**, "
      f"<200 = **{q['counts'].get('too_short_lt200',0)}**, "
      f"<500 = **{q['counts'].get('too_short_lt500',0)}**")
    A("")
    A("source 分布：")
    A("")
    A("| source | docs |")
    A("|---|---|")
    for k, v in b["source_dist"]:
        A(f"| {k} | {v} |")
    A("")
    A("publish_year 分布： " + ", ".join(f"{k}: {v}" for k, v in b["year_dist"]))
    A("")
    A("publish_month 分布（Top 18）： " + ", ".join(f"{k}: {v}" for k, v in b["month_dist"][:18]))
    A("")
    if report["base"]["has_content_type_field"]:
        A("content_type 分布： " + ", ".join(f"{k}: {v}" for k, v in b["content_type_dist"]))
    else:
        A("content_type 分布：_corpus 无 `content_type` 字段_；改列 section / category：")
        A("")
        A("- section(Top10)： " + ", ".join(f"{k}:{v}" for k, v in b["section_dist"][:10]))
        A("- category(Top10)： " + ", ".join(f"{k}:{v}" for k, v in b["category_dist"][:10]))
    A("")
    A(f"缺失：title 缺失 = **{q['counts'].get('empty_title',0)}**, "
      f"content 缺失 = **{q['counts'].get('empty_content',0)}**, "
      f"date 缺失/无法解析 = **{q['counts'].get('date_missing',0) + q['counts'].get('date_unparseable',0)}**")
    A("")

    # 2. quality
    A("## 二、质量问题检查")
    A("")
    A("| 检查项 | 数量 |")
    A("|---|---|")
    qc = q["counts"]
    rows = [
        ("空标题 empty_title", qc.get("empty_title", 0)),
        ("空正文 empty_content", qc.get("empty_content", 0)),
        ("正文过短 (<200)", qc.get("too_short_lt200", 0)),
        ("标题疑似乱码", qc.get("title_garbled", 0)),
        ("正文疑似乱码", qc.get("content_garbled", 0)),
        ("HTML 残留", qc.get("html_residue", 0)),
        ("URL 残留", qc.get("url_residue", 0)),
        ("尾部噪声(责编/下载客户端/版权声明等)", qc.get("tail_noise", 0)),
        ("异常日期-未来", qc.get("date_future", 0)),
        ("异常日期-1949前", qc.get("date_too_old", 0)),
        ("异常日期-无法解析", qc.get("date_unparseable", 0)),
        ("异常日期-缺失", qc.get("date_missing", 0)),
        ("重复标题(精确)", dup["dup_title_docs"]),
        ("重复正文 hash(精确)", dup["dup_content_docs"]),
        ("同日近似重复(组)", dup["near_group_count"]),
    ]
    for name, val in rows:
        A(f"| {name} | {val} |")
    A("")
    if q["examples"]:
        A("部分问题样例（doc_id）：")
        A("")
        for fl, ex in q["examples"].items():
            if ex:
                A(f"- `{fl}`: " + ", ".join(f"`{e}`" for e in ex))
        A("")

    # 3. duplicates
    A("## 三、重复检测")
    A("")
    A(f"- 精确：content_hash 重复组 = **{dup['exact_content_group_count']}**（多余文档 {dup['dup_content_docs']}）；"
      f"title_hash 重复组 = **{dup['exact_title_group_count']}**（多余 {dup['dup_title_docs']}）")
    A(f"- 近似：同日(source+day) 近似重复组 = **{dup['near_group_count']}**，"
      f"pair = {dup['near_pair_count']}，比较次数 = {dup['near_comparisons']}"
      f"（title≥0.90 或 content[:1000]≥0.95）")
    A("")
    A("Top 重复组（精确 content）：")
    A("")
    A("| size | date | source | 标题示例 |")
    A("|---|---|---|---|")
    for g in dup["exact_top_groups"][:30]:
        ttl = " ⏐ ".join(e["title"] for e in g["examples"][:2])
        A(f"| {g['size']} | {g['date']} | {g['source']} | {ttl} |")
    A("")
    if dup["near_top_groups"]:
        A("Top 重复组（近似，同日）：")
        A("")
        A("| size | date | source | 标题示例 |")
        A("|---|---|---|---|")
        for g in dup["near_top_groups"][:30]:
            ttl = " ⏐ ".join(e["title"] for e in g["examples"][:2])
            A(f"| {g['size']} | {g['date']} | {g['source']} | {ttl} |")
        A("")

    # 4. gold coverage
    A("## 四、gold evidence 覆盖检查")
    A("")
    A(f"- gold 文件：{', '.join(report['gold_coverage']['gold_files']) or '(none found)'}")
    A(f"- gold case 总数：**{cov['gold_total_cases']}**（可作答 answerable：{cov['answerable_cases']}）")
    A(f"- gold_covered_count：**{cov['gold_covered_count']}**")
    A(f"- gold_missing_count：**{cov['gold_missing_count']}**")
    A(f"- gold_mismatch_count（matched 但质量异常）：**{cov['gold_mismatch_count']}**；其中正文过短 {cov['gold_short_count']}")
    A(f"- gold_coverage_rate（case 级）：**{cov['gold_coverage_rate_cases']:.3f}**；"
      f"（evidence-id 级）：**{cov['gold_coverage_rate_refs']:.3f}** "
      f"（{cov['evidence_refs_found']}/{cov['evidence_refs_total']}）")
    A("")
    if cov["missing_examples"]:
        A("Top missing examples：")
        A("")
        for m in cov["missing_examples"]:
            A(f"- `{m['id']}` — missing {m['missing']} — {m['question']}")
        A("")
    else:
        A("_无缺失 gold（answerable 全覆盖）_")
        A("")

    # 5. failure attribution
    A("## 五、失败案例归因（基于现有 diagnosis 报告）")
    A("")
    if fa["source_report"]:
        A(f"- 来源报告：`{fa['source_report']}`")
        m = fa["summary"].get("metrics", {})
        if m:
            A(f"- v2 指标：Recall@5={m.get('Recall@5')}, EvidenceRecall@5={m.get('EvidenceRecall@5')}, "
              f"MRR={m.get('MRR')}, RouteAcc={m.get('RouteAccuracy')}, "
              f"LatencyP50={m.get('LatencyP50')}, LatencyP95={m.get('LatencyP95')}")
        ge = fa["summary"].get("gold_existence_summary", {})
        if ge:
            A(f"- gold_existence：checked={ge.get('gold_refs_checked')}, exists={ge.get('exists')}, "
              f"missing={ge.get('missing')}, source_hits={ge.get('source_hits')}")
        A("")
        A("归因分布：")
        A("")
        A("| 类别 | 含义 | 数量 |")
        A("|---|---|---|")
        for cls in ("A", "B", "C", "D", "E", "F", "U"):
            if fa["class_counts"].get(cls):
                A(f"| {cls} | {CLASS_LABELS[cls]} | {fa['class_counts'][cls]} |")
        A("")
        A("逐案表：")
        A("")
        A("| id | case_type | route(exp→act) | gold_in_corpus | best_rank | buckets | 类别 |")
        A("|---|---|---|---|---|---|---|")
        for r in fa["rows"]:
            route = f"{r['expected_route']}→{r['route']}"
            A(f"| {r['id']} | {r['case_type']} | {route} | {r['gold_in_corpus']} | "
              f"{r['best_rank']} | {','.join(r['buckets'])} | {r['class']} |")
        A("")
    else:
        A("_未找到带 per-case `diagnostics` 的 v2 诊断报告；无法自动归因，请人工分析 eval/reports/ 下的 diagnosis 文件。_")
        A("")

    # 6. db reconcile
    A("## 六、PG / Qdrant 对账（只读，可选）")
    A("")
    db = report["db_reconcile"]
    if db.get("qdrant"):
        qd = db["qdrant"]
        if qd.get("exists"):
            A(f"- Qdrant `{qd['collection']}` points_count = **{qd['points_count']}**，"
              f"clean corpus docs = **{b['parent_docs']}**，"
              f"平均 chunks/parent ≈ **{qd.get('avg_chunks_per_parent')}**")
            A(f"- payload meta：{qd.get('has_meta')}")
        else:
            A(f"- Qdrant collection `{qd['collection']}` 不存在或不可读。")
    if db.get("postgres"):
        A(f"- PostgreSQL：{db['postgres']}")
    for note in db.get("notes", []):
        A(f"- _{note}_")
    A("")

    # 7. recommendation detail
    A("## 七、最终建议（判定规则）")
    A("")
    A("| 规则 | 实测值 | 阈值 | 触发? |")
    A("|---|---|---|---|")
    for r in rec["rules"]:
        A(f"| {r['rule']} | {r['value']} | {r['op']} {r['threshold']} | {'✅触发' if r['triggered'] else '—'} |")
    A("")
    A(f"**判定：{rec['headline']}**")
    A("")
    A("建议动作：")
    for a in rec["recommended_actions"]:
        A(f"- {a}")
    A("")
    return "\n".join(L)


# ---------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only clean corpus audit (no DB writes / no embedding).")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--output-md", required=True)
    ap.add_argument("--output-json", required=True)
    ap.add_argument("--eval-dir", default="eval")
    ap.add_argument("--reports-dir", default="eval/reports")
    ap.add_argument("--gold", default=None, help="explicit gold file; otherwise auto-discovered under --eval-dir")
    ap.add_argument("--near-dup-window", type=int, default=4)
    ap.add_argument("--max-dup-examples", type=int, default=30)
    ap.add_argument("--no-db", action="store_true", help="skip optional read-only PG/Qdrant reconciliation")
    args = ap.parse_args(argv)

    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        print(f"[ERROR] corpus not found: {corpus_path}", file=sys.stderr)
        return 2
    project_root = Path.cwd()
    eval_dir = Path(args.eval_dir)
    reports_dir = Path(args.reports_dir)

    if not HAVE_RAPIDFUZZ:
        print("[info] rapidfuzz 未安装，近似重复改用 difflib 回退（较慢但可用）。"
              "如需更快/更准： pip install rapidfuzz", file=sys.stderr)

    print(f"[1/6] scanning corpus: {corpus_path} ...", file=sys.stderr)
    scan = load_and_scan(corpus_path)
    docs = scan["docs"]
    total = len(docs)
    corpus_ev = {d["evidence_id"] for d in docs if d["evidence_id"]}

    print(f"[2/6] duplicate detection over {total} docs ...", file=sys.stderr)
    dup = detect_duplicates(docs, window=args.near_dup_window, max_examples=args.max_dup_examples)

    print("[3/6] gold coverage ...", file=sys.stderr)
    if args.gold:
        gold_files = [Path(args.gold)]
    else:
        gold_files = discover_gold_files(eval_dir)
    gold_cases = []
    used_gold = []
    for gf in gold_files[:1] or []:  # primary gold (retrieval) for coverage rate
        cases = load_gold(gf)
        if cases:
            gold_cases = cases
            used_gold.append(str(gf))
            break
    cov = audit_gold(docs, gold_cases) if gold_cases else {
        "gold_total_cases": 0, "answerable_cases": 0, "gold_covered_count": 0,
        "gold_missing_count": 0, "gold_short_count": 0, "gold_mismatch_count": 0,
        "evidence_refs_total": 0, "evidence_refs_found": 0,
        "gold_coverage_rate_cases": 1.0, "gold_coverage_rate_refs": 1.0, "missing_examples": [],
    }
    cov["gold_files"] = used_gold

    print("[4/6] failure attribution ...", file=sys.stderr)
    fa = attribute_failures(reports_dir, corpus_ev) if reports_dir.exists() else {
        "source_report": None, "summary": {}, "class_counts": {}, "rows": []}

    print("[5/6] (optional) read-only DB reconcile ...", file=sys.stderr)
    db = reconcile_db(project_root, total, enabled=not args.no_db)

    # base stats
    lens = scan["content_lengths"]
    perc = percentiles(lens, [25, 50, 75, 90, 95])
    base = {
        "parent_docs": total,
        "parse_errors": scan["parse_errors"],
        "avg_content_len": round(sum(lens) / total, 1) if total else 0,
        "content_len_percentiles": {
            "min": min(lens) if lens else 0, "p25": perc[25], "p50": perc[50],
            "p75": perc[75], "p90": perc[90], "p95": perc[95], "max": max(lens) if lens else 0,
        },
        "source_dist": top_items(scan["source_dist"], 30),
        "year_dist": sorted(scan["year_dist"].items()),
        "month_dist": sorted(scan["month_dist"].items()),
        "has_content_type_field": scan["has_content_type_field"],
        "content_type_dist": top_items(scan["content_type_dist"], 30),
        "section_dist": top_items(scan["section_dist"], 20),
        "category_dist": top_items(scan["category_dist"], 20),
        "field_presence": dict(scan["field_presence"]),
    }
    # rename date status counts into quality keys
    qcounts = dict(scan["quality"])

    print("[6/6] rendering report ...", file=sys.stderr)
    report = {
        "meta": {
            "date": "2026-06-22",
            "corpus": str(corpus_path),
            "have_rapidfuzz": HAVE_RAPIDFUZZ,
            "read_only": True,
        },
        "base": base,
        "quality": {"counts": qcounts, "examples": dict(scan["examples"])},
        "duplicates": dup,
        "gold_coverage": cov,
        "failure_attribution": fa,
        "db_reconcile": db,
    }
    report["recommendation"] = build_recommendation(report)

    Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_md).write_text(render_md(report), encoding="utf-8")
    Path(args.output_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    rec = report["recommendation"]
    print(f"\n[done] verdict = {rec['verdict']} :: {rec['headline']}", file=sys.stderr)
    print(f"[done] MD  -> {args.output_md}", file=sys.stderr)
    print(f"[done] JSON-> {args.output_json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
