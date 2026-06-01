# stock-screening

デイトレ向け株スクリーニング自動メール通知ツール。
Claude Code Routinesで毎日自動実行。PCがオフラインでも動作。

## 構成

```
stock-screening/
├── scripts/
│   ├── screener.py        # テクニカルスクリーニング（yfinance）
│   ├── morning_mail.py    # 朝8時メール送信
│   └── afternoon_mail.py  # 12:30メール送信
├── routines/
│   ├── morning.yml        # Claude Code Routines設定（朝）
│   └── afternoon.yml      # Claude Code Routines設定（昼）
├── .env.example           # 環境変数テンプレート
└── README.md
```

## メール内容

### 朝8時メール
- 📰 Section 1: 本日の好材料銘柄 TOP10（Claude APIでウェブ検索）
- 📈 Section 2: 週足GC直前ランキング TOP10（乖離率低い順）
- 💡 Section 3: GC直前（株価2300円超）参考リスト TOP10

### 12:30メール
- 📈 午後から上昇期待の銘柄（現在株価・前日比・出来高・コメント付き）

各銘柄名はYahooファイナンス週足チャートへのリンク付き。

## スクリーニング条件（Section 2・3）

- `SMA(13週) < SMA(26週)` → GC未成立
- `株価 > SMA(26週)` → 株価は26週線を上抜け済み
- `乖離率 = (SMA26 - SMA13) / SMA26 < 5%` → GC直前

## セットアップ

### 1. 環境変数を設定

Claude Code Routinesの環境変数に以下を設定：

| 変数名 | 内容 |
|--------|------|
| `ANTHROPIC_API_KEY` | AnthropicのAPIキー |
| `GMAIL_USER` | 送信元Gmailアドレス |
| `GMAIL_APP_PASSWORD` | Googleアプリパスワード |
| `TO_EMAIL` | 送信先メールアドレス |

**Googleアプリパスワード取得手順：**
1. https://myaccount.google.com/apppasswords にアクセス
2. 「アプリを選択」→「メール」、「デバイス」→「その他」
3. 生成された16文字のパスワードを `GMAIL_APP_PASSWORD` に設定

### 2. GitHubリポジトリにpush

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/your-username/stock-screening.git
git push -u origin main
```

### 3. Claude Code Routinesに登録

Claude Code（code.claude.com）で：
1. 「Routines」タブを開く
2. 「New Routine」→ `routines/morning.yml` の内容を設定
3. 同様に `routines/afternoon.yml` を設定
4. 環境変数を設定

### 4. ローカルでのテスト

```bash
cp .env.example .env.local
# .env.localを編集して実際の値を入力

# 環境変数を読み込んでテスト
export $(cat .env.local | grep -v ^# | xargs)
pip install yfinance anthropic
python scripts/morning_mail.py
python scripts/afternoon_mail.py
```

## 注意事項

- yfinanceのデータ取得には数分かかる場合があります
- Claude Routinesの実行回数：Pro=5回/日、Max=15回/日（朝+昼で2回消費）
- 土日・祝日も実行されるため、必要に応じてスクリプト内で営業日チェックを追加してください
