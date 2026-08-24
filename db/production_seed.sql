-- Clean production seed: formal content, official identity, and the verified Phase 9 live post only.

update public.memory_state set version=1,value=$memory$
{
  "posts":[{"at":"2026-08-24T17:08:02+09:00","text":"メガネのねじを締めた\n小さいドライバーを使った","motif":"glasses","action":"post","reason":"Phase 8 validated first live post","song_id":null,"week_id":null,"category":"ordinary","event_id":null,"media_id":null,"include_url":false,"event_action":"none"}],
  "decisions":[{"at":"2026-08-24T17:08:02+09:00","text":"メガネのねじを締めた\n小さいドライバーを使った","motif":"glasses","action":"post","reason":"Phase 8 validated first live post","song_id":null,"week_id":null,"category":"ordinary","event_id":null,"media_id":null,"include_url":false,"event_action":"none"}],
  "weeks":[],"events":[],"media_usage":{},"song_usage":{},"motif_usage":{"glasses":["2026-08-24T17:08:02+09:00"]},
  "settings":{"normal_daily_limit":2,"weekly_image_limit":1,"weekly_song_limit":1,"continuity_weight":0.8}
}
$memory$::jsonb,updated_at='2026-08-24T08:08:06.311364+00:00' where singleton and environment='production' and version=0;

insert into public.job_runs(run_id,mode,status,started_at,finished_at,decision)
values('x-first-live-post:2026-08-24T08:08:02Z','send','succeeded','2026-08-24T08:08:06.311364+00:00','2026-08-24T08:08:07.323753+00:00',$decision${"at":"2026-08-24T17:08:02+09:00","text":"メガネのねじを締めた\n小さいドライバーを使った","motif":"glasses","action":"post","reason":"Phase 8 validated first live post","song_id":null,"week_id":null,"category":"ordinary","event_id":null,"media_id":null,"include_url":false,"event_action":"none"}$decision$::jsonb)
on conflict(run_id) do nothing;

insert into public.post_decisions(run_id,action,category,motif,include_url,reason,snapshot,decided_at)
values('x-first-live-post:2026-08-24T08:08:02Z','post','ordinary','glasses',false,'Phase 8 validated first live post',$decision${"at":"2026-08-24T17:08:02+09:00","text":"メガネのねじを締めた\n小さいドライバーを使った","motif":"glasses","action":"post","reason":"Phase 8 validated first live post","song_id":null,"week_id":null,"category":"ordinary","event_id":null,"media_id":null,"include_url":false,"event_action":"none"}$decision$::jsonb,'2026-08-24T08:08:06.311364+00:00')
on conflict(run_id) do nothing;

insert into public.delivery_ledger(idempotency_key,run_id,kind,status,payload,external_id,updated_at)
values('x:x-first-live-post:2026-08-24T08:08:02Z','x-first-live-post:2026-08-24T08:08:02Z','post','sent',$payload${"at":"2026-08-24T17:08:02+09:00","url":null,"text":"メガネのねじを締めた\n小さいドライバーを使った","motif":"glasses","action":"post","reason":"Phase 8 validated first live post","run_id":"x-first-live-post:2026-08-24T08:08:02Z","song_id":null,"week_id":null,"category":"ordinary","event_id":null,"media_id":null,"x_app_id":"31849050","media_hash":null,"media_path":null,"fingerprint":"71506361dc67e1ff2e4d932d52acb657129ec5cddb4f7d5d058f1f648d46a220","include_url":false,"event_action":"none","scheduled_jst":"2026-08-24T17:08:02+09:00","idempotency_key":"x:x-first-live-post:2026-08-24T08:08:02Z","human_approved_single_post":true}$payload$::jsonb,'2091799699821117644','2026-08-24T08:08:07.323753+00:00')
on conflict(idempotency_key) do nothing;

insert into public.usage_history(kind,item_id,run_id,used_at)
select 'motif','glasses','x-first-live-post:2026-08-24T08:08:02Z','2026-08-24T08:08:07.323753+00:00' where not exists(select 1 from public.usage_history where run_id='x-first-live-post:2026-08-24T08:08:02Z' and kind='motif' and item_id='glasses');

