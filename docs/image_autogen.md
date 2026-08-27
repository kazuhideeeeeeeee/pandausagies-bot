# Image Autogen Phase A

pandausagies V2.xの画像候補生成は、既存のDirectorが通常の生活リズムで`post`を決めた後に`text_only` / `image_single` / `skip`を選び、画像専用pipelineへ渡す構造です。初期比率は、その通常投稿候補の中でtext 70% / image 20% / additional skip 10%です。Phase Aはstaging限定で、実画像APIとX writeを呼びません。

## 安全境界

- `APP_ENV=staging`
- `IMAGE_PROVIDER=fake`
- `IMAGE_AUTOGEN_ENABLED=true`
- `ALLOW_EXTERNAL_SEND=false`
- `AUTONOMOUS_ENABLED=false`
- `KILL_SWITCH=true`
- `X_WRITE_ENABLED=false`
- retryは0回
- 連続3失敗で画像専用circuit breakerを開く
- 生成失敗・審査不合格・重複・上限到達時は`text_only`へフォールバック
- prompts、jobs、generated mediaはprivate stateでありPUBLIC STATEへ出さない
- 公式reference画像は読み取りanchorであり、加工・上書き・Storage移動をしない

production runnerは画像設定を明示的に渡さないため、従来どおり`text_only`が既定です。Render productionやX credentialsはPhase Aでは変更しません。

## Pipeline

1. Director decision
2. `post_type`選択
3. structured `ImagePlan`
4. version付きprompt生成
5. plan fingerprint / provider試行回数ベースの日次・月次上限
6. provider生成
7. safety/quality validation
8. media fingerprint
9. private Supabase Storage保存
10. `media_jobs` / `generated_media`保存
11. staging candidateとして停止（X write 0）

## Provider abstraction

- `FakeImageProvider`: 固定の小さなPNGと検証用quality signalsを返す。外部通信0。
- `OpenAIImageProvider`: Phase Bでgeneration callableを注入する境界。Phase AではclientもAPI keyも生成しない。

## Visual rules

promptは成人（24歳）の日本人女性、ピンク髪ボブ、原則メガネ、私的な生活スナップ、2000年代コンデジ／トイカメラ風を固定します。sceneは既存10 motifへ接続し、電車・駅・歩道橋・夜カフェ・古い喫茶店・部屋・台所・机・パン・お弁当・花・近所・自販機・公園・雨・ギター・眼鏡・髪・ぼんやりした瞬間を候補に含めます。直近scene/outfitを避け、メガネは長期的に約80%を目安にします。

公式5画像は`content/media.json`のapproved IDをplanへ記録するidentity/air anchorです。Phase Aでは画像バイトをproviderへ送らず、加工・上書きもしません。Phase B providerはこのIDから明示的にreferenceを解決できる構造です。

禁止項目は未成年に見える表現、性的文脈、露出、暴力・自傷・グロ、著名人類似、政治・宗教、支配的ロゴ、コスプレ、ホラーです。

## Storage

`db/image_autogen_staging.sql`はstaging markerを確認してから次を追加します。

- private table `media_jobs`
- private table `generated_media`
- private bucket `generated-media`
- schema version 2
- staging reset対象への追加

匿名・authenticated roleにはtable accessを与えません。Backend Secretはbackendの`apikey` headerだけに使用し、ブラウザ、URL、log、tracked fileへ出しません。

## Configuration

非秘密項目は`.env.example`を参照してください。Phase Bまでは`IMAGE_PROVIDER=openai`を有効にせず、production rolloutには別途明示承認が必要です。

## Verification

```bash
python3 -m unittest tests.test_image_autogen -v
IMAGE_PROVIDER=fake IMAGE_AUTOGEN_ENABLED=true python3 scripts/run_image_phase_a.py
```

後者はstaging schema適用後にのみ実行し、Directorが20%設定の通常ロジック内で`image_single`を選ぶseedを有界探索します。保存後も`selected_for_post=false`で停止します。
