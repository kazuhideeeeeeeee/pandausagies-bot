-- Atomic staging-only operations. Service role only; fixed search_path.
create or replace function public.acquire_job_lease(p_name text,p_owner text,p_ttl_seconds integer default 300) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ begin if p_ttl_seconds<1 or p_ttl_seconds>3600 then raise exception 'invalid lease ttl'; end if; insert into job_leases(name,owner,expires_at,heartbeat_at) values(p_name,p_owner,now()+make_interval(secs=>p_ttl_seconds),now()) on conflict(name) do update set owner=excluded.owner,expires_at=excluded.expires_at,heartbeat_at=now() where job_leases.expires_at<=now() or job_leases.owner=excluded.owner; return found; end $$;
create or replace function public.heartbeat_job_lease(p_name text,p_owner text,p_ttl_seconds integer default 300) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ begin update job_leases set expires_at=now()+make_interval(secs=>p_ttl_seconds),heartbeat_at=now() where name=p_name and owner=p_owner and expires_at>now(); return found; end $$;
create or replace function public.release_job_lease(p_name text,p_owner text) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ begin delete from job_leases where name=p_name and owner=p_owner; return found; end $$;
create or replace function public.save_memory_cas(p_expected_version bigint,p_value jsonb) returns bigint language plpgsql security definer set search_path=public,pg_temp as $$ declare next_version bigint; begin update memory_state set value=p_value,version=version+1,updated_at=now() where singleton and version=p_expected_version returning version into next_version; if next_version is null then raise exception 'memory version conflict' using errcode='40001'; end if; return next_version; end $$;
create or replace function public.commit_run_decision(p_run_id text,p_action text,p_reason text,p_snapshot jsonb,p_expected_memory_version bigint,p_memory jsonb,p_category text default null,p_motif text default null,p_event_id text default null,p_song_id text default null,p_media_id text default null,p_include_url boolean default false) returns bigint language plpgsql security definer set search_path=public,pg_temp as $$ declare next_version bigint; begin update job_runs set status='decided',decision=p_snapshot where run_id=p_run_id and status='running'; if not found then raise exception 'run state conflict' using errcode='40001'; end if; insert into post_decisions(run_id,action,reason,snapshot,category,motif,event_id,song_id,media_id,include_url) values(p_run_id,p_action,p_reason,p_snapshot,p_category,p_motif,p_event_id,p_song_id,p_media_id,p_include_url); update memory_state set value=p_memory,version=version+1,updated_at=now() where singleton and version=p_expected_memory_version returning version into next_version; if next_version is null then raise exception 'memory version conflict' using errcode='40001'; end if; return next_version; end $$;
drop function if exists public.reset_staging_state(text);
create function public.reset_staging_state(p_confirmation text) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ begin if p_confirmation<>'RESET pandausagies-v2-staging' then raise exception 'staging reset confirmation mismatch'; end if; if not exists(select 1 from staging_metadata where singleton and environment='staging') then raise exception 'not a staging database'; end if; delete from reply_candidates; delete from mentions; delete from conversations; delete from contacts; delete from x_read_cursors; delete from x_account_identities; delete from public_state_snapshots; delete from usage_history; delete from delivery_ledger; delete from post_decisions; delete from weeks; delete from errors; delete from life_events; delete from job_runs; delete from job_leases; delete from settings; update memory_state set version=0,value='{}'::jsonb,updated_at=now() where singleton; return true; end $$;
revoke all on function public.acquire_job_lease(text,text,integer),public.heartbeat_job_lease(text,text,integer),public.release_job_lease(text,text),public.save_memory_cas(bigint,jsonb),public.commit_run_decision(text,text,text,jsonb,bigint,jsonb,text,text,text,text,text,boolean),public.reset_staging_state(text) from public,anon,authenticated;
grant execute on function public.acquire_job_lease(text,text,integer),public.heartbeat_job_lease(text,text,integer),public.release_job_lease(text,text),public.save_memory_cas(bigint,jsonb),public.commit_run_decision(text,text,text,jsonb,bigint,jsonb,text,text,text,text,text,boolean),public.reset_staging_state(text) to service_role;

