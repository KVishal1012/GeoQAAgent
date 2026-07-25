alter table public.geoqa_runs
  add column if not exists package_status text not null default 'not_requested'
    check (package_status in ('not_requested', 'queued', 'building', 'ready', 'failed')),
  add column if not exists package_claimed_at timestamptz,
  add column if not exists package_claimed_by text,
  add column if not exists package_last_heartbeat_at timestamptz,
  add column if not exists package_attempt_count integer not null default 0,
  add column if not exists package_max_attempts integer not null default 3,
  add column if not exists package_requested_at timestamptz,
  add column if not exists package_completed_at timestamptz,
  add column if not exists package_error text,
  add column if not exists package_error_type text;

create index if not exists geoqa_runs_package_claimable_idx
  on public.geoqa_runs (package_status, package_requested_at, package_last_heartbeat_at);

create or replace function public.claim_geoqa_run(
  p_worker_id text,
  p_stale_after_seconds integer,
  p_max_attempts integer
)
returns setof public.geoqa_runs
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  with candidate as (
    select candidate_run.run_id
    from public.geoqa_runs as candidate_run
    where candidate_run.attempt_count < coalesce(candidate_run.max_attempts, p_max_attempts)
      and (
        candidate_run.status = 'queued'
        or (
          candidate_run.status = 'running'
          and coalesce(
            candidate_run.last_heartbeat_at,
            candidate_run.claimed_at,
            candidate_run.updated_at
          ) < now() - make_interval(secs => greatest(p_stale_after_seconds, 1))
        )
      )
    order by candidate_run.submitted_at
    for update skip locked
    limit 1
  )
  update public.geoqa_runs as claimed_run
  set
    status = 'running',
    claimed_at = now(),
    claimed_by = p_worker_id,
    last_heartbeat_at = now(),
    attempt_count = claimed_run.attempt_count + 1,
    max_attempts = coalesce(claimed_run.max_attempts, p_max_attempts),
    error = null,
    error_type = null,
    updated_at = now()
  from candidate
  where claimed_run.run_id = candidate.run_id
  returning claimed_run.*;
end;
$$;

create or replace function public.claim_geoqa_package(
  p_worker_id text,
  p_stale_after_seconds integer,
  p_max_attempts integer
)
returns setof public.geoqa_runs
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  with candidate as (
    select candidate_run.run_id
    from public.geoqa_runs as candidate_run
    where candidate_run.status = 'completed'
      and candidate_run.review_status ->> 'status' = 'approved'
      and candidate_run.package_attempt_count < coalesce(candidate_run.package_max_attempts, p_max_attempts)
      and (
        candidate_run.package_status = 'queued'
        or (
          candidate_run.package_status = 'building'
          and coalesce(
            candidate_run.package_last_heartbeat_at,
            candidate_run.package_claimed_at,
            candidate_run.updated_at
          ) < now() - make_interval(secs => greatest(p_stale_after_seconds, 1))
        )
      )
    order by coalesce(candidate_run.package_requested_at, candidate_run.updated_at)
    for update skip locked
    limit 1
  )
  update public.geoqa_runs as claimed_run
  set
    package_status = 'building',
    package_claimed_at = now(),
    package_claimed_by = p_worker_id,
    package_last_heartbeat_at = now(),
    package_attempt_count = claimed_run.package_attempt_count + 1,
    package_max_attempts = coalesce(claimed_run.package_max_attempts, p_max_attempts),
    package_error = null,
    package_error_type = null,
    updated_at = now()
  from candidate
  where claimed_run.run_id = candidate.run_id
  returning claimed_run.*;
end;
$$;

revoke all on function public.claim_geoqa_run(text, integer, integer) from public, anon, authenticated;
revoke all on function public.claim_geoqa_package(text, integer, integer) from public, anon, authenticated;
grant execute on function public.claim_geoqa_run(text, integer, integer) to service_role;
grant execute on function public.claim_geoqa_package(text, integer, integer) to service_role;
