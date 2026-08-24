# AUTONOMOUS CORE

## 固定されるもの

`docs/character_bible.md`、`docs/social_voice.md`、禁止語、投稿上限、安全・セキュリティ設定はDirectorの入力ではなく境界条件です。自律処理はコード、Git、APIキー、契約、規約解釈を変更しません。

## 判断順序

1. JST時刻、直近投稿、WEEK、曲・画像・motif使用履歴、open life eventを読む。
2. 1日上限と週次上限を先に適用する。
3. 投稿またはskipを選ぶ。
4. 継続中eventも参照しつつ、正式10 motifを日常側7：祝祭側3の長期重みで選ぶ。天気は背景でありmotifにしない。
5. 直近重複と累計回数を避けて、登録済み実在曲・承認済み原画像だけを選ぶ。
6. 具体物＋具体行動から1〜2行を作る。擬人化、比喩、詩的回収、コピー的な二行目へ強いペナルティを与え、禁止語、hashtag、絵文字、広告調も検証する。
7. OBSERVEは複製memory上で判断して破棄する。SIMULATIONもin-memoryのみで、正式WEEKを確定しない。

## memory

`posts`, `decisions`, `weeks`, `events`, `media_usage`, `song_usage`, `motif_usage`, `settings`を保持します。life eventは`id/type/start_date/status/summary/motif/related_posts/earliest_next_ref/reference_count/target_refs/outcome/closed_at`を持ちます。一回限り、2回、4回の長さがあり、一部は回収せず`forgotten`で終わります。

本番用の保存先は将来Supabase adapterへ差し替えます。`db/schema.sql`はその目標構造だけを定義し、今回はDB作成・接続・鍵設定を行いません。

## WEEK

本番開始日を基準に7日ごとにDirectorが曲・画像・文章を決定し、確定後はimmutable archiveとして追記します。OBSERVEはWEEKを作らず、SIMULATIONの`week-01`以降はすべて`status=simulated`で本番データではありません。

## 表現生成

何をするか、event、motif、曲、画像、URL有無はコードが決めます。OpenAIは将来の任意アダプタとして最後の1〜2行を整える範囲だけに限定します。Phase 3では無効であり、APIキーがなくても`LocalExpressionProvider`で全機能が動きます。
