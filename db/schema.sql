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
  status text not null check (status in ('open', 'closed')),
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
