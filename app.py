from __future__ import annotations

import argparse
import json
import sys

from geoqa.config import ConfigError, diagnose_config, load_app_config
from geoqa.ingestion.validators import ValidationError
from geoqa.llm.gateway import LLMGatewayError, StaticFileLLMGateway, build_openai_gateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts, review_existing_agent_report
from geoqa.review.human_review import ReviewError
from geoqa.runner import run_geoqa
from geoqa.workflows import HandoffBundleError, compare_run_outputs, export_handoff_bundle, generate_fix_plan_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GeoQA against a geospatial dataset.")
    parser.add_argument("input_path", nargs="?", help="Path to a .geojson, .gpkg, or zipped shapefile.")
    parser.add_argument("--output-dir", default=None, help="Directory used for QA artifacts.")
    parser.add_argument("--env-file", default=None, help="Optional .env file used to populate runtime configuration.")
    parser.add_argument(
        "--diagnose-config",
        action="store_true",
        help="Print the effective runtime configuration and exit.",
    )
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
        "--compare-run-dir",
        default=None,
        help="Base run output directory used to compare against the current or target run output directory.",
    )
    parser.add_argument(
        "--target-run-dir",
        default=None,
        help="Target run output directory used with --compare-run-dir for run comparison.",
    )
    parser.add_argument(
        "--generate-fix-plan",
        action="store_true",
        help="Generate fix plan artifacts for an existing run output directory.",
    )
    parser.add_argument(
        "--export-handoff-bundle",
        action="store_true",
        help="Export a handoff bundle for an existing run output directory.",
    )
    parser.add_argument(
        "--comparison-key",
        default=None,
        help="Optional comparison key to include when exporting a handoff bundle.",
    )
    parser.add_argument(
        "--playbook-dir",
        default=None,
        help="Optional directory containing fix playbooks for agent report retrieval and fix plans.",
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
    comparison_requested = bool(args.compare_run_dir or args.target_run_dir)
    existing_run_action_requested = args.generate_fix_plan or args.export_handoff_bundle
    if args.approve_agent_report and args.reject_agent_report:
        parser.error("--approve-agent-report and --reject-agent-report cannot be used together")
    if review_action_requested and not args.reviewer_name:
        parser.error("--reviewer-name is required with review actions")
    if args.review_output_dir and args.agent_report:
        parser.error("--review-output-dir cannot be combined with --agent-report")
    if args.review_output_dir and not (review_action_requested or existing_run_action_requested):
        parser.error(
            "--review-output-dir requires a review action, --generate-fix-plan, or --export-handoff-bundle"
        )
    if review_action_requested and not args.review_output_dir and not args.agent_report:
        parser.error("review actions require either --agent-report or --review-output-dir")
    if args.llm_provider == "static" and args.agent_report and not args.static_report_file:
        parser.error("--static-report-file is required with --llm-provider static")
    if comparison_requested and not (args.compare_run_dir and args.target_run_dir):
        parser.error("--compare-run-dir and --target-run-dir are required together")
    if existing_run_action_requested and not args.review_output_dir:
        parser.error("existing-run workflow actions require --review-output-dir")
    if args.review_output_dir and args.input_path:
        parser.error("input_path cannot be combined with --review-output-dir workflow actions")
    if comparison_requested and args.input_path:
        parser.error("input_path cannot be combined with run comparison")
    if args.comparison_key and not args.export_handoff_bundle:
        parser.error("--comparison-key is only valid with --export-handoff-bundle")
    if not args.review_output_dir and not args.input_path and not args.diagnose_config and not comparison_requested:
        parser.error("input_path is required unless --review-output-dir or run comparison is used")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = load_app_config(args.env_file)
        if args.output_dir is None:
            args.output_dir = config.output_root
        validate_args(args, parser)
        if args.diagnose_config:
            print(json.dumps(diagnose_config(config), indent=2))
            return

        if args.review_output_dir:
            workflow_result: dict[str, str | bool | None] = {}
            if args.approve_agent_report or args.reject_agent_report:
                action = "approve" if args.approve_agent_report else "reject"
                workflow_result.update(
                    review_existing_agent_report(
                        args.review_output_dir,
                        action=action,
                        reviewer_name=args.reviewer_name or "",
                        notes=args.review_notes,
                    )
                )
            if args.generate_fix_plan:
                workflow_result.update(
                    generate_fix_plan_artifacts(args.review_output_dir, playbook_dir=args.playbook_dir)
                )
            if args.export_handoff_bundle:
                workflow_result.update(
                    export_handoff_bundle(
                        args.review_output_dir,
                        comparison_key=args.comparison_key,
                    )
                )
            print(json.dumps(workflow_result, indent=2))
            return

        if args.compare_run_dir and args.target_run_dir:
            comparison_result = compare_run_outputs(args.compare_run_dir, args.target_run_dir)
            print(json.dumps(comparison_result, indent=2))
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
                if not config.agent_report_enabled:
                    raise LLMGatewayError(
                        "Agent reports are disabled by GEOQA_AGENT_REPORT_ENABLED=0.",
                        code="agent_reports_disabled",
                    )
                gateway = StaticFileLLMGateway(args.static_report_file)
            elif args.llm_provider == "openai":
                runtime_model = args.llm_model or config.llm_model
                gateway = build_openai_gateway(
                    config,
                    default_model=runtime_model,
                )
            agent_artifacts = generate_agent_report_artifacts(
                result,
                gateway=gateway,
                model=args.llm_model or config.llm_model,
                playbook_dir=args.playbook_dir,
                prompt_name=args.agent_prompt,
                approve=args.approve_agent_report,
                reviewer_name=args.reviewer_name,
                review_notes=args.review_notes,
                runtime_config=config.to_safe_dict(),
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
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (LLMGatewayError, ReviewError, HandoffBundleError) as exc:
        print(f"Agent report error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
