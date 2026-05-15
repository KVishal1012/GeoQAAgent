from geoqa.reliability.report_consistency import check_report_consistency


def _evidence():
    summary = {
        "dataset": {
            "filename": "sample.zip",
            "feature_count": 50,
            "geometry_types": ["MultiPoint"],
            "crs": "EPSG:4326",
        },
        "readiness": {"score": 87, "band": "needs_review", "penalties": {"low": 3, "medium": 1, "high": 0}},
    }
    issues = [
        {
            "issue_code": "DUPLICATE_GEOMETRY",
            "check_name": "duplicate_geometry",
            "severity": "medium",
            "feature_id": "12",
            "message": "Feature duplicates geometry of feature 11.",
            "suggested_fix": "Deduplicate repeated spatial features.",
        }
    ]
    run_record = {
        "enabled_checks": ["crs_checks", "geometry_checks", "schema_checks"],
        "issue_counts": {"low": 3, "medium": 1, "high": 0, "total": 4},
        "readiness_band": "needs_review",
        "readiness_score": 87,
        "feature_count": 50,
        "crs": "EPSG:4326",
        "geometry_types": ["MultiPoint"],
    }
    return summary, issues, run_record


def test_report_consistency_allows_supported_claims():
    summary, issues, run_record = _evidence()
    report = (
        "GeoQA inspected sample.zip, containing 50 features with MultiPoint geometry in EPSG:4326. "
        "The dataset is classified as `needs_review` with a readiness score of 87/100. "
        "The DUPLICATE_GEOMETRY finding is medium-severity."
    )

    result = check_report_consistency(report, summary, issues, run_record)

    assert result.passed
    assert result.blocking_errors == []


def test_report_consistency_blocks_unsupported_number():
    summary, issues, run_record = _evidence()

    result = check_report_consistency("The dataset contains 999 features.", summary, issues, run_record)

    assert not result.passed
    assert "Unsupported numeric value in report: 999" in result.blocking_errors


def test_report_consistency_blocks_wrong_readiness_band():
    summary, issues, run_record = _evidence()

    result = check_report_consistency("The dataset is classified as `not_ready`.", summary, issues, run_record)

    assert not result.passed
    assert any("does not match" in error for error in result.blocking_errors)


def test_report_consistency_blocks_invented_severity():
    summary, issues, run_record = _evidence()

    result = check_report_consistency("The report found high-severity issues.", summary, issues, run_record)

    assert not result.passed
    assert any("high-severity" in error for error in result.blocking_errors)


def test_report_consistency_blocks_invented_issue_code():
    summary, issues, run_record = _evidence()

    result = check_report_consistency("The report found FAKE_ISSUE.", summary, issues, run_record)

    assert not result.passed
    assert "Issue code 'FAKE_ISSUE' is not present in issues.csv." in result.blocking_errors


def test_report_consistency_blocks_check_not_run():
    summary, issues, run_record = _evidence()

    result = check_report_consistency("Review before SQL Server loading.", summary, issues, run_record)

    assert not result.passed
    assert any("sql server" in error for error in result.blocking_errors)

