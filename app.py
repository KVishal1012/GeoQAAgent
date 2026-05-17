from __future__ import annotations

import argparse
import json
import sys

from geoqa.ingestion.validators import ValidationError
from geoqa.llm.gateway import LLMGatewayError, OpenAILLMGateway, StaticFileLLMGateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts
from geoqa.review.human_review import ReviewError
from geoqa.runner import run_geoqa


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GeoQA against a geospatial dataset.")
    parser.add_argument("input_path", help="Path to a .geojson, .gpkg, or zipped shapefile.")
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
    parser.add_argument("--reviewer-name", default=None, help="Reviewer name required for agent report approval.")
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
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.approve_agent_report and not args.agent_report:
        parser.error("--approve-agent-report requires --agent-report")
    if args.approve_agent_report and not args.reviewer_name:
        parser.error("--reviewer-name is required with --approve-agent-report")
    if args.llm_provider == "static" and args.agent_report and not args.static_report_file:
        parser.error("--static-report-file is required with --llm-provider static")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(args, parser)
    try:
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
                approve=args.approve_agent_report,
                reviewer_name=args.reviewer_name,
            )
            result.artifact_paths.update(agent_artifacts)
    except ValidationError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (LLMGatewayError, ReviewError) as exc:
        print(f"Agent report error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
