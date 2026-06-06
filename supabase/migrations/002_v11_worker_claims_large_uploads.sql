alter table public.geoqa_runs
  add column if not exists claimed_at timestamptz,
  add column if not exists claimed_by text,
  add column if not exists last_heartbeat_at timestamptz,
  add column if not exists attempt_count integer not null default 0,
  add column if not exists max_attempts integer not null default 3,
  add column if not exists size_bytes bigint,
  add column if not exists content_type text,
  add column if not exists upload_completed_at timestamptz,
  add column if not exists error_type text;

create index if not exists geoqa_runs_claimable_idx
  on public.geoqa_runs (status, submitted_at, last_heartbeat_at);

create index if not exists geoqa_runs_claimed_by_idx
  on public.geoqa_runs (claimed_by, last_heartbeat_at);
