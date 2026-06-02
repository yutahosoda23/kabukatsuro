"""
好材料銘柄 / 午後候補銘柄を「無料の公開ページのスクレイピング」で生成する。
APIキー不要。ローカルMac（ネット制限なし）での実行を前提とする。

データソース:
  - Yahoo!ファイナンス ランキング（値上がり率 / 出来高 / 掲示板投稿数）
      __PRELOADED_STATE__.mainRankingList.results を解析
  - kabutan 適時開示一覧（上方修正・自社株買い等の好材料を理由付きで取得）

使い方:
  朝Section1: python scripts/catalysts.py morning  --out /tmp/kabu_hot.json
  午後候補  : python scripts/catalysts.py afternoon --out /tmp/kabu_afternoon.json

注意: 「PTS夜間の買付未成率ランキング」は無料の公開ソースが無く（証券会社のログインが必要）、
      本スクリプトには含めていない。代替として掲示板投稿数（注目度）を利用する。
"""

import argparse
import html as htmllib
import json
import re
import sys

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA}

# 好材料とみなす適時開示タイトルのキーワード
GOOD_KEYWORDS = [
    "上方修正", "増配", "復配", "最高益", "過去最高", "黒字転換", "営業利益", "経常利益",
    "自己株式の取得", "自社株", "株式分割", "業務提携", "資本提携", "資本業務提携",
    "受注", "新製品", "新サービス", "買収", "子会社化", "ＴＯＢ", "TOB", "MBO",
    "増額", "好調", "進捗", "承認", "認可", "提携",
]


def chart_url(code: str) -> str:
    return (
        f"https://finance.yahoo.co.jp/quote/{code}.T/chart"
        "?frm=wkly&trm=6m&scl=stndrd&styl=cndl&evnts=volume"
        "&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
    )


def fetch_yahoo_ranking(kind: str, limit: int = 30) -> list[dict]:
    """Yahoo!ファイナンスのランキングを取得。kind: up / volume / bbs など。"""
    url = f"https://finance.yahoo.co.jp/stocks/ranking/{kind}?market=tokyoAll&term=daily"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        m = re.search(r'__PRELOADED_STATE__\s*=\s*(\{.*\})', r.text, re.S)
        data = json.loads(m.group(1))
        results = data["mainRankingList"]["results"]
    except Exception as e:  # noqa: BLE001
        print(f"  Yahooランキング取得失敗 ({kind}): {e}", file=sys.stderr)
        return []

    out = []
    for it in results[:limit]:
        code = str(it.get("stockCode", ""))
        if not re.fullmatch(r"\d{4}", code):
            continue
        # rankingResult の中で、騰落率/出来高を持つ非nullのサブdictを採用
        # （up は changePriceRate、volume は volume サブdictに値が入る）
        sub = {}
        for v in (it.get("rankingResult") or {}).values():
            if isinstance(v, dict) and ("changePriceRate" in v or "volume" in v):
                sub = v
                break
        out.append({
            "code": code,
            "name": it.get("stockName", code),
            "price": it.get("savePrice", ""),
            "pct": sub.get("changePriceRate", ""),   # 騰落率 例 "+32.69"
            "vol": sub.get("volume", ""),             # 出来高 例 "51,947,400"
            "rank": it.get("rank", ""),
        })
    return out


