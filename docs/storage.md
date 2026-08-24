# Supabase storage plan

初期V2はDB未設定でも診断とDRY RUNが動く。Supabaseのアカウント／プロジェクト作成は今回行わない。

## 環境変数

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

service role keyはRenderの秘密環境変数だけに保存し、HPやブラウザへ渡さない。

## 最小テーブル

- `job_runs`: 起動、モード、開始／終了、結果、エラー
- `posts`: 候補、カテゴリー、投稿判断、X Post ID、成功日時
- `media_usage`: 画像と利用日時
- `song_usage`: 曲と利用日時
- `story_events`: 継続中の生活イベント
- `contacts`: 会話相手、opt-out状態、最終接触
- `conversations`: 取得したリプ／メンションと会話要約
- `reply_candidates`: AI候補、人間承認、送信状態

`posts.idempotency_key` と `conversations.x_post_id` を一意にし、Cron再実行時の二重処理を防ぐ。
