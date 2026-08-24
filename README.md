# pandausagies V2

pandausagiesのX、公式HP、週次画像、楽曲導線をつなぐ小さな運用システムです。旧V1資産は削除せず保持しています。

## 安全なローカル確認

Python 3.12を使い、仮想環境へ `requirements.txt` をインストールします。

```bash
python diagnose.py
python v2_bot.py
python -m unittest discover -s tests -v
```

`python v2_bot.py` は常にDRY RUNです。Xへ送信する唯一の明示スイッチは `--send` ですが、本番確認が完了するまで使用しません。

## HP MVP

公開対象だけを `dist/` へまとめ、そこだけをローカル配信します。

```bash
python scripts/build_site.py
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

ブラウザで `http://127.0.0.1:8000/` を開きます。正式canonical URLは `https://pandausa.dwmdog.com` です。DNS・Render独自ドメイン設定はこのリポジトリから変更しません。

Render Static SiteではBuild Commandを `python scripts/build_site.py`、Publish Directoryを `dist` とする想定です。今回はRender設定を変更しません。

週次更新は `media/weeks/` に画像を追加し、`content/weeks.json` と `content/current.json` を更新します。曲は実在する動画だけを `content/songs.json` に登録します。

## 運用資料

- `docs/character_bible.md`
- `docs/social_voice.md`
- `docs/operations_checklist.md`
- `docs/storage.md`
- `db/schema.sql`

`bot.py`、`ugokubot.py`、旧人格・音楽参照・地名資料、旧画像と動画はlegacy原本として保持します。

## AUTONOMOUS CORE（ローカル観察専用）

Phase 3では、固定された人格・声・安全制約の内側で、投稿／skip、カテゴリー、モチーフ、life event、曲、既存画像、WEEKを選ぶDirectorを追加しています。コードやCharacter Bibleを自分で変更する機能はありません。

```bash
python autonomous.py --observe --seed 1
python simulate.py --days 60 --seed 1234
```

OBSERVEとSIMULATIONは状態を保存せず、X、OpenAI、Supabase、Render、画像生成APIへ接続しません。正式WEEK 01も確定しません。OpenAIは将来、Directorが決めた内容を1〜2行へ整える任意の表現アダプタに限定し、キーが無い場合は現在のローカル断片だけで継続します。

## PRODUCTION SAFETY CORE

ローカルSQLiteで再起動、重複run、lock競合、crash recoveryを検証できます。外部送信は既定で二重に無効です。

```bash
python3 autonomous.py --health
python3 safety_scenarios.py
python3 production_regression.py --days 90 --seeds 1001 3003 5005
```

送信可能条件は`AUTONOMOUS_ENABLED=true`かつ`ALLOW_EXTERNAL_SEND=true`かつ`KILL_SWITCH=false`です。Phase 4には実ネットワークsenderを接続していません。
