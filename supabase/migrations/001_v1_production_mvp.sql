create table if not exists public.geoqa_runs (
  run_id text primary key,
  status text not null check (status in ('queued', 'running', 'completed', 'failed')),
  submitted_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  filename text not null,
  upload_id text not null,
  upload_storage_path text not null,
  required_columns jsonb not null default '[]'::jsonb,
  target_crs text,
  readiness_score integer,
  readiness_band text,
  issue_counts jsonb,
  review_status jsonb,
  run_output_dir text,
  artifacts jsonb not null default '{}'::jsonb,
  error text,
  error_type text
);

create index if not exists geoqa_runs_status_submitted_idx
  on public.geoqa_runs (status, submitted_at);

create table if not exists public.geoqa_run_events (
  id bigint generated always as identity primary key,
  run_id text not null references public.geoqa_runs(run_id) on delete cascade,
  event_type text not null,
  timestamp timestamptz not null default now(),
  details jsonb not null default '{}'::jsonb
);

create index if not exists geoqa_run_events_run_timestamp_idx
  on public.geoqa_run_events (run_id, timestamp);
