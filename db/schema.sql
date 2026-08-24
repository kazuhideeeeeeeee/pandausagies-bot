create table if not exists job_runs (
  id bigint generated always as identity primary key,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  mode text not null check (mode in ('dry_run', 'send')),
  status text not null check (status in ('running', 'succeeded', 'failed')),
  error text
);

create table if not exists posts (
  id bigint generated always as identity primary key,
  idempotency_key text not null unique,
  scheduled_at timestamptz not null,
  category text not null,
  body text not null,
  should_post boolean not null,
  decision_reason text not null,
  media_path text,
  song_id text,
  url text,
  x_post_id text unique,
  posted_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists media_usage (
  id bigint generated always as identity primary key,
  post_id bigint not null references posts(id),
  media_path text not null,
  used_at timestamptz not null default now()
);

create table if not exists song_usage (
  id bigint generated always as identity primary key,
  post_id bigint not null references posts(id),
  song_id text not null,
  used_at timestamptz not null default now()
);

create table if not exists story_events (
  id bigint generated always as identity primary key,
  event_key text not null unique,
  summary text not null,
  status text not null check (status in ('open', 'closed', 'forgotten')),
  started_at timestamptz not null default now(),
  next_after timestamptz,
  closed_at timestamptz
);

create table if not exists contacts (
  x_user_id text primary key,
  display_name text,
  username text,
  opted_out boolean not null default false,
  last_contact_at timestamptz
);

create table if not exists conversations (
  id bigint generated always as identity primary key,
  x_post_id text not null unique,
  x_user_id text not null references contacts(x_user_id),
  direction text not null check (direction in ('inbound', 'outbound')),
  body text not null,
  received_at timestamptz not null,
  raw_payload jsonb
);

create table if not exists reply_candidates (
  id bigint generated always as identity primary key,
  conversation_id bigint not null references conversations(id),
  body text not null,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'sent')),
  approved_at timestamptz,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

-- Phase 3 target schema. These definitions are migration-ready only; no Supabase project is created here.
create table if not exists weeks (
  id text primary key,
  week_number integer not null unique,
  starts_on date not null,
  body text not null,
  song_id text,
  media_id text,
  status text not null check (status in ('draft', 'published', 'simulated')),
  finalized_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists post_decisions (
  id bigint generated always as identity primary key,
  decided_at timestamptz not null,
  action text not null check (action in ('post', 'skip')),
  category text,
  motif text,
  event_id text,
  song_id text,
  media_id text,
  include_url boolean not null default false,
  reason text not null,
  snapshot jsonb not null
);

create table if not exists motif_usage (
  id bigint generated always as identity primary key,
  motif text not null,
  used_at timestamptz not null,
  post_id bigint references posts(id)
);

create table if not exists life_events (
  id text primary key,
  type text not null,
  started_on date not null,
  status text not null check (status in ('open', 'closed')),
  summary text not null,
  motif text not null,
  related_posts jsonb not null default '[]'::jsonb,
  earliest_next_ref date,
  reference_count integer not null default 1,
  closed_at timestamptz
);

create table if not exists metrics (
  id bigint generated always as identity primary key,
  observed_on date not null,
  source text not null,
  values jsonb not null
);

create table if not exists settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists errors (
  id bigint generated always as identity primary key,
  occurred_at timestamptz not null default now(),
  component text not null,
  message text not null,
  context jsonb
);
