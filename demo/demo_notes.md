# GeoQA V0.1.1 Demo Notes

## What this demo shows

This demo uses a 50-feature sample from a Centreline Intersections shapefile in `EPSG:4326`. The sample keeps the original shapefile-style field names and `MultiPoint` geometry so the run feels close to a real municipal data QA workflow while staying small enough for the repository.

## Run command

```bash
python app.py demo/input/centreline_intersections_sample.zip --output-dir demo/output
```

The committed files in `demo/output/` are stable reference artifacts for review. A fresh CLI run writes a timestamped run folder under `demo/output/`.

## Expected result

- Readiness band: `needs_review`
- Readiness score: `87`
- Feature count: `50`
- Geometry type: `MultiPoint`
- Main findings: duplicate point geometry and null-heavy elevation/height fields

## Why it matters

GeoQA turns geospatial data quality checks into a repeatable handoff artifact. Instead of manually opening a shapefile and writing notes, a data owner can run one command and share a report, issue CSV, summary JSON, and run record.

## 2-minute Loom script

1. Open the README and point to the flowchart: "GeoQA takes a geospatial file, validates it, normalizes it, runs deterministic QA checks, scores readiness, and writes artifacts."
2. Show `demo/input/centreline_intersections_sample.zip`: "For V0.1.1, I added a small Centreline Intersections sample so anyone can test the project immediately."
3. Run the command: `python app.py demo/input/centreline_intersections_sample.zip --output-dir demo/output`.
4. Open `demo/output/qa_report.md`: "The report gives a readiness score, issue counts, normalization notes, top findings, and suggested fixes."
5. Open `demo/output/issues.csv`: "The CSV is useful for triage because each issue has a code, severity, feature ID, message, and suggested fix."
6. Close with the value: "This makes geospatial QA easier to reproduce, easier to explain, and easier to hand off before data moves into downstream systems."

## LinkedIn/GitHub talking points

- Built a Python geospatial QA pipeline that validates GeoJSON, GeoPackage, and zipped shapefile inputs.
- Added a Centreline Intersections demo package with input data, output artifacts, screenshots, and a walkthrough script.
- Auto-detects source ID columns so findings can point back to real records.
- Produces readiness scoring, issue CSVs, JSON summaries, and Markdown reports for data handoff.

## Screenshots

- `screenshots/report_preview.png`: report summary and top findings
- `screenshots/issues_csv_preview.png`: first rows of the issue CSV
- `screenshots/terminal_run.png`: command-line demo run summary
