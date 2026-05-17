from geoqa.reliability.hallucination_monitor import monitor_report_grounding


def test_hallucination_monitor_blocks_unsupported_claims():
    summary = {"dataset": {"feature_count": 50, "crs": "EPSG:4326"}, "readiness": {"band": "ready", "score": 100}}
    issues = []
    run_record = {"enabled_checks": ["crs_checks"], "issue_counts": {"low": 0, "medium": 0, "high": 0}}

    result = monitor_report_grounding("The dataset contains 999 features.", summary, issues, run_record)

    assert not result.passed
    assert any("999" in error for error in result.blocking_errors)


def test_hallucination_monitor_allows_cautious_conditional_language():
    summary = {"dataset": {"feature_count": 50, "crs": "EPSG:4326"}, "readiness": {"band": "needs_review", "score": 87}}
    issues = [{"issue_code": "DUPLICATE_GEOMETRY", "check_name": "duplicate_geometry", "severity": "medium"}]
    run_record = {
        "enabled_checks": ["geometry_checks"],
        "issue_counts": {"low": 0, "medium": 1, "high": 0},
        "readiness_band": "needs_review",
    }
    report = (
        "The dataset is classified as `needs_review`. "
        "If this dataset is intended for routing or network analysis, the DUPLICATE_GEOMETRY finding should be reviewed before use."
    )

    result = monitor_report_grounding(report, summary, issues, run_record)

    assert result.passed
    assert result.blocking_errors == []


def test_hallucination_monitor_blocks_unsupported_workflow_claim():
    summary = {"dataset": {"feature_count": 50, "crs": "EPSG:4326"}, "readiness": {"band": "needs_review", "score": 87}}
    issues = [{"issue_code": "DUPLICATE_GEOMETRY", "check_name": "duplicate_geometry", "severity": "medium"}]
    run_record = {
        "enabled_checks": ["geometry_checks"],
        "issue_counts": {"low": 0, "medium": 1, "high": 0},
        "readiness_band": "needs_review",
    }

    result = monitor_report_grounding(
        "The dataset is safe for routing and ready for network analysis.",
        summary,
        issues,
        run_record,
    )

    assert not result.passed
    assert any("routing safety" in error or "network analysis readiness" in error for error in result.blocking_errors)
