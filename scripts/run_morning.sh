#!/bin/bash
# 朝8:00 ローカル実行スクリプト（launchdから呼ばれる）
# Section1(好材料/API) + Section2/3(テクニカル/yfinance) を生成しメール送信
set -uo pipefail

REPO="/Users/yuthsd/kabukatsuro"
PY="$REPO/.venv/bin/python"
cd "$REPO" || exit 1

# 認証情報を読み込み
set -a; . "$REPO/.env.local"; set +a

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 朝の実行開始 ====="

# 1) テクニカルスクリーニング（休場日なら終了コード10でSKIP）
"$PY" scripts/screener.py --out /tmp/kabu_screen.json
rc=$?
if [ $rc -eq 10 ]; then
  echo "休場日のためスキップしました。"
  exit 0
elif [ $rc -ne 0 ]; then
  echo "screener.py が異常終了 (rc=$rc)。処理を中止します。"
  exit $rc
fi

# 2) お祭り銘柄（デイトレ予習：値上がり率/出来高/移動平均上抜け/仕手/IPO/履歴）
"$PY" scripts/daytrade.py --out /tmp/kabu_matsuri.json || echo "お祭り銘柄の生成に失敗（Section1は空で続行）"

# 2.5) 松井証券デイトレ適正ランキング（寄付前・スクレイピング）
"$PY" scripts/matsui.py --out /tmp/kabu_matsui.json || echo "松井ランキングの取得に失敗（空で続行）"

# 3) メール送信
"$PY" scripts/mailer.py morning --screen /tmp/kabu_screen.json --matsuri /tmp/kabu_matsuri.json --matsui /tmp/kabu_matsui.json

echo "===== 朝の実行完了 ====="
