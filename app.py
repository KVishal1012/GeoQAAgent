from __future__ import annotations

import argparse
import json
import sys

from geoqa.ingestion.validators import ValidationError
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
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
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
    except ValidationError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
