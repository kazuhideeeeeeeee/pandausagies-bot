-- Design only. Do not apply until a reviewed production Supabase project exists.
alter table public_state_snapshots enable row level security;
alter table public_songs enable row level security;
alter table public_media enable row level security;
alter table job_runs enable row level security;
alter table post_decisions enable row level security;
alter table posts enable row level security;
alter table contacts enable row level security;
alter table conversations enable row level security;
alter table errors enable row level security;
alter table settings enable row level security;

create policy "anon reads public snapshots" on public_state_snapshots for select to anon using (true);
create policy "anon reads public songs" on public_songs for select to anon using (active = true);
create policy "anon reads public media" on public_media for select to anon using (active = true);

-- No anon INSERT/UPDATE/DELETE policies. Private tables intentionally have no anon policies.
revoke insert, update, delete on public_state_snapshots, public_songs, public_media from anon;
revoke all on job_runs, post_decisions, posts, contacts, conversations, errors, settings from anon;
