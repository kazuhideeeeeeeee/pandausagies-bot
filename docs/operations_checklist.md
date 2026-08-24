# Phase 0 Operations Checklist

このチェックは本番投稿を行わない。秘密値はコピーせず、設定の有無と状態だけを確認する。

## Render Dashboard

- 対象サービスの種類がCron Jobか確認
- Start Commandが `python v2_bot.py` へ切替可能な状態か確認（今回は変更しない）
- Cron ScheduleとUTC/JST換算を確認
- 接続GitHubリポジトリとbranchを確認
- Environmentに `API_KEY`、`API_SECRET`、`ACCESS_TOKEN`、`ACCESS_TOKEN_SECRET` が同名で存在するか確認
- 必要なら `OPENAI_API_KEY`、`TIMEZONE` が存在するか確認
- 2026-06-15〜2026-06-17のLogsを開く
- 最後に `[OK]` が出た実行日時とPost IDを記録
- 最初に `[X POST ERROR]`、`[FATAL]`、認証警告が出た実行日時と全文を記録
- Deploy historyで、その直前のbuild、commit、Python／依存更新を確認
- Billing、CronのSuspend状態、失敗通知設定を確認
- 診断時はStart Commandを変更せず、ShellまたはPreview環境で `python diagnose.py` を実行

## X Developer Console

- 対象Project/AppがActiveか確認
- 現在のクレジット残高、支出上限、残高不足履歴を確認
- App permissionsがRead and Writeか確認
- Consumer Key/SecretとAccess Token/Secretが同じApp・同じユーザー用か確認
- トークンが権限変更前に発行されたものなら、再発行の必要性だけ確認（今回は変更しない）
- Posts createとmedia uploadにアクセスできるプランか確認
- 2026-06-15〜2026-06-17付近のusage・請求・拒否履歴を確認
- アカウント／Appのsuspension、policy notice、メール通知を確認

## 収集して次工程へ渡す情報

- Renderの最後の成功ログ
- 最初の失敗ログとHTTP status/error code
- 当時のcommit SHA
- 実際のStart CommandとCron Schedule
- X App status、権限、クレジット状態

秘密値そのものはIssue、チャット、ログへ貼らない。
