-- Phase 9 staging-only one-shot X write state machine. No external API calls.

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
