---
name: ohayou-stock-mail
description: ユーザーが「おはよう」「おはよ」「good morning」と言ったとき、または「朝メール／朝の株候補を送って」と頼んだときに使う。kabukatsuroの朝メール（週足GC直前テクニカルスクリーニング＋本日の好材料銘柄＋夜間PTS・投稿数の注目銘柄）を組み立て、Gmailで送信する。日本株デイトレ向けの morning stock screening email を送る朝のルーティン。
---

# おはよう＝朝の株候補メール送信

「おはよう」と言われたら、このルーティンを実行して当日の朝メールを送る。
スケジュール実行版は `routines/morning.yml`（毎営業日8:00）。内容は常にこのスキルと一致させること。

作業ディレクトリは `/Users/yuthsd/Desktop/kabukatsuro`。
プロジェクトの `.venv` と `.env.local` をそのまま使う（認証情報は `.env.local` にあり、リポジトリにはコミットしない）。

## 手順

### 0. 準備（環境変数の読み込み・依存確認）
```bash
cd /Users/yuthsd/Desktop/kabukatsuro
set -a; . ./.env.local; set +a          # GMAIL_USER / GMAIL_APP_PASSWORD / TO_EMAIL を読み込む
.venv/bin/python -c "import yfinance,pandas,xlrd,jpholiday,requests" 2>/dev/null \
  || .venv/bin/pip install -q yfinance pandas xlrd jpholiday requests
```

### 1. テクニカルスクリーニング（全銘柄。数分かかる）
```bash
.venv/bin/python scripts/screener.py --out /tmp/screen.json
```
- 出力に `SKIP`（終了コード10）が出たら本日は休場日（土日・祝日）。
  **以降を中止し、メールは送らず「休場日のためスキップ」と報告して終了する。**

### 2. 本日の好材料銘柄 TOP10 を選定 → /tmp/hot.json
WebSearch で当日〜直近の材料を調べ、下記の観点で10銘柄を選ぶ。
- 決算（上方修正・増配・好決算）
- 証券会社の目標株価引き上げ・買い推奨（レーティング格上げ）
- 自社株買い発表 / M&A・提携・新製品 / 出来高急増・話題銘柄
- **★追加ソース（下記「注目銘柄の見つけ方」）で拾った夜間PTS・投稿数の注目銘柄**

`code`（4桁東証コード）と `price`（概算現在株価・数値）は **yfinanceで裏取り** する：
```bash
.venv/bin/python -c "import yfinance as yf;print(round(float(yf.Ticker('CODE.T').history(period='5d')['Close'].iloc[-1]),1))"
```
保存形式（配列のみ。コードフェンス・説明文は書かない）:
```json
[{"code":"7272","name":"ヤマハ発動機","price":1279,"reason":"Q1決算で営業利益+43.8%、通期増益予想"}]
```

### 3. メール送信
```bash
.venv/bin/python scripts/mailer.py morning --screen /tmp/screen.json --hot /tmp/hot.json
```

### 4. 報告
Section1/2/3 の各銘柄数、送信先、エラーの有無を簡潔に報告する。

---

## 注目銘柄の見つけ方（本で学んだ手法 — Section1の選定に必ず使う）

材料銘柄を探すとき、ニュース検索に加えて次の2つのランキングを確認する。
拾った候補は **必ずニュースで材料を裏取り** してから採用し、具体的な好材料があるものを優先する。

### A. 夜間PTS取引高ランキング（最重要）
前日の夜にどの銘柄がどれだけ売買されたかは、当日の寄り付きを占う重要材料。
- 見るのは「買付取引**成立**数」ではなく **「買付取引未成率（買い注文の未成立比率）」**。
  - 取引が「未成立」＝買いに対して売りが出ない（売り渋り）状態。
    PTSで成立しなかった分、**翌朝の寄りに買いが殺到してギャップアップする可能性が高い**。
- さらに、その未成立分の **「件数」** を必ず確認する。
  - 「買付取引未成立株数」が多くても **件数が1件だけ** なら単一の大口注文にすぎず、上昇余地は読めない。
    **件数が多い**（多数の参加者が買い向かっている）銘柄を重視する。
- 探し方の例: `PTS 夜間 ランキング 買付 未成立 件数` 等で検索。
  SBI証券のPTS夜間取引ランキング、株探・みんかぶのPTSランキングなどを参照する。

### B. Yahoo!ファイナンス 銘柄別投稿数ランキング（参考程度）
- 掲示板の **投稿数が多い＝注目度が高い**。https://finance.yahoo.co.jp/ の掲示板/投稿数ランキングを確認。
- あくまで注目度の目安。材料の裏取り（決算・自社株買い・レーティング等のニュース確認）は別途 WebSearch で行う。

> いずれも「注目度・需給の偏り」を示すシグナル。最終的に Section1 に載せるのは
> 具体的な好材料があり、かつ需給（PTS未成率・件数）や注目度（投稿数）の裏付けがある銘柄を優先する。

---

## メモ
- 投資助言ではない。メール末尾に「投資判断はご自身で」の注記あり。
- 認証情報（`GMAIL_APP_PASSWORD`）はこのファイルや公開リポジトリに**絶対に書かない**。`.env.local`（gitignore済み）に置く。
