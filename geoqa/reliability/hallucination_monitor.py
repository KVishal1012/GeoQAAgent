from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from geoqa.reliability.report_consistency import check_report_consistency


@dataclass(slots=True)
class HallucinationCheckResult:
    passed: bool
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_claims: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def monitor_report_grounding(
    report_text: str,
    summary: dict[str, Any],
    issues: list[dict[str, Any]],
    run_record: dict[str, Any],
    playbooks: list[dict[str, Any]] | None = None,
) -> HallucinationCheckResult:
    consistency = check_report_consistency(report_text, summary, issues, run_record)
    warnings = list(consistency.warnings)
    checked_claims = list(consistency.checked_claims)

    evidence_terms = _build_evidence_terms(summary, issues, run_record, playbooks or [])
    for sentence in _split_sentences(report_text):
        if not sentence.strip():
            continue
        grounded_terms = sorted(term for term in evidence_terms if term and term.lower() in sentence.lower())
        checked_claims.append({"type": "sentence_grounding", "sentence": sentence, "grounded_terms": grounded_terms[:8]})
        if _looks_like_claim(sentence) and not grounded_terms:
            warnings.append(f"Sentence has no obvious evidence term: {sentence}")

    return HallucinationCheckResult(
        passed=consistency.passed,
        blocking_errors=list(consistency.blocking_errors),
        warnings=warnings,
        checked_claims=checked_claims,
    )


def _build_evidence_terms(
    summary: dict[str, Any],
    issues: list[dict[str, Any]],
    run_record: dict[str, Any],
    playbooks: list[dict[str, Any]],
) -> set[str]:
    terms = {
        str(summary.get("dataset", {}).get("filename", "")),
        str(summary.get("dataset", {}).get("crs", "")),
        str(summary.get("readiness", {}).get("band", "")),
        str(summary.get("readiness", {}).get("score", "")),
        str(run_record.get("filename", "")),
        str(run_record.get("crs", "")),
        str(run_record.get("readiness_band", "")),
        str(run_record.get("readiness_score", "")),
    }
    terms.update(str(value) for value in summary.get("dataset", {}).get("geometry_types", []))
    terms.update(str(value) for value in run_record.get("geometry_types", []))
    terms.update(str(value) for value in run_record.get("enabled_checks", []))
    for issue in issues:
        terms.update(str(issue.get(key, "")) for key in ("issue_code", "check_name", "severity", "message", "suggested_fix"))
    for playbook in playbooks:
        terms.add(str(playbook.get("title", "")))
        terms.add(str(playbook.get("source", "")))
    return {term for term in terms if term and term != "None"}


def _split_sentences(report_text: str) -> list[str]:
    compact = " ".join(line.strip() for line in report_text.splitlines() if line.strip())
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", compact) if sentence.strip()]


def _looks_like_claim(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(
        marker in lowered
        for marker in (
            "dataset",
            "feature",
            "geometry",
            "crs",
            "readiness",
            "issue",
            "finding",
            "severity",
            "sql server",
            "routing",
            "network analysis",
        )
    )

