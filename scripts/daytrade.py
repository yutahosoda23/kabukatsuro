"""
デイトレ予習「お祭り銘柄」スクリーニング（ある相場本の手法を実装）

本の手法:
  - 値上がり率上位・売買高(出来高)上位の中から「強い上昇エネルギー」を持つ銘柄を品定め
  - 日足/分足で移動平均線を上抜けていれば翌日リストに加える
  - 特に材料も無いのに急騰＋出来高急増＝「仕手」っぽい動き → ターゲット
  - IPOホヤホヤ・材料株（上方修正/分割等）も対象
  - 毎日ランキングを見て「常連の記憶」「上位常連の急落＝リバウンド期待」「連動銘柄」を掴む

このスクリプトは上記をデータで近似し、朝メールSection1用のJSONを出力する。
日次ランキングは data/ranking_history.jsonl に蓄積し、常連/リバウンド/連動の分析に使う。

使い方:
  python scripts/daytrade.py --out /tmp/kabu_matsuri.json
"""

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime

import pandas as pd

from catalysts import fetch_kabutan_good_news, fetch_yahoo_ranking, chart_url

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(REPO, "data", "ranking_history.jsonl")

TOP_RANK = 30        # 各ランキングから拾う上位数
HISTORY_DAYS = 20    # 履歴分析で遡る日数
REGULAR_MIN_DAYS = 5  # この日数以上ランクインしていれば「常連」


def _to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").replace("+", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def load_candidates() -> tuple[dict, list, list]:
    """値上がり率・出来高ランキングを取得し、候補(コード→情報)とランキング順コード列を返す。"""
    up = fetch_yahoo_ranking("up", limit=TOP_RANK)
    vol = fetch_yahoo_ranking("volume", limit=TOP_RANK)

    cand: dict[str, dict] = {}
    for r, it in enumerate(up, 1):
        c = cand.setdefault(it["code"], {"code": it["code"], "name": it["name"], "price": it["price"]})
        c["up_rank"] = r
        c["chg_pct"] = _to_float(it["pct"])
    for r, it in enumerate(vol, 1):
        c = cand.setdefault(it["code"], {"code": it["code"], "name": it["name"], "price": it["price"]})
        c["vol_rank"] = r
        c.setdefault("chg_pct", _to_float(it["pct"]))

    return cand, [x["code"] for x in up], [x["code"] for x in vol]


def add_technicals(cand: dict) -> pd.DataFrame:
    """候補の日足を取得し、移動平均上抜け・出来高急増・IPO判定を付与。日足終値DataFrameを返す。"""
    import yfinance as yf

    tickers = [f"{c}.T" for c in cand]
    closes = {}
    try:
        data = yf.download(tickers, period="4mo", interval="1d",
                           group_by="ticker", auto_adjust=True, progress=False, threads=True)
    except Exception:  # noqa: BLE001
        data = None

    for code in list(cand):
        info = cand[code]
        try:
            df = data[f"{code}.T"] if data is not None and len(tickers) > 1 else data
            close = df["Close"].dropna()
            vol = df["Volume"].dropna()
        except Exception:  # noqa: BLE001
            continue
        if len(close) < 6:
            continue

        closes[code] = close
        price = float(close.iloc[-1])
        ma5 = float(close.iloc[-5:].mean())
        ma25 = float(close.iloc[-25:].mean()) if len(close) >= 25 else None
        # 移動平均(25日)上抜け: 当日終値が25MA超、かつ前日は25MA以下＝当日ブレイク
        info["above_ma25"] = bool(ma25 and price > ma25)
        if ma25 and len(close) >= 26:
            prev = float(close.iloc[-2])
            prev_ma25 = float(close.iloc[-26:-1].mean())
            info["cross_up_ma25"] = bool(prev <= prev_ma25 and price > ma25)
        else:
            info["cross_up_ma25"] = False
        info["above_ma5"] = bool(price > ma5)
        # 出来高急増: 当日出来高 / 直近25日平均
        if len(vol) >= 6:
            avg = float(vol.iloc[-25:-1].mean()) if len(vol) >= 26 else float(vol.iloc[:-1].mean())
            info["vol_ratio"] = round(float(vol.iloc[-1]) / avg, 1) if avg else None
        # IPOホヤホヤ: 上場後の営業日が少ない
        info["ipo_fresh"] = len(close) < 40

    return pd.DataFrame({c: s for c, s in closes.items()})


def update_history(up_codes: list, vol_codes: list) -> list[dict]:
    """本日のランキングを履歴に追記し、直近HISTORY_DAYS日分を返す。"""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    hist = []
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            hist = [json.loads(line) for line in f if line.strip()]

    if not any(h.get("date") == today for h in hist):
        hist.append({"date": today, "up": up_codes[:TOP_RANK], "vol": vol_codes[:TOP_RANK]})
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            for h in hist:
                f.write(json.dumps(h, ensure_ascii=False) + "\n")

    return hist[-HISTORY_DAYS:]


