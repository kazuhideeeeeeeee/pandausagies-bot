-- pandausagies V2.x Phase A image automation migration.
-- Staging only. Contains no credentials and never enables X writes.

do $$
begin
  if not exists (
    select 1 from public.staging_metadata
    where singleton and environment = 'staging'
  ) then
    raise exception 'image autogen migration is staging-only';
  end if;
end
$$;

create table if not exists public.media_jobs (
  id text primary key,
  run_id text not null unique,
  environment text not null default 'staging' check (environment = 'staging'),
  provider text not null check (provider in ('fake', 'openai')),
  prompt_version text not null,
  status text not null check (status in ('planned', 'generating', 'approved', 'rejected', 'failed')),
  plan jsonb not null,
  prompt text not null,
  plan_fingerprint text not null unique,
  generated_media_id text,
  fallback_action text check (fallback_action in ('text_only', 'skip')),
  error_category text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.generated_media (
  id text primary key,
  job_id text not null unique references public.media_jobs(id) on delete cascade,
  run_id text not null unique,
  environment text not null default 'staging' check (environment = 'staging'),
  provider text not null check (provider in ('fake', 'openai')),
  prompt_version text not null,
  scene text not null,
  outfit text not null,
  motif text not null,
  caption text not null,
  storage_bucket text not null,
  storage_path text not null unique,
  mime_type text not null check (mime_type in ('image/png', 'image/jpeg', 'image/webp')),
  width integer not null check (width > 0),
  height integer not null check (height > 0),
  moderation_status text not null check (moderation_status in ('approved', 'rejected', 'needs_human')),
  selected_for_post boolean not null default false,
  fingerprint text not null unique,
  content_sha256 text not null,
  created_at timestamptz not null default now()
);

create index if not exists media_jobs_created_at_idx on public.media_jobs(created_at desc);
create index if not exists media_jobs_status_idx on public.media_jobs(status, created_at desc);
create index if not exists generated_media_created_at_idx on public.generated_media(created_at desc);
create index if not exists generated_media_motif_idx on public.generated_media(motif, created_at desc);

alter table public.media_jobs enable row level security;
alter table public.generated_media enable row level security;

-- Generated candidates and prompts are private backend state.
revoke all on public.media_jobs, public.generated_media from anon, authenticated;
grant all on public.media_jobs, public.generated_media to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'generated-media',
  'generated-media',
  false,
  6291456,
  array['image/png', 'image/jpeg', 'image/webp']
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

update public.staging_metadata
set schema_version = greatest(schema_version, 2), updated_at = now()
where singleton and environment = 'staging';

-- Keep the explicit staging reset complete without exposing it publicly.
create or replace function public.reset_staging_state(p_confirmation text)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if p_confirmation <> 'RESET pandausagies-v2-staging' then
    raise exception 'staging reset confirmation mismatch';
  end if;
  if not exists(select 1 from staging_metadata where singleton and environment = 'staging') then
    raise exception 'not a staging database';
  end if;
  delete from storage.objects where bucket_id = 'generated-media';
  delete from generated_media;
  delete from media_jobs;
  delete from reply_candidates;
  delete from mentions;
  delete from conversations;
  delete from contacts;
  delete from x_read_cursors;
  delete from x_account_identities;
  delete from public_state_snapshots;
  delete from usage_history;
  delete from delivery_ledger;
  delete from post_decisions;
  delete from weeks;
  delete from errors;
  delete from life_events;
  delete from job_runs;
  delete from job_leases;
  delete from settings;
  update memory_state set version = 0, value = '{}'::jsonb, updated_at = now() where singleton;
  return true;
end
$$;

revoke all on function public.reset_staging_state(text) from public, anon, authenticated;
grant execute on function public.reset_staging_state(text) to service_role;
