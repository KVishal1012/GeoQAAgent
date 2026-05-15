from geoqa.rag.retriever import retrieve_playbooks
from geoqa.severity.taxonomy import SEVERITY_MAP


def test_retriever_covers_all_current_issue_codes():
    issues = [{"issue_code": issue_code} for issue_code in SEVERITY_MAP]

    playbooks = retrieve_playbooks(issues)
    covered_codes = {issue_code for playbook in playbooks for issue_code in playbook.issue_codes}

    assert set(SEVERITY_MAP) == covered_codes


def test_retriever_returns_duplicate_geometry_playbook():
    playbooks = retrieve_playbooks([{"issue_code": "DUPLICATE_GEOMETRY"}])

    assert len(playbooks) == 1
    assert playbooks[0].title == "Duplicate Geometry Playbook"
    assert "spatial joins" in playbooks[0].text