def fetch_kabutan_good_news(limit: int = 40) -> list[dict]:
    """kabutan適時開示から好材料っぽい開示を {code,name,reason} で返す（新しい順・コード重複排除）。"""
    try:
        r = requests.get("https://kabutan.jp/disclosures/", headers=HEADERS, timeout=20)
        r.raise_for_status()
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S)
    except Exception as e:  # noqa: BLE001
        print(f"  kabutan適時開示の取得失敗: {e}", file=sys.stderr)
        return []

    seen, out = set(), []
    for row in rows:
        cm = re.search(r"code=(\d{4})", row)
        if not cm:
            continue
        code = cm.group(1)
        if code == "0000" or code in seen:
            continue
        texts = [htmllib.unescape(re.sub("<[^>]+>", "", t)).strip()
                 for t in re.findall(r">([^<]{2,})<", row)]
        texts = [t for t in texts if t and not re.fullmatch(r"[\d:/\s]+", t)]
        if not texts:
            continue
        name = texts[0]
        title = next((t for t in texts if any(k in t for k in GOOD_KEYWORDS)), None)
        if not title:
            continue
        seen.add(code)
        out.append({"code": code, "name": name, "reason": title[:60]})
        if len(out) >= limit:
            break
    return out


def enrich_price(items: list[dict]) -> None:
    """price未設定の銘柄にyfinanceで現在株価を付加（少数前提）。"""
    try:
        import yfinance as yf
    except ImportError:
        return
    for s in items:
        if s.get("price"):
            continue
        try:
            hist = yf.Ticker(f"{s['code']}.T").history(period="2d", interval="1d")
            if len(hist):
                s["price"] = round(float(hist["Close"].iloc[-1]), 1)
        except Exception:  # noqa: BLE001
            s["price"] = ""


def build_morning() -> list[dict]:
    """好材料(適時開示) を主軸に、値上がり率・出来高・投稿数で10件まで補完。"""
    picks, seen = [], set()

    def add(code, name, price, reason):
        if code in seen or len(picks) >= 10:
            return
        seen.add(code)
        picks.append({"code": code, "name": name, "price": price,
                      "reason": reason, "chart_url": chart_url(code)})

    # 1) 好材料の適時開示（理由付き）
    for d in fetch_kabutan_good_news():
        add(d["code"], d["name"], "", f"好材料: {d['reason']}")

    # 2) 値上がり率上位（動意）
    for it in fetch_yahoo_ranking("up"):
        add(it["code"], it["name"], it["price"], f"本日値上がり率{it['rank']}位（{it['pct']}%）")

    # 3) 出来高上位（売買代金・関心）
    for it in fetch_yahoo_ranking("volume"):
        add(it["code"], it["name"], it["price"], f"本日出来高{it['rank']}位（{it['vol']}株）")

    # 4) 掲示板投稿数（注目度）
    for it in fetch_yahoo_ranking("bbs"):
        add(it["code"], it["name"], it["price"], f"掲示板投稿数{it['rank']}位（注目度）")

    enrich_price(picks)
    return picks[:10]


def build_afternoon() -> list[dict]:
    """前場の値上がり率・出来高の動意から午後の継続/反発期待銘柄を10件。"""
    picks, seen = [], set()

    def add(code, name, reason):
        if code in seen or len(picks) >= 10:
            return
        seen.add(code)
        picks.append({"code": code, "name": name, "reason": reason, "chart_url": chart_url(code)})

    up = fetch_yahoo_ranking("up")
    vol = fetch_yahoo_ranking("volume")
    # 値上がり率と出来高の両ランキングを交互に拾って動意の強い銘柄を集める
    for i in range(max(len(up), len(vol))):
        if i < len(up):
            add(up[i]["code"], up[i]["name"],
                f"前場値上がり率{up[i]['rank']}位（{up[i]['pct']}%）。午後の上昇継続に期待")
        if i < len(vol):
            add(vol[i]["code"], vol[i]["name"],
                f"前場出来高{vol[i]['rank']}位（{vol[i]['vol']}株）。売買活発で午後の動意に期待")
    return picks[:10]


def main():
    parser = argparse.ArgumentParser(description="好材料/午後候補をスクレイピングで生成（APIキー不要）")
    parser.add_argument("mode", choices=["morning", "afternoon"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    stocks = build_morning() if args.mode == "morning" else build_afternoon()

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)
    print(f"{args.mode}: {len(stocks)}銘柄を書き出しました → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
