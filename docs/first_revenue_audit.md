# GeoQA Data Readiness Audit

## Offer

GeoQA Data Readiness Audit is the first revenue version of GeoQA Agent.

It is a productized per-dataset QA package for GIS and infrastructure teams that need to know whether a geospatial dataset is ready for database loading, dashboarding, migration, spatial joins, routing review, or downstream handoff.

## Buyer Promise

Before you load, join, migrate, or hand off geospatial data, GeoQA tells you what will break and gives you evidence-backed artifacts to fix or approve it.

## Pricing Starting Point

- Starter audit: $249 per dataset
- Project audit: $1,500-$5,000 for 5-20 datasets
- Pilot audit: $3,000-$7,500 for a 2-4 week readiness pilot

## Included Deliverables

- Customer-facing audit report: `customer_report.md`
- Deterministic QA report: `qa_report.md`
- Issue spreadsheet: `issues.csv`
- Run summary: `summary.json`
- Run record: `run_record.json`
- Geometry profile: `geometry_profile.json`
- Customer intake: `customer_intake.json`
- Optional fix plan and handoff bundle

## Intake Fields

Collect these before running a paid audit:

- customer or organization name
- business-facing dataset name
- intended downstream use
- required columns
- target CRS/SRID, if any
- customer notes or decision context

## Copy-Paste Audit Command

```bash
python app.py demo/input/centreline_intersections_sample.zip   --output-dir demo/customer_package   --customer-name "Demo City GIS Team"   --customer-dataset-name "Centreline Intersections Sample"   --intended-use sql_load   --required-column OBJECTID   --customer-notes "Assess readiness before SQL/database loading and downstream reporting."
```

## Safe Language Rule

The customer report should use cautious workflow guidance. It may say `needs review before SQL/database loading`, but it should not claim a dataset is unsuitable unless deterministic evidence proves that conclusion.

## Sales Workflow

1. Customer uploads or sends one `.geojson`, `.gpkg`, or zipped shapefile.
2. GeoQA runs deterministic QA and writes the audit package.
3. Analyst reviews the findings and customer report.
4. Deliver the package within 24-48 hours.
5. Offer a follow-up fix-plan review, multi-dataset audit, recurring QA, or internal deployment.
