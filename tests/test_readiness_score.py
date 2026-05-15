from geoqa.models import Issue
from geoqa.scoring.readiness_score import calculate_readiness_score


def test_readiness_score_returns_ready_for_clean_dataset():
    readiness = calculate_readiness_score([])

    assert readiness["score"] == 100
    assert readiness["band"] == "ready"


def test_readiness_score_penalizes_high_severity_more():
    issues = [
        Issue(issue_code="A", check_name="a", message="a", severity="low"),
        Issue(issue_code="B", check_name="b", message="b", severity="medium"),
        Issue(issue_code="C", check_name="c", message="c", severity="high"),
    ]

    readiness = calculate_readiness_score(issues)

    assert readiness["score"] == 76
    assert readiness["band"] == "needs_review"
