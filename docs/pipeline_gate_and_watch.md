# GeoQA Pipeline Gate And Watch Mode

GeoQA can now act as a data-quality control point before ingestion, migration, dashboarding, or client ETL.

## Pipeline Gate Mode

Use `--fail-below` to make GeoQA return a non-zero exit code when the readiness score is below the configured threshold.

```bash
python app.py path/to/dataset.zip --output-dir outputs/gates --fail-below 85
```

Behavior:

- GeoQA still writes the full QA package first.
- The command exits with `0` when the readiness score is greater than or equal to the threshold.
- The command exits with `2` when the readiness score is below the threshold.
- The JSON output includes a `pipeline_gate` object with the threshold, score, pass/fail state, exit code, and message.

This makes GeoQA suitable in front of GeoSentinel ingestion, GitHub Actions, or client ETL jobs.

## GitHub Action

The repository includes `.github/workflows/geoqa-gate.yml`.

Manual run inputs:

- `dataset_path`: repository-relative path to a `.geojson`, `.gpkg`, or zipped shapefile
- `fail_below`: minimum readiness score required to pass, default `85`

The action uploads the generated QA artifacts even when the gate fails, so reviewers can inspect the evidence.

## Scheduled Watch Mode

Use `--watch-dir` to scan a folder for new geospatial drops.

```bash
python app.py \
  --watch-dir /data/incoming \
  --output-dir outputs/watch \
  --watch-state-file outputs/watch/watch_state.json \
  --watch-once \
  --fail-below 85
```

For continuous polling:

```bash
python app.py \
  --watch-dir /data/incoming \
  --output-dir outputs/watch \
  --watch-interval-seconds 60 \
  --watch-min-age-seconds 10 \
  --fail-below 85
```

Supported drop types:

- `.geojson`
- `.gpkg`
- `.zip` zipped shapefile

## Slack Alerts

Add an incoming webhook URL to alert when a watched dataset fails the gate.

```bash
python app.py \
  --watch-dir /data/incoming \
  --output-dir outputs/watch \
  --fail-below 85 \
  --slack-webhook-url "$SLACK_WEBHOOK_URL"
```

Slack alerts are only sent for watcher runs where `--fail-below` is configured and the readiness score is below threshold.

## Operational Notes

- Watch state is stored in `watch_state.json` by default under the output root.
- Files are keyed by path, size, and modified time so unchanged drops are not reprocessed.
- Use `--watch-min-age-seconds` when files are copied slowly into the watched folder.
- Bucket watching is intentionally not provider-specific yet; mount or sync buckets to a local folder for this version.
