# kabukatsuro — デイトレ向け株スクリーニング自動メール

毎営業日の朝8:00と昼12:30に、候補銘柄リストをGmailで自動送信するツール。
**APIキー不要**（市場データは yfinance、好材料は Yahoo/kabutan の無料公開ページから取得）。
Mac の `launchd` でローカル実行する。

## 構成

```
.
├── scripts/
│   ├── screener.py        # 週足GCスクリーニング（JPX全銘柄 × yfinance）
│   ├── daytrade.py        # デイトレ予習「お祭り銘柄」＋履歴追跡（朝Section1用）
│   ├── catalysts.py       # 午後候補をスクレイピングで生成（APIキー不要）
│   ├── mailer.py          # メール整形・Gmail送信（朝/昼 兼用）
│   ├── run_morning.sh     # 朝8:00の実行スクリプト（launchdから呼ばれる）
│   └── run_afternoon.sh   # 昼12:30の実行スクリプト（同上）
├── data/                  # ランキング履歴（ranking_history.jsonl、gitignore）
├── routines/              # （非推奨）クラウドRoutine用設定。下記「経緯」参照
├── .env.example
└── README.md
```

launchd 設定は `~/Library/LaunchAgents/com.kabukatsuro.{morning,afternoon}.plist`。

## メール内容

### 朝8:00メール
- 🌅 今朝の市場のまとめ（地合い・主要指数・注目イベントを寄り前に手早く把握）
  ※ WebSearchが必要なため、市場まとめ付きで送るのは手動の `ohayou-stock-mail` スキル。
     launchd自動実行では省略される（`mailer.py` の `--market` は任意）。
- 📈 週足GC直前ランキング TOP10（条件を全て満たす銘柄を乖離率の低い順）
- 💡 GC直前（株価2300円超）参考リスト TOP10（「株価2300円未満」だけ満たさない銘柄）
- 🔥 お祭り銘柄 TOP10（デイトレ予習・最下部）— `daytrade.py`

履歴が貯まると お祭り銘柄 の後に「🔄 急落リバウンド候補」が出ることがある。
「おはよう」と話しかけると市場まとめ付きの朝メールを送る（`.claude/skills/ohayou-stock-mail`）。

#### お祭り銘柄（Section 1）の手法 — ある相場本の夜の予習法を実装
- 値上がり率上位 ∪ 出来高（売買高）上位を母集団にする
- 日足の **25日移動平均線を上抜け**（特に当日上抜け）を重視
- **出来高急増**（直近25日平均比）を検出
- **材料の有無**を kabutan適時開示と照合。材料が無いのに急騰＋出来高急増は **「仕手」っぽい動き** としてフラグ
- **IPOホヤホヤ**（上場後の営業日が少ない）を検出
- ランキングを毎日 `data/ranking_history.jsonl` に保存し、**常連銘柄**・**急落リバウンド候補**（常連が本日圏外）・**連動銘柄**（日足リターンの相関）を分析
- これらをスコア化して上位10件。寄り前の「強い上昇エネルギー」を持つ銘柄を品定めする

### 昼12:30メール
- 📈 午後から上昇期待の銘柄 TOP10（前場の値上がり率・出来高から抽出、現在株価・前日比・出来高付き）
  ※ 午後はテクニカルの Section 2・3 は送りません。

各銘柄名はYahooファイナンスの週足チャートへのリンク付き。

## スクリーニング条件（Section 2・3）

- `株価 < 2300円`（Section 3 はこの条件だけ満たさない銘柄）
- `SMA(13週) < SMA(26週)` → GC未成立
- `株価 > SMA(26週)` → 株価は26週線を上抜け済み
- `乖離率 = (SMA26 - SMA13) / SMA26 < 5%` → GC直前（この値が小さい順にランキング）

銘柄ユニバースは JPX「上場銘柄一覧（data_j.xls）」から東証プライム/スタンダード/グロースの
内国普通株（約3,500銘柄）を毎回取得する。

## 営業日判定

土日および日本の祝日（`jpholiday`）は自動でスキップ（`screener.py` が終了コード10を返す）。

## セットアップ

```bash
cd kabukatsuro
python3 -m venv .venv
.venv/bin/pip install yfinance pandas xlrd jpholiday requests

cp .env.example .env.local   # GMAIL_USER / GMAIL_APP_PASSWORD / TO_EMAIL を実値に編集
```

Googleアプリパスワード（16桁・スペース無しで入力）: https://myaccount.google.com/apppasswords

### launchd への登録

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kabukatsuro.morning.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kabukatsuro.afternoon.plist
launchctl list | grep kabukatsuro   # 登録確認
```

手動実行・テスト:

```bash
bash scripts/run_morning.sh     # 朝メール（全銘柄スクリーニングで1〜3分）
bash scripts/run_afternoon.sh   # 昼メール
# 即時発火: launchctl kickstart gui/$(id -u)/com.kabukatsuro.morning
```

ログは `logs/morning.log` / `logs/afternoon.log`。

## 注意事項

- **Macが起動中（スリープ可）であること**が前提。スリープ中に時刻を過ぎても次回起動時に実行されるが、
  シャットダウン中の時刻はスキップされる。
- スクレイピング対象（Yahoo/kabutan）のページ構造が変わると `catalysts.py` の修正が必要。
- 「PTS夜間の買付未成率ランキング」は無料の公開ソースが存在しない（証券会社のログインが必要）ため未対応。
  代替として掲示板投稿数（注目度）を Section 1 に利用している。
- 投資判断はご自身の責任で。

## 経緯（クラウドRoutineを使わない理由）

当初はClaude Code Routines（クラウド実行）を検討したが、サンドボックスの外部ネットワークが
制限されており、JPX/yfinance（市場データ）も SMTP送信もブロックされ、本ツールの中核機能が動作しなかった。
そのため、ネットワーク制限のないローカルMac（launchd）での実行に切り替えた。
`routines/*.yml` はその名残（非推奨）。