insert into public.x_account_identities(handle,x_user_id,current_username,display_name,resolved_at,updated_at)
values('pandausagies','1988900673572974592','pandausagies','パンダうさギーズ','2026-08-24T07:13:11.240953+00:00','2026-08-24T07:13:11.240953+00:00')
on conflict(handle) do update set x_user_id=excluded.x_user_id,current_username=excluded.current_username,display_name=excluded.display_name,updated_at=excluded.updated_at;

insert into public.settings(key,value) values
('consecutive_errors','0'::jsonb),('circuit_open','false'::jsonb),('public_version','1'::jsonb)
on conflict(key) do update set value=excluded.value,updated_at=now();

insert into public.public_songs(id,title,youtube_video_id,youtube_url,release_info,active) values
('tokunaru','遠くなる','G3S9MQibBWM','https://www.youtube.com/watch?v=G3S9MQibBWM','{"release":"パンダうさギーズ","order":1}'::jsonb,true),
('come-on','Come On','nvftQJgKzF0','https://www.youtube.com/watch?v=nvftQJgKzF0','{"release":"パンダうさギーズ","order":2}'::jsonb,true),
('wakaranaitte-iunayo','わからないっていうなよ','6HgpBssiUEA','https://www.youtube.com/watch?v=6HgpBssiUEA','{"release":"パンダうさギーズ","order":3}'::jsonb,true),
('kakinoki-no-saru','柿の木の猿','AYFH1KOxHbw','https://www.youtube.com/watch?v=AYFH1KOxHbw','{"release":"パンダうさギーズ","order":4}'::jsonb,true),
('sekai-de-ichiban-yasashii-otoko','世界で一番優しい男','JpEepeGgmt4','https://www.youtube.com/watch?v=JpEepeGgmt4','{"release":"パンダうさギーズ","order":5}'::jsonb,true),
('baby','Baby','Y3PFKTVvD6w','https://www.youtube.com/watch?v=Y3PFKTVvD6w','{"release":"パンダうさギーズ","order":6}'::jsonb,true),
('onaji-tsuki-album','同じ月(アルバムバージョン)','Zl30Fw2eJzM','https://www.youtube.com/watch?v=Zl30Fw2eJzM','{"release":"パンダうさギーズ","order":7}'::jsonb,true),
('pandausagies-sengen','パンダうさギーズ宣言','OKmuI01LTF8','https://www.youtube.com/watch?v=OKmuI01LTF8','{"release":"パンダうさギーズ","order":8}'::jsonb,true),
('onaji-tsuki-single','同じ月(シングルバージョン)','eBt7aBzkMh8','https://www.youtube.com/watch?v=eBt7aBzkMh8','{"release":"同じ月","order":1}'::jsonb,true),
('whatever','ワットエバー','ajoQcfkdhko','https://www.youtube.com/watch?v=ajoQcfkdhko','{"release":"同じ月","order":2}'::jsonb,true)
on conflict(id) do update set title=excluded.title,youtube_video_id=excluded.youtube_video_id,youtube_url=excluded.youtube_url,release_info=excluded.release_info,active=excluded.active;

insert into public.public_media(id,public_url,alt_text,active) values
('portrait-coat','https://pandausa.dwmdog.com/media/weeks/week-00.png','ピンクの髪とダブルブリッジ眼鏡のpandausagies',true),
('old-room-table','https://pandausa.dwmdog.com/media/reference/2ndg.png','古い部屋の食卓で過ごすpandausagies',true),
('crown-flowers','https://pandausa.dwmdog.com/media/reference/baby3.png','王冠と花に囲まれたpandausagies',true),
('flowers-portrait','https://pandausa.dwmdog.com/media/reference/ps.png','花に囲まれたpandausagies',true),
('sweater-portrait','https://pandausa.dwmdog.com/media/reference/bjork.png','セーター姿で正面を向くpandausagies',true)
on conflict(id) do update set public_url=excluded.public_url,alt_text=excluded.alt_text,active=excluded.active;

insert into public.public_state_snapshots(payload,published)
select '{"version":1,"generated_at":"2026-08-24T08:08:07.323753+00:00","currentWeek":null,"pastWeeks":[]}'::jsonb,true
where not exists(select 1 from public.public_state_snapshots where published=true);
