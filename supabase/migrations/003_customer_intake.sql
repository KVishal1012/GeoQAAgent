alter table public.geoqa_runs
  add column if not exists customer_intake jsonb not null default '{}'::jsonb;