create or replace function public.ingest_x_mention(p_mention jsonb,p_classification text,p_candidate_body text default null) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ declare inserted boolean; begin
  insert into contacts(x_user_id,current_username,display_name,first_seen_at,last_seen_at,interaction_count,automation_opt_out)
  values(p_mention->>'author_id',p_mention->>'username',p_mention->>'display_name',(p_mention->>'created_at')::timestamptz,(p_mention->>'created_at')::timestamptz,1,coalesce((p_mention->>'automation_opt_out')::boolean,false))
  on conflict(x_user_id) do nothing;
  insert into conversations(conversation_id,x_user_id,first_seen_at,last_seen_at) values(p_mention->>'conversation_id',p_mention->>'author_id',(p_mention->>'created_at')::timestamptz,(p_mention->>'created_at')::timestamptz) on conflict(conversation_id) do nothing;
  insert into mentions(x_post_id,author_id,username,display_name,text,created_at,conversation_id,referenced_post_id,in_reply_to_user_id,status,raw_minimal)
  values(p_mention->>'x_post_id',p_mention->>'author_id',p_mention->>'username',p_mention->>'display_name',p_mention->>'text',(p_mention->>'created_at')::timestamptz,p_mention->>'conversation_id',nullif(p_mention->>'referenced_post_id',''),nullif(p_mention->>'in_reply_to_user_id',''),case when p_classification='candidate' then 'awaiting_review' else p_classification end,coalesce(p_mention->'raw_minimal','{}'::jsonb)) on conflict(x_post_id) do nothing;
  inserted:=found;
  if inserted then
    update contacts set current_username=p_mention->>'username',display_name=p_mention->>'display_name',last_seen_at=greatest(last_seen_at,(p_mention->>'created_at')::timestamptz),interaction_count=interaction_count+case when first_seen_at=(p_mention->>'created_at')::timestamptz then 0 else 1 end,automation_opt_out=automation_opt_out or coalesce((p_mention->>'automation_opt_out')::boolean,false) where x_user_id=p_mention->>'author_id';
    update conversations set last_seen_at=greatest(last_seen_at,(p_mention->>'created_at')::timestamptz) where conversation_id=p_mention->>'conversation_id';
    insert into reply_candidates(x_post_id,body,classification,status) values(p_mention->>'x_post_id',p_candidate_body,p_classification,case when p_classification='candidate' then 'awaiting_review' when p_classification='needs_human' then 'needs_human' else 'suppressed' end);
  end if;
  return inserted;
end $$;
revoke all on function public.ingest_x_mention(jsonb,text,text) from public,anon,authenticated;
grant execute on function public.ingest_x_mention(jsonb,text,text) to service_role;

create or replace function public.stage_x_write_preflight(p_run_id text,p_idempotency_key text,p_fingerprint text,p_payload jsonb,p_decision jsonb,p_expected_memory_version bigint,p_memory jsonb) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ declare next_version bigint; begin
  if not exists(select 1 from staging_metadata where singleton and environment='staging') then raise exception 'not a staging database'; end if;
  if exists(select 1 from delivery_ledger where updated_at>=now()-interval '24 hours' and status in ('candidate','sending','sent') and payload->>'fingerprint'=p_fingerprint) then raise exception 'duplicate payload fingerprint' using errcode='23505'; end if;
  insert into job_runs(run_id,mode,status,decision) values(p_run_id,'dry_run','decided',p_decision);
  insert into post_decisions(run_id,action,category,motif,event_id,song_id,media_id,include_url,reason,snapshot) values(p_run_id,'post',p_decision->>'category',p_decision->>'motif',nullif(p_decision->>'event_id',''),nullif(p_decision->>'song_id',''),nullif(p_decision->>'media_id',''),coalesce((p_decision->>'include_url')::boolean,false),p_decision->>'reason',p_decision);
  update memory_state set value=p_memory,version=version+1,updated_at=now() where singleton and version=p_expected_memory_version returning version into next_version;
  if next_version is null then raise exception 'memory version conflict' using errcode='40001'; end if;
  insert into delivery_ledger(idempotency_key,run_id,kind,status,payload) values(p_idempotency_key,p_run_id,'post','candidate',p_payload);
  return true;
end $$;
revoke all on function public.stage_x_write_preflight(text,text,text,jsonb,jsonb,bigint,jsonb) from public,anon,authenticated;
grant execute on function public.stage_x_write_preflight(text,text,text,jsonb,jsonb,bigint,jsonb) to service_role;

-- Phase 9: close the exact unsent Phase 8 dry-run without erasing its audit trail.
create or replace function public.supersede_x_write_preflight(p_run_id text,p_expected_memory_version bigint,p_memory jsonb) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ declare next_version bigint; begin
  if not exists(select 1 from staging_metadata where singleton and environment='staging') then raise exception 'not a staging database'; end if;
  if not exists(select 1 from job_runs r join delivery_ledger l using(run_id) where r.run_id=p_run_id and r.mode='dry_run' and l.status='candidate' and l.external_id is null) then raise exception 'preflight is not safely supersedable' using errcode='40001'; end if;
  update delivery_ledger set status='failed',payload=payload||jsonb_build_object('superseded',true,'superseded_reason','replaced by approved Phase 9 live run','superseded_at',now()),updated_at=now() where run_id=p_run_id and status='candidate' and external_id is null;
  if not found then raise exception 'preflight ledger state conflict' using errcode='40001'; end if;
  update job_runs set status='safe_stopped',finished_at=now(),error='superseded before approved live send' where run_id=p_run_id and mode='dry_run';
  update memory_state set value=p_memory,version=version+1,updated_at=now() where singleton and version=p_expected_memory_version returning version into next_version;
  if next_version is null then raise exception 'memory version conflict' using errcode='40001'; end if;
  return true;
