# stock-screening

デイトレ向け株スクリーニング自動メール通知ツール。
Claude Code Routinesで毎営業日に自動実行。PCがオフラインでも動作します。

## 構成

```
.
├── scripts/
│   ├── screener.py   # テクニカルスクリーニング（JPX全銘柄 × yfinance週足）
│   └── mailer.py     # メール整形・送信（朝/昼 兼用）
├── routines/
│   ├── morning.yml   # Routine設定（朝8:00）
│   └── afternoon.yml # Routine設定（昼12:30）
├── .env.example      # 環境変数テンプレート
└── README.md
```

## メール内容

### 朝8:00メール（3セクション）
- 📰 Section 1: 本日の好材料銘柄 TOP10（Routineエージェントが Web 検索）
- 📈 Section 2: 週足GC直前ランキング TOP10（条件を全て満たす銘柄を乖離率の低い順）
- 💡 Section 3: GC直前（株価2300円超）参考リスト TOP10（「株価2300円未満」だけ満たさない銘柄）

### 昼12:30メール
- 📈 午後から上昇期待の銘柄 TOP10（現在株価・前日比・出来高・コメント付き）
  ※ 午後はテクニカルの Section 2・3 は送りません。

各銘柄名はYahooファイナンスの週足チャートへのリンク付き。

## スクリーニング条件（Section 2・3）

- `株価 < 2300円`（Section 3 はこの条件だけ満たさない銘柄）
- `SMA(13週) < SMA(26週)` → GC未成立
- `株価 > SMA(26週)` → 株価は26週線を上抜け済み
- `乖離率 = (SMA26 - SMA13) / SMA26 < 5%` → GC直前（この値が小さい順にランキング）

## 銘柄ユニバース

JPX公式の「上場銘柄一覧（data_j.xls）」を毎回取得し、
東証プライム/スタンダード/グロースの内国普通株（約3,500銘柄）を対象にします。
銘柄名もこのリストから取得するため、yfinanceの遅い `.info` 呼び出しは行いません。

## 営業日判定

土日および日本の祝日（`jpholiday`）は自動でスキップします。
`screener.py` が休場日に `SKIP`（終了コード10）を返し、Routine側でメール送信を中止します。

## セットアップ

### 1. 環境変数

Routine（およびローカルテスト）に以下を設定：

| 変数名 | 内容 |
|--------|------|
| `GMAIL_USER` | 送信元Gmailアドレス |
| `GMAIL_APP_PASSWORD` | Googleアプリパスワード（16桁） |
| `TO_EMAIL` | 送信先（カンマ区切りで複数可） |

**Googleアプリパスワード取得手順：**
1. https://myaccount.google.com/apppasswords にアクセス
2. 「アプリを選択」→「メール」、「デバイス」→「その他」
3. 生成された16文字のパスワードを `GMAIL_APP_PASSWORD` に設定

> Anthropic APIキーは不要です（好材料・午後候補の Web 検索は Routineエージェント自身が行います）。

### 2. GitHubリポジトリにpush

```bash
git add .
git commit -m "stock screening tool"
git remote add origin https://github.com/your-username/stock-screening.git
git push -u origin main
```

`.env.local` は `.gitignore` 済みなのでpushされません。

### 3. Claude Code Routinesに登録

1. Claude Code（code.claude.com）で「Routines」を開く
2. `routines/morning.yml` の内容で新規Routineを作成（朝8:00）
3. 同様に `routines/afternoon.yml`（昼12:30）
4. 上記の環境変数を設定

### 4. ローカルでのテスト

```bash
cp .env.example .env.local   # 値を実際のものに編集
python3 -m venv .venv
.venv/bin/pip install yfinance pandas xlrd jpholiday requests

set -a; . ./.env.local; set +a   # 環境変数を読み込み

# テクニカルスクリーニング（全銘柄。数分かかります）
.venv/bin/python scripts/screener.py --out /tmp/screen.json

# 朝メール（hotは任意。省略するとSection1は空）
echo '[]' > /tmp/hot.json
.venv/bin/python scripts/mailer.py morning --screen /tmp/screen.json --hot /tmp/hot.json

# 昼メール
echo '[{"code":"7203","name":"トヨタ自動車","reason":"テスト"}]' > /tmp/aft.json
.venv/bin/python scripts/mailer.py afternoon --candidates /tmp/aft.json
```

## 注意事項

- 全銘柄の週足取得は数分かかります（yfinanceを150銘柄ずつ一括取得）。
- Routineの実行回数：Pro=5回/日、Max=15回/日（朝+昼で2回消費）。
- 投資判断はご自身の責任で行ってください。
