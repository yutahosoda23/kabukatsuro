#!/bin/bash
# 昼12:30 ローカル実行スクリプト（launchdから呼ばれる）
# 午後から上がりそうな銘柄リスト（Section2/3は送らない）
set -uo pipefail

REPO="/Users/yuthsd/Desktop/kabukatsuro"
PY="$REPO/.venv/bin/python"
cd "$REPO" || exit 1

set -a; . "$REPO/.env.local"; set +a

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 午後の実行開始 ====="

# 1) 取引日判定（休場日なら終了コード10でSKIP）
"$PY" scripts/screener.py --check-day-only
rc=$?
if [ $rc -eq 10 ]; then
  echo "休場日のためスキップしました。"
  exit 0
elif [ $rc -ne 0 ]; then
  echo "取引日判定が異常終了 (rc=$rc)。処理を中止します。"
  exit $rc
fi

# 2) 午後候補銘柄（Anthropic API + web_search）
"$PY" scripts/catalysts.py afternoon --out /tmp/kabu_afternoon.json || {
  echo "午後候補の取得に失敗。メールは送りません。"
  exit 1
}

# 3) メール送信
"$PY" scripts/mailer.py afternoon --candidates /tmp/kabu_afternoon.json

echo "===== 午後の実行完了 ====="
