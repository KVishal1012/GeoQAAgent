from __future__ import annotations

from geoqa.models import Issue

SEVERITY_WEIGHTS = {"low": 2, "medium": 7, "high": 15}


def calculate_readiness_score(issues: list[Issue]) -> dict[str, int | str | dict[str, int]]:
    penalties = {"low": 0, "medium": 0, "high": 0}
    for issue in issues:
        if issue.severity in penalties:
            penalties[issue.severity] += 1

    penalty_score = sum(count * SEVERITY_WEIGHTS[level] for level, count in penalties.items())
    score = max(0, 100 - penalty_score)
    if score >= 90:
        band = "ready"
    elif score >= 70:
        band = "needs_review"
    else:
        band = "not_ready"
    return {
        "score": score,
        "band": band,
        "penalties": penalties,
    }