def analyze_history(hist: list[dict], today_codes: set) -> tuple[Counter, set]:
    """常連カウント(過去の出現日数)と、急落リバウンド候補(常連だが本日圏外)を返す。"""
    prior = hist[:-1] if hist else []
    appear = Counter()
    for h in prior:
        for c in set(h.get("up", []) + h.get("vol", [])):
            appear[c] += 1
    rebound = {c for c, n in appear.items() if n >= REGULAR_MIN_DAYS and c not in today_codes}
    return appear, rebound


def find_linked(close_df: pd.DataFrame, codes: list, threshold: float = 0.85) -> dict:
    """日足リターンの相関から連動銘柄ペアを抽出（codeごとに連動先コード集合）。"""
    linked: dict[str, set] = {c: set() for c in codes}
    cols = [c for c in codes if c in close_df.columns]
    if len(cols) < 2:
        return linked
    rets = close_df[cols].pct_change().dropna()
    if len(rets) < 10:
        return linked
    corr = rets.corr()
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            if corr.loc[a, b] >= threshold:
                linked[a].add(b)
                linked[b].add(a)
    return linked


def build(cand: dict, kabutan: dict, appear: Counter, rebound: set, linked: dict) -> list[dict]:
    """各候補にスコアと理由を付け、上位10件を返す。"""
    rows = []
    for code, c in cand.items():
        chg = c.get("chg_pct") or 0
        vr = c.get("vol_ratio")
        material = kabutan.get(code)
        # 仕手っぽさ: 出来高急増＋大きく上昇＋材料なし
        shite = bool(vr and vr >= 2 and chg >= 8 and not material)

        score = 0.0
        score += min(chg, 30) * 1.0                      # 上昇エネルギー
        score += (vr or 0) * 3.0                          # 出来高急増
        score += 12 if c.get("cross_up_ma25") else (6 if c.get("above_ma25") else 0)
        score += 4 if c.get("above_ma5") else 0
        score += 8 if material else 0                     # 材料株
        score += 6 if shite else 0                        # 仕手っぽい強い動き
        score += 5 if c.get("ipo_fresh") else 0           # IPOホヤホヤ
        score += min(appear.get(code, 0), 10) * 0.5       # 常連度

        tags = []
        if c.get("up_rank"):
            tags.append(f"値上がり率{c['up_rank']}位（{chg:+.1f}%）")
        if c.get("vol_rank"):
            tags.append(f"出来高{c['vol_rank']}位")
        if vr and vr >= 2:
            tags.append(f"出来高急増(平均比{vr}倍)")
        if c.get("cross_up_ma25"):
            tags.append("⚡25日線を当日上抜け")
        elif c.get("above_ma25"):
            tags.append("25日線の上")
        if material:
            tags.append(f"材料: {material}")
        if shite:
            tags.append("🎯仕手っぽい急騰(材料なし)")
        if c.get("ipo_fresh"):
            tags.append("IPOホヤホヤ")
        if appear.get(code, 0) >= REGULAR_MIN_DAYS:
            tags.append(f"ランキング常連(直近{appear[code]}日)")
        if linked.get(code):
            tags.append("連動: " + "・".join(sorted(linked[code])[:3]))

        rows.append({
            "code": code,
            "name": c.get("name", code),
            "price": c.get("price", ""),
            "reason": " / ".join(tags) if tags else "ランキング上位",
            "chart_url": chart_url(code),
            "_score": score,
        })

    rows.sort(key=lambda x: x["_score"], reverse=True)
    out = rows[:10]
    for r in out:
        r.pop("_score", None)
    return out


def build_rebound(cand_codes: set, rebound: set, hist: list[dict]) -> list[dict]:
    """急落リバウンド候補（常連だが本日圏外）を別枠で返す。"""
    if not rebound:
        return []
    # 直近で出現した日数の多い順
    appear = Counter()
    for h in hist[:-1] if hist else []:
        for c in set(h.get("up", []) + h.get("vol", [])):
            if c in rebound:
                appear[c] += 1
    out = []
    for code, n in appear.most_common(5):
        out.append({
            "code": code, "name": code, "price": "",
            "reason": f"ランキング常連だが本日は圏外（直近{n}日上位）→ リバウンド期待",
            "chart_url": chart_url(code),
        })
    return out


def main():
    parser = argparse.ArgumentParser(description="デイトレ予習お祭り銘柄スクリーニング")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    cand, up_codes, vol_codes = load_candidates()
    today_codes = set(up_codes) | set(vol_codes)

    close_df = add_technicals(cand)
    kabutan = {d["code"]: d["reason"] for d in fetch_kabutan_good_news()}
    hist = update_history(up_codes, vol_codes)
    appear, rebound = analyze_history(hist, today_codes)
    linked = find_linked(close_df, list(cand))

    matsuri = build(cand, kabutan, appear, rebound, linked)
    rebound_list = build_rebound(today_codes, rebound, hist)

    payload = {"matsuri": matsuri, "rebound": rebound_list,
               "generated_at": datetime.now().strftime("%Y/%m/%d %H:%M")}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"お祭り銘柄 {len(matsuri)}件 / リバウンド候補 {len(rebound_list)}件 → {args.out}")


if __name__ == "__main__":
    main()
