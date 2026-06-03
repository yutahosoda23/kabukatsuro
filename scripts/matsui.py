"""
松井証券「デイトレ適正ランキング（寄付前）」を無料の公開ページから取得する。
APIキー不要。ローカルMac（ネット制限なし）での実行を前提とする。

データソース:
  https://finance.matsui.co.jp/ranking-day-trading-morning/index
  ページ内の静的HTMLテーブル（順位 / 銘柄名(コード/市場) / 現在値 / 出来高 /
  概算売買代金 / 株価変動率）をスクレイピングする。

「デイトレ適正」は値動きの大きさ（株価変動率）と流動性（出来高・売買代金）を
合わせた松井証券独自のランキング。朝メールのデイトレ予習用に上位を載せる。

使い方:
  python scripts/matsui.py --out /tmp/kabu_matsui.json
"""

import argparse
import html as htmllib
import json
import re
import sys

import requests

URL = "https://finance.matsui.co.jp/ranking-day-trading-morning/index"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA}
TOP_N = 10              # 各セクションに載せる件数
PRICE_CEILING = 15000   # 単価上限（円）。単元100株＝150万円以下で取引できる銘柄に限定
PRICE_CEILING_LOW = 2300  # 別セクション用の単価上限（円）。少額(単元23万円以下)で取引できる銘柄


def chart_url(code: str) -> str:
    return (
        f"https://finance.yahoo.co.jp/quote/{code}.T/chart"
        "?frm=dly&trm=3m&scl=stndrd&styl=cndl&evnts=volume"
        "&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
    )


def _cells(row_html: str) -> list[str]:
    cs = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)
    return [htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip())
            for c in cs]


def _fetch_all_rows() -> list[dict]:
    """ランキング全行を価格フィルタ無しで解析して返す（順位順）。失敗時は空リスト。"""
    try:
        r = requests.get(URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        tables = re.findall(r"<table.*?</table>", r.text, re.S)
        target = next(t for t in tables if "株価変動率" in t)
        rows = re.findall(r"<tr.*?</tr>", target, re.S)
    except Exception as e:  # noqa: BLE001
        print(f"  デイトレ適性ランキング取得失敗: {e}", file=sys.stderr)
        return []

    out: list[dict] = []
    for row in rows:
        cs = _cells(row)
        if not cs or not re.fullmatch(r"\d+", cs[0] or ""):  # ヘッダ・空行を除外
            continue

        namecell = cs[1] if len(cs) > 1 else ""
        # 末尾が「<コード> <市場>」 例: "キオクシアホールディングス 285A 東P"
        m = re.match(r"^(.*?)\s+([0-9]{3,4}[A-Z]?)\s+(東[PSG]|名|福|札[PSG]?|[^\s]+)\s*$",
                     namecell)
        if m:
            name, code, market = m.group(1), m.group(2), m.group(3)
        else:
            name, code, market = namecell, "", ""

        price_str = cs[2] if len(cs) > 2 else ""
        try:
            price_val = float(price_str.replace(",", ""))
        except ValueError:
            continue  # 価格が取れない行はスキップ

        joined = " ".join(cs)
        chg = re.search(r"\(([-+][\d.]+)%\)", joined)
        vol = re.search(r"出来高：([\d,]+)", joined)
        turnover = re.search(r"概算売買代金：([\d,]+)", joined)
        volat = re.search(r"株価変動率：([-+]?[\d.]+)%", joined)

        turnover_oku = ""
        if turnover:
            try:
                turnover_oku = round(int(turnover.group(1).replace(",", "")) / 1e8, 1)
            except ValueError:
                turnover_oku = ""

        out.append({
            "rank": int(cs[0]),
            "code": code,
            "name": name,
            "market": market,
            "price": price_str,
            "price_val": price_val,
            "chg_pct": chg.group(1) if chg else "",
            "volume": vol.group(1) if vol else "",
            "turnover_oku": turnover_oku,            # 概算売買代金（億円）
            "volatility_pct": volat.group(1) if volat else "",  # 株価変動率（デイトレ適性の核）
            "chart_url": chart_url(code) if code else "",
        })
    return out


def filter_ranking(rows: list[dict], limit: int, price_ceiling: int) -> list[dict]:
    """単価<=price_ceiling の銘柄を順位順に最大limit件返す（内部用price_valは除く）。"""
    out = []
    for r in rows:
        if r["price_val"] > price_ceiling:
            continue
        out.append({k: v for k, v in r.items() if k != "price_val"})
        if len(out) >= limit:
            break
    return out


def fetch_matsui_ranking(limit: int = TOP_N, price_ceiling: int = PRICE_CEILING) -> list[dict]:
    """単価<=price_ceiling のデイトレ適性ランキング上位を返す。失敗時は空リスト。"""
    return filter_ranking(_fetch_all_rows(), limit, price_ceiling)


def main():
    parser = argparse.ArgumentParser(description="デイトレ適性ランキング取得")
    parser.add_argument("--out", help="結果JSONの出力先パス（省略時は標準出力）")
    parser.add_argument("--limit", type=int, default=TOP_N, help="各セクションの件数")
    args = parser.parse_args()

    rows = _fetch_all_rows()
    result = {
        "matsui": filter_ranking(rows, args.limit, PRICE_CEILING),       # 単価<=15,000円（150万円以下）
        "matsui_2300": filter_ranking(rows, args.limit, PRICE_CEILING_LOW),  # 単価<=2,300円
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"デイトレ適性ランキング 150万円以下{len(result['matsui'])}件 / "
              f"2300円以下{len(result['matsui_2300'])}件 → {args.out}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
