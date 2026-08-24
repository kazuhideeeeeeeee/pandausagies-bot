# Production Adapter Design

## Atomic boundaries

- RUN START transaction: lease取得、`run_id`一意登録、memory読込。
- DECISION transaction: decision保存、candidate/ledger作成、event・usageを含むmemory commit、WEEK plannedを同時確定。
- POST DELIVERY: DB transaction外のremote effect。`candidate → sending → sent/unknown/retry_wait/failed`を短いtransactionで遷移。
- WEEK: post sent確定後に`planned → publishing → published/unknown/retry_wait/failed`。
- PUBLIC STATE: published WEEKだけからversion付きsnapshot一枚を生成し、CASで現行versionを交換。

外部effectをDB transactionに含めず、exactly-onceを仮定しない。ledger、unique key、payload fingerprint、remote lookupでeffectively-onceを目指す。

## Production Postgres lock recommendation

推奨は専用`job_leases`行をRPC内のatomic `INSERT ... ON CONFLICT ... DO UPDATE ... WHERE expires_at <= now()`で取得するlease方式。owner、acquired_at、heartbeat_at、expires_atを保持する。REST越しでも1回のserver-side transactionに閉じられ、advisory lockのsession固定を要求しないためSupabaseと相性がよい。heartbeatはjob中60秒ごと、leaseは5分。期限切れだけ別runが回収する。

## Retry and reconciliation

timeout/response lostは`unknown`として即再送しない。remote fingerprint lookupを行い、存在すればsent。見つからない状態が規定回数続いた後だけretryする。429は`retry_after`まで停止。5xx・一時networkは指数backoff。auth、permission、policy rejection、invalid mediaは自動retry禁止で通知する。

## HP public state

推奨は「小さなversion付き公開JSON snapshot + static fallback」。静的HPはruntime endpointを最初に読み、失敗・不整合時は同梱`content/current.json`と`weeks.json`を使う。Supabase tableをブラウザから組み立てるより、途中状態を見せず、RLS面積も小さい。

## Clean start

本番はproduction clean startを推奨する。SQLite、simulation WEEK、week-00 previewは移行しない。empty production DB、明示した`AUTONOMOUS_EPOCH`、両Hard Gate、Kill Switch OFFを確認した最初のweekly cycleで本人がWEEK 01を決める。

Render logical run idは`{job}:{scheduled UTC ISO minute}`、例`check:2026-08-25T03:00:00Z`。retryは同じscheduled slotを使う。Cronは投稿命令ではなく、起きて確認する契機。
