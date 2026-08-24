# PRODUCTION SAFETY CORE

## Fail closed

Storage・履歴・時刻・lock・設定を確認できない場合は送信しない。`AUTONOMOUS_ENABLED=true`と`ALLOW_EXTERNAL_SEND=true`の両方が必要で、`KILL_SWITCH=true`は常に優先する。重大エラー3回連続でCircuit Breakerが開く。

## 永続化と一意性

ローカル検証はSQLiteを使う。`run_id`、投稿`idempotency_key`、WEEK番号とWEEKの`run_id`に一意制約がある。lockは期限付き行を`BEGIN IMMEDIATE`で取得する。Directorは保存先を知らない。

投稿は`candidate → sending → sent`または`failed`、WEEKは`planned → published`または`failed`。送信成功前に`sent`、公開成功前に`published`へしない。

## Crash recovery

Decisionのみなら同じdecisionを復元し、candidate以降なら同じidempotency keyで再開する。送信後DB確定前は送信先の`lookup(key)`を先に行い、存在すれば再送せずDBだけ確定する。本番X adapterには、この照合能力または同等のdelivery ledgerが必須。

## PUBLIC STATE

公開対象はcurrent WEEK、画像識別子、本文、曲識別子、past WEEKのみ。decision reason、errors、contacts、user ID、秘密設定は含めない。

SupabaseStorageは注入client用の境界だけを持ち、URL・鍵・通信処理はPhase 4に含めない。
