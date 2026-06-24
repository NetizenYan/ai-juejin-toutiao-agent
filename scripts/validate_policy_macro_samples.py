"""Validate local policy_macro manual samples.

This script only reads local files under data/policy_macro_manual_samples.
It does not access external websites, download data, modify RAG collections,
or write to databases.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES_DIR = PROJECT_ROOT / "data" / "policy_macro_manual_samples"

FIRST_BATCH_SOURCES = {
    "gov_policy_documents": "gov_policy_library",
    "ndrc": "ndrc_policy",
    "mof": "mof_policy_fiscal",
    "pbc": "pbc_policy_statistics",
    "stats_gov": "stats_gov_data",
    "stats_data": "national_data_stats",
}

POLICY_DOMAINS = {
    "macro_policy",
    "fiscal_policy",
    "monetary_policy",
    "industrial_policy",
    "capital_market_policy",
    "consumption_policy",
    "real_estate_policy",
    "foreign_trade_policy",
    "employment_policy",
    "technology_policy",
    "green_energy_policy",
    "data_ai_policy",
}

INDUSTRY_TAGS = {
    "broad_market",
    "consumer",
    "real_estate",
    "banking",
    "securities",
    "insurance",
    "semiconductor",
    "ai_computing",
    "new_energy",
    "automobile",
    "pharmaceutical",
    "defense",
    "infrastructure",
    "foreign_trade",
    "manufacturing",
    "agriculture",
    "digital_economy",
    "green_energy",
}

DOCUMENT_TYPES = {
    "policy_document",
    "notice",
    "announcement",
    "statistics_release",
    "press_release",
    "interpretation",
    "other",
}

LICENSE_STATUSES = {"checked", "unknown", "restricted", "blocked"}
RISK_LEVELS = {"low", "medium", "high", "blocked"}

REQUIRED_FIELDS = [
    "source_id",
    "source_name",
    "document_id",
    "title",
    "publish_time",
    "publisher",
    "document_type",
    "topic_tags",
    "policy_domain",
    "industry_tags",
    "summary",
    "content_excerpt",
    "content_length",
    "source_url",
    "license_or_terms_status",
    "risk_level",
    "allowed_use",
    "citation_id",
]


@dataclass
class SampleRecord:
    file: str
    line: int
    data: dict[str, Any]


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    separator = ";" if ";" in text else ","
    return [item.strip() for item in text.split(separator) if item.strip()]


def _add_issue(
    issues: list[dict[str, Any]],
    record: SampleRecord,
    field: str,
    message: str,
    severity: str = "error",
) -> None:
    issues.append(
        {
            "severity": severity,
            "file": record.file,
            "line": record.line,
            "field": field,
            "message": message,
        }
    )


def _load_jsonl(path: Path, include_templates: bool) -> tuple[list[SampleRecord], int]:
    records: list[SampleRecord] = []
    skipped = 0
    if not path.exists():
        return records, skipped
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if data.get("_template") and not include_templates:
                skipped += 1
                continue
            records.append(SampleRecord(str(path), line_number, data))
    return records, skipped


def _load_csv(path: Path, include_templates: bool) -> tuple[list[SampleRecord], int]:
    records: list[SampleRecord] = []
    skipped = 0
    if not path.exists():
        return records, skipped
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            if row.get("_template") and not include_templates:
                skipped += 1
                continue
            records.append(SampleRecord(str(path), row_number, dict(row)))
    return records, skipped


def load_records(samples_dir: Path, include_templates: bool = False) -> tuple[list[SampleRecord], int, list[str]]:
    records: list[SampleRecord] = []
    skipped_templates = 0
    files_read: list[str] = []

    for path in sorted(samples_dir.glob("*.jsonl")):
        loaded, skipped = _load_jsonl(path, include_templates)
        records.extend(loaded)
        skipped_templates += skipped
        files_read.append(str(path))

    for path in sorted(samples_dir.glob("*.csv")):
        loaded, skipped = _load_csv(path, include_templates)
        records.extend(loaded)
        skipped_templates += skipped
        files_read.append(str(path))

    return records, skipped_templates, files_read


def validate_record(record: SampleRecord) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    data = record.data

    present_required = 0
    for field in REQUIRED_FIELDS:
        if _is_blank(data.get(field)):
            _add_issue(errors, record, field, "required field is missing or empty")
        else:
            present_required += 1

    source_id = str(data.get("source_id", "")).strip()
    if source_id and source_id not in FIRST_BATCH_SOURCES:
        _add_issue(errors, record, "source_id", f"source_id is not in first-batch whitelist: {source_id}")

    document_type = str(data.get("document_type", "")).strip()
    if document_type and document_type not in DOCUMENT_TYPES:
        _add_issue(errors, record, "document_type", f"unsupported document_type: {document_type}")

    topic_tags = _parse_list(data.get("topic_tags"))
    for tag in topic_tags:
        if tag not in POLICY_DOMAINS:
            _add_issue(errors, record, "topic_tags", f"unsupported topic tag: {tag}")

    policy_domain = str(data.get("policy_domain", "")).strip()
    if policy_domain and policy_domain not in POLICY_DOMAINS:
        _add_issue(errors, record, "policy_domain", f"unsupported policy_domain: {policy_domain}")

    industry_tags = _parse_list(data.get("industry_tags"))
    for tag in industry_tags:
        if tag not in INDUSTRY_TAGS:
            _add_issue(errors, record, "industry_tags", f"unsupported industry tag: {tag}")

    source_url = str(data.get("source_url", "")).strip()
    if source_url:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            _add_issue(errors, record, "source_url", "source_url must be a non-empty http(s) URL")

    license_status = str(data.get("license_or_terms_status", "")).strip()
    if license_status and license_status not in LICENSE_STATUSES:
        _add_issue(errors, record, "license_or_terms_status", f"unsupported license_or_terms_status: {license_status}")

    risk_level = str(data.get("risk_level", "")).strip()
    if risk_level and risk_level not in RISK_LEVELS:
        _add_issue(errors, record, "risk_level", f"unsupported risk_level: {risk_level}")
    if risk_level == "blocked":
        _add_issue(errors, record, "risk_level", "blocked sources are not allowed in the manual sample pack")

    allowed_use = _parse_list(data.get("allowed_use"))
    if not allowed_use:
        _add_issue(errors, record, "allowed_use", "allowed_use must be non-empty")

    document_id = str(data.get("document_id", "")).strip()
    citation_id = str(data.get("citation_id", "")).strip()
    if source_id and document_id and citation_id:
        expected_citation = f"policy:{source_id}:{document_id}"
        if citation_id != expected_citation:
            _add_issue(
                errors,
                record,
                "citation_id",
                f"citation_id should be {expected_citation}",
            )

    content_excerpt = str(data.get("content_excerpt", "") or "")
    summary = str(data.get("summary", "") or "")
    content_length_raw = data.get("content_length")
    try:
        content_length = int(content_length_raw)
    except (TypeError, ValueError):
        content_length = None
        if not _is_blank(content_length_raw):
            _add_issue(errors, record, "content_length", "content_length must be an integer")

    if content_length is not None:
        expected_length = len(content_excerpt) if content_excerpt else len(summary)
        tolerance = max(20, int(expected_length * 0.2))
        if expected_length > 0 and abs(content_length - expected_length) > tolerance:
            _add_issue(
                warnings,
                record,
                "content_length",
                f"content_length differs from excerpt/summary length by more than tolerance: value={content_length}, expected_around={expected_length}",
                severity="warning",
            )

    return errors, warnings, {
        "present_required": present_required,
        "required_total": len(REQUIRED_FIELDS),
        "source_id": source_id,
        "policy_domain": policy_domain,
        "industry_tags": industry_tags,
        "source_url_present": bool(source_url),
        "policy_domain_present": bool(policy_domain),
        "industry_tags_present": bool(industry_tags),
    }


def validate_samples(samples_dir: Path, include_templates: bool = False) -> dict[str, Any]:
    records, skipped_templates, files_read = load_records(samples_dir, include_templates)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    source_distribution: Counter[str] = Counter()
    policy_domain_distribution: Counter[str] = Counter()
    industry_tag_distribution: Counter[str] = Counter()

    required_present = 0
    required_total = 0
    source_url_present = 0
    policy_domain_present = 0
    industry_tags_present = 0

    for record in records:
        record_errors, record_warnings, stats = validate_record(record)
        errors.extend(record_errors)
        warnings.extend(record_warnings)
        required_present += stats["present_required"]
        required_total += stats["required_total"]

        if stats["source_id"]:
            source_distribution[stats["source_id"]] += 1
        if stats["policy_domain"]:
            policy_domain_distribution[stats["policy_domain"]] += 1
        for tag in stats["industry_tags"]:
            industry_tag_distribution[tag] += 1
        if stats["source_url_present"]:
            source_url_present += 1
        if stats["policy_domain_present"]:
            policy_domain_present += 1
        if stats["industry_tags_present"]:
            industry_tags_present += 1

    sample_count = len(records)
    completeness = (required_present / required_total) if required_total else 0.0
    source_url_rate = (source_url_present / sample_count) if sample_count else 0.0
    policy_domain_rate = (policy_domain_present / sample_count) if sample_count else 0.0
    industry_tags_rate = (industry_tags_present / sample_count) if sample_count else 0.0

    shadow_gate = {
        "sample_count_at_least_30": sample_count >= 30,
        "at_least_4_sources": len(source_distribution) >= 4,
        "required_field_completeness_at_least_95pct": completeness >= 0.95,
        "source_url_completeness_at_least_95pct": source_url_rate >= 0.95,
        "policy_domain_rate_at_least_90pct": policy_domain_rate >= 0.90,
        "industry_tags_rate_at_least_70pct": industry_tags_rate >= 0.70,
        "no_errors": len(errors) == 0,
    }

    return {
        "validator": "scripts/validate_policy_macro_samples.py",
        "samples_dir": str(samples_dir),
        "network_access": "not_used",
        "files_read": files_read,
        "skipped_templates": skipped_templates,
        "sample_count": sample_count,
        "field_completeness": {
            "required_present": required_present,
            "required_total": required_total,
            "rate": round(completeness, 4),
        },
        "source_url_completeness": {
            "present": source_url_present,
            "total": sample_count,
            "rate": round(source_url_rate, 4),
        },
        "policy_domain_determinable_rate": {
            "present": policy_domain_present,
            "total": sample_count,
            "rate": round(policy_domain_rate, 4),
        },
        "industry_tags_determinable_rate": {
            "present": industry_tags_present,
            "total": sample_count,
            "rate": round(industry_tags_rate, 4),
        },
        "source_distribution": dict(sorted(source_distribution.items())),
        "policy_domain_distribution": dict(sorted(policy_domain_distribution.items())),
        "industry_tag_distribution": dict(sorted(industry_tag_distribution.items())),
        "errors": errors,
        "warnings": warnings,
        "shadow_entry_gate": shadow_gate,
        "shadow_entry_ready": all(shadow_gate.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local policy_macro manual sample files.")
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=DEFAULT_SAMPLES_DIR,
        help="Directory containing policy_macro manual sample files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report output path.",
    )
    parser.add_argument(
        "--include-templates",
        action="store_true",
        help="Validate rows marked as _template instead of skipping them.",
    )
    args = parser.parse_args()

    report = validate_samples(args.samples_dir, include_templates=args.include_templates)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
