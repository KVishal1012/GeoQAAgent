from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v1_mvp_docs_are_present_and_linked():
    required_docs = [
        REPO_ROOT / "docs" / "v1_release_notes.md",
        REPO_ROOT / "docs" / "v1_deployment.md",
        REPO_ROOT / "docs" / "v1_case_study_centreline.md",
        REPO_ROOT / "docs" / "v1_glossary.md",
    ]
    for path in required_docs:
        assert path.exists(), f"missing V1 document: {path.name}"
        assert "GeoQA" in path.read_text(encoding="utf-8")

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## V1 Product Complete" in readme
    assert "docs/v1_release_notes.md" in readme
    assert "docs/v1_deployment.md" in readme
    assert "docs/v1_case_study_centreline.md" in readme
    assert "docs/v1_glossary.md" in readme


def test_v1_demo_artifact_package_is_complete():
    demo_output = REPO_ROOT / "demo" / "output"
    required_artifacts = [
        "qa_report.md",
        "issues.csv",
        "summary.json",
        "run_record.json",
        "agent_report_draft.md",
        "agent_report.md",
        "agent_report.json",
        "agent_session.json",
        "agent_trace.json",
        "report_consistency.json",
        "hallucination_check.json",
        "review_status.json",
        "review_history.jsonl",
        "static_v4_report.md",
    ]
    for name in required_artifacts:
        assert (demo_output / name).exists(), f"missing V1 demo artifact: {name}"
