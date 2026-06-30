from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PIPELINE_GATE_EXIT_CODE = 2


@dataclass(frozen=True, slots=True)
class PipelineGateResult:
    """Result of applying a readiness-score threshold to a completed QA run."""

    threshold: int
    readiness_score: int
    passed: bool
    exit_code: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_fail_below_threshold(threshold: int | None) -> None:
    if threshold is None:
        return
    if threshold < 0 or threshold > 100:
        raise ValueError("--fail-below must be between 0 and 100")


def evaluate_pipeline_gate(readiness_score: int | None, threshold: int | None) -> PipelineGateResult | None:
    """Return a blocking gate result when a fail-below threshold is configured."""

    if threshold is None:
        return None
    validate_fail_below_threshold(threshold)
    if readiness_score is None:
        score = 0
    else:
        score = int(readiness_score)
    passed = score >= int(threshold)
    return PipelineGateResult(
        threshold=int(threshold),
        readiness_score=score,
        passed=passed,
        exit_code=0 if passed else PIPELINE_GATE_EXIT_CODE,
        message=(
            f"GeoQA readiness score {score}/100 meets the configured threshold {threshold}/100."
            if passed
            else f"GeoQA readiness score {score}/100 is below the configured threshold {threshold}/100."
        ),
    )