end $$;
revoke all on function public.supersede_x_write_preflight(text,bigint,jsonb) from public,anon,authenticated;
grant execute on function public.supersede_x_write_preflight(text,bigint,jsonb) to service_role;

-- A live run is staged before the sole external effect. No database function can call X.
create or replace function public.stage_x_single_post(p_run_id text,p_idempotency_key text,p_fingerprint text,p_payload jsonb,p_decision jsonb,p_expected_memory_version bigint,p_memory jsonb) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ declare next_version bigint; begin
  if not exists(select 1 from staging_metadata where singleton and environment='staging') then raise exception 'not a staging database'; end if;
  if (p_payload->>'fingerprint') is distinct from p_fingerprint or (p_payload->>'x_app_id') is distinct from '31849050' or coalesce((p_payload->>'human_approved_single_post')::boolean,false) is not true then raise exception 'live payload authorization mismatch'; end if;
  if exists(select 1 from delivery_ledger where updated_at>=now()-interval '24 hours' and status in ('candidate','sending','sent') and payload->>'fingerprint'=p_fingerprint) then raise exception 'duplicate payload fingerprint' using errcode='23505'; end if;
  insert into job_runs(run_id,mode,status,decision) values(p_run_id,'send','decided',p_decision);
  insert into post_decisions(run_id,action,category,motif,event_id,song_id,media_id,include_url,reason,snapshot) values(p_run_id,'post',p_decision->>'category',p_decision->>'motif',nullif(p_decision->>'event_id',''),nullif(p_decision->>'song_id',''),nullif(p_decision->>'media_id',''),coalesce((p_decision->>'include_url')::boolean,false),p_decision->>'reason',p_decision);
  update memory_state set value=p_memory,version=version+1,updated_at=now() where singleton and version=p_expected_memory_version returning version into next_version;
  if next_version is null then raise exception 'memory version conflict' using errcode='40001'; end if;
  insert into delivery_ledger(idempotency_key,run_id,kind,status,payload) values(p_idempotency_key,p_run_id,'post','candidate',p_payload);
  return true;
end $$;
revoke all on function public.stage_x_single_post(text,text,text,jsonb,jsonb,bigint,jsonb) from public,anon,authenticated;
grant execute on function public.stage_x_single_post(text,text,text,jsonb,jsonb,bigint,jsonb) to service_role;

create or replace function public.begin_x_single_post(p_run_id text,p_idempotency_key text,p_fingerprint text) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ begin
  update delivery_ledger set status='sending',updated_at=now() where run_id=p_run_id and idempotency_key=p_idempotency_key and status='candidate' and external_id is null and payload->>'fingerprint'=p_fingerprint and payload->>'x_app_id'='31849050';
  if not found then raise exception 'live ledger state conflict' using errcode='40001'; end if;
  update job_runs set status='running' where run_id=p_run_id and mode='send' and status='decided';
  if not found then raise exception 'live run state conflict' using errcode='40001'; end if;
  return true;
end $$;
revoke all on function public.begin_x_single_post(text,text,text) from public,anon,authenticated;
grant execute on function public.begin_x_single_post(text,text,text) to service_role;

create or replace function public.complete_x_single_post(p_run_id text,p_idempotency_key text,p_external_id text,p_motif text) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ begin
  if p_external_id is null or btrim(p_external_id)='' then raise exception 'missing external id'; end if;
  update delivery_ledger set status='sent',external_id=p_external_id,updated_at=now() where run_id=p_run_id and idempotency_key=p_idempotency_key and status='sending' and external_id is null;
  if not found then raise exception 'live completion state conflict' using errcode='40001'; end if;
  insert into usage_history(kind,item_id,run_id) values('motif',p_motif,p_run_id);
  update job_runs set status='succeeded',finished_at=now(),error=null where run_id=p_run_id and mode='send' and status='running';
  insert into settings(key,value) values('consecutive_errors','0'::jsonb) on conflict(key) do update set value='0'::jsonb,updated_at=now();
  return true;
end $$;
revoke all on function public.complete_x_single_post(text,text,text,text) from public,anon,authenticated;
grant execute on function public.complete_x_single_post(text,text,text,text) to service_role;

create or replace function public.stop_x_single_post(p_run_id text,p_idempotency_key text,p_delivery_unknown boolean,p_error_category text) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$ begin
  update delivery_ledger set status=case when p_delivery_unknown then 'sending' else 'failed' end,payload=payload||jsonb_build_object('failure_category',p_error_category,'reconciliation_required',p_delivery_unknown),updated_at=now() where run_id=p_run_id and idempotency_key=p_idempotency_key and status in ('candidate','sending') and external_id is null;
  update job_runs set status=case when p_delivery_unknown then 'safe_stopped' else 'failed' end,finished_at=now(),error=p_error_category where run_id=p_run_id and mode='send' and status in ('decided','running');
  return true;
end $$;
revoke all on function public.stop_x_single_post(text,text,boolean,text) from public,anon,authenticated;
grant execute on function public.stop_x_single_post(text,text,boolean,text) to service_role;
