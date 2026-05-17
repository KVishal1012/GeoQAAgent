from __future__ import annotations

import argparse
import json
import sys

from geoqa.ingestion.validators import ValidationError
from geoqa.llm.gateway import LLMGatewayError, OpenAILLMGateway, StaticFileLLMGateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts, review_existing_agent_report
from geoqa.review.human_review import ReviewError
from geoqa.runner import run_geoqa


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GeoQA against a geospatial dataset.")
    parser.add_argument("input_path", nargs="?", help="Path to a .geojson, .gpkg, or zipped shapefile.")
    parser.add_argument("--output-dir", default="outputs", help="Directory used for QA artifacts.")
    parser.add_argument(
        "--required-column",
        action="append",
        dest="required_columns",
        default=[],
        help="Required schema column. Repeat the flag to require multiple columns.",
    )
    parser.add_argument("--target-crs", default=None, help="Optional canonical CRS for QA checks.")
    parser.add_argument(
        "--precision-grid-size",
        type=float,
        default=None,
        help="Optional coordinate snapping grid size.",
    )
    parser.add_argument(
        "--skip-sqlserver-checks",
        action="store_true",
        help="Disable SQL Server compatibility checks.",
    )
    parser.add_argument(
        "--skip-linear-reference-checks",
        action="store_true",
        help="Disable linear reference checks.",
    )
    parser.add_argument(
        "--agent-report",
        action="store_true",
        help="Generate an evidence-backed LLM draft report after deterministic QA artifacts are written.",
    )
    parser.add_argument(
        "--llm-provider",
        default="openai",
        choices=["openai", "static"],
        help="LLM provider for agent reports. Use 'static' for the no-API-key demo path.",
    )
    parser.add_argument("--llm-model", default=None, help="Optional LLM model override for agent reports.")
    parser.add_argument(
        "--approve-agent-report",
        action="store_true",
        help="Approve the generated agent report when consistency checks pass.",
    )
    parser.add_argument(
        "--reject-agent-report",
        action="store_true",
        help="Reject the generated or existing agent report draft and record reviewer metadata.",
    )
    parser.add_argument("--reviewer-name", default=None, help="Reviewer name required for agent report approval.")
    parser.add_argument(
        "--review-notes",
        default=None,
        help="Optional notes recorded with agent report approval or rejection.",
    )
    parser.add_argument(
        "--review-output-dir",
        default=None,
        help="Existing run output directory to approve or reject without regenerating artifacts.",
    )
    parser.add_argument(
        "--playbook-dir",
        default=None,
        help="Optional directory containing fix playbooks for agent report retrieval.",
    )
    parser.add_argument(
        "--static-report-file",
        default=None,
        help="Static agent report markdown used when --llm-provider static is selected.",
    )
    parser.add_argument(
        "--agent-prompt",
        default="technical_report_v1",
        choices=["technical_report_v1", "executive_summary_v1", "fix_recommendation_v1"],
        help="Prompt template used for agent report generation.",
    )
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    review_action_requested = args.approve_agent_report or args.reject_agent_report
    if args.approve_agent_report and args.reject_agent_report:
        parser.error("--approve-agent-report and --reject-agent-report cannot be used together")
    if review_action_requested and not args.reviewer_name:
        parser.error("--reviewer-name is required with review actions")
    if args.review_output_dir and args.agent_report:
        parser.error("--review-output-dir cannot be combined with --agent-report")
    if args.review_output_dir and not review_action_requested:
        parser.error("--review-output-dir requires --approve-agent-report or --reject-agent-report")
    if review_action_requested and not args.review_output_dir and not args.agent_report:
        parser.error("review actions require either --agent-report or --review-output-dir")
    if args.llm_provider == "static" and args.agent_report and not args.static_report_file:
        parser.error("--static-report-file is required with --llm-provider static")
    if not args.review_output_dir and not args.input_path:
        parser.error("input_path is required unless --review-output-dir is used")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(args, parser)
    try:
        if args.review_output_dir:
            action = "approve" if args.approve_agent_report else "reject"
            review_result = review_existing_agent_report(
                args.review_output_dir,
                action=action,
                reviewer_name=args.reviewer_name or "",
                notes=args.review_notes,
            )
            print(json.dumps(review_result, indent=2))
            return

        result = run_geoqa(
            input_path=args.input_path,
            output_root=args.output_dir,
            required_columns=args.required_columns,
            target_crs=args.target_crs,
            precision_grid_size=args.precision_grid_size,
            enable_sqlserver_checks=not args.skip_sqlserver_checks,
            enable_linear_reference_checks=not args.skip_linear_reference_checks,
        )
        if args.agent_report:
            gateway = None
            if args.llm_provider == "static":
                gateway = StaticFileLLMGateway(args.static_report_file)
            elif args.llm_provider == "openai":
                gateway = OpenAILLMGateway(default_model=args.llm_model)
            agent_artifacts = generate_agent_report_artifacts(
                result,
                gateway=gateway,
                model=args.llm_model,
                playbook_dir=args.playbook_dir,
                prompt_name=args.agent_prompt,
                approve=args.approve_agent_report,
                reviewer_name=args.reviewer_name,
                review_notes=args.review_notes,
            )
            result.artifact_paths.update(agent_artifacts)
            if args.reject_agent_report:
                review_result = review_existing_agent_report(
                    result.artifact_paths["output_dir"],
                    action="reject",
                    reviewer_name=args.reviewer_name or "",
                    notes=args.review_notes,
                )
                result.artifact_paths.update({k: v for k, v in review_result.items() if v})
    except ValidationError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (LLMGatewayError, ReviewError) as exc:
        print(f"Agent report error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
