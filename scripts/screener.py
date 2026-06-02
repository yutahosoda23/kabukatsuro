"""
週足ゴールデンクロス(GC)直前スクリーニング

条件:
  - 株価 < 2300円
  - SMA(13週) < SMA(26週)            ← GC未成立
  - 株価 > SMA(26週)                  ← 26週線を上抜け済み
  - 乖離率 = (SMA26 - SMA13) / SMA26 < 5%  ← GC直前
  - 日次平均売買代金 >= 1億円          ← デイトレで売買できる流動性

出力(JSON):
  {
    "section2": [...],   # 全条件OK（株価 < 2300円）乖離率の低い順 TOP10
    "section3": [...],   # 「株価 < 2300円」だけ満たさない（2300円以上）TOP10
    "screened_at": "...",
    "universe_size": N
  }

銘柄ユニバースはJPX公式の「上場銘柄一覧(data_j.xls)」から
東証プライム/スタンダード/グロースの内国普通株を自動取得する。
"""

import argparse
import io
import json
import sys
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf

JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"

# data_j.xls の「市場・商品区分」のうち対象とする内国株式の市場
TARGET_MARKETS = {
    "プライム（内国株式）",
    "スタンダード（内国株式）",
    "グロース（内国株式）",
}

PRICE_CEILING = 2300            # 株価上限（円）
GAP_THRESHOLD = 0.05            # 乖離率しきい値（5%）
MIN_DAILY_TURNOVER = 100_000_000  # 日次平均売買代金の下限（円, 1億円）デイトレ流動性フィルタ
TOP_N = 10                      # 各セクションの最大件数
BATCH_SIZE = 150                # yfinance一括取得のバッチサイズ


def chart_url(code: str) -> str:
    return (
        f"https://finance.yahoo.co.jp/quote/{code}.T/chart"
        "?frm=wkly&trm=6m&scl=stndrd&styl=cndl&evnts=volume"
        "&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
    )


def get_jpx_universe() -> dict[str, str]:
    """JPX上場銘柄一覧から {コード(.Tなし): 銘柄名} を返す。"""
    resp = requests.get(JPX_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content), dtype={"コード": str})

    df = df[df["市場・商品区分"].isin(TARGET_MARKETS)]
    # 4桁の数値コードのみ（新規の英数字コードはyfinance非対応のため除外）
    df = df[df["コード"].str.fullmatch(r"\d{4}")]

    return dict(zip(df["コード"], df["銘柄名"]))


def is_trading_day(dt: datetime | None = None) -> bool:
    """平日かつ日本の祝日でなければ取引日とみなす（年末年始は祝日扱いされない点に注意）。"""
    dt = dt or datetime.now()
    if dt.weekday() >= 5:  # 土(5)・日(6)
        return False
    try:
        import jpholiday

        if jpholiday.is_holiday(dt.date()):
            return False
    except ImportError:
        # jpholiday未導入なら平日判定のみにフォールバック
        pass
    return True


def _weekly_field(data: pd.DataFrame, ticker: str, field: str) -> pd.Series | None:
    """yf.download の戻り値から指定銘柄の週足系列（Close/Volume等）を取り出す。"""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            s = data[ticker][field]
        else:
            s = data[field]
    except (KeyError, TypeError):
        return None
    return s.dropna()


def screen(price_ceiling: int = PRICE_CEILING, gap_threshold: float = GAP_THRESHOLD,
           min_turnover: float = MIN_DAILY_TURNOVER) -> dict:
    universe = get_jpx_universe()
    codes = list(universe.keys())
    tickers = [f"{c}.T" for c in codes]
    print(f"スクリーニング開始: {len(tickers)}銘柄", file=sys.stderr)

    section2 = []  # 全条件OK（< price_ceiling）
    section3 = []  # 価格以外OK（>= price_ceiling）

    for start in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[start:start + BATCH_SIZE]
        print(f"  {start}/{len(tickers)} 取得中...", file=sys.stderr)
        try:
            data = yf.download(
                batch, period="2y", interval="1wk",
                group_by="ticker", auto_adjust=True,
                progress=False, threads=True,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  バッチ取得失敗 ({start}): {e}", file=sys.stderr)
            continue

        for ticker in batch:
            close = _weekly_field(data, ticker, "Close")
            if close is None or len(close) < 26:
                continue

            price = float(close.iloc[-1])
            sma13 = float(close.iloc[-13:].mean())
            sma26 = float(close.iloc[-26:].mean())
            if sma26 == 0:
                continue

            gap_ratio = (sma26 - sma13) / sma26  # SMA13<SMA26 のとき正

            cond_not_gc = sma13 < sma26          # GC未成立
            cond_above_sma26 = price > sma26     # 26週線上抜け
            cond_gap = gap_ratio < gap_threshold  # 乖離率 < しきい値
            if not (cond_not_gc and cond_above_sma26 and cond_gap):
                continue

            # 流動性（デイトレ用）: 直近4週の平均週間出来高から日次平均売買代金を概算
            volume = _weekly_field(data, ticker, "Volume")
            if volume is None or len(volume) == 0:
                continue
            avg_daily_vol = float(volume.iloc[-4:].mean()) / 5.0  # 週間出来高→日次概算
            turnover = avg_daily_vol * price                     # 日次平均売買代金(円)
            if turnover < min_turnover:
                continue

            code = ticker[:-2]
            entry = {
                "code": code,
                "name": universe.get(code, code),
                "price": round(price, 1),
                "sma13": round(sma13, 1),
                "sma26": round(sma26, 1),
                "gap_ratio": round(gap_ratio * 100, 2),  # %表示
                "avg_vol_man": round(avg_daily_vol / 10000, 1),   # 日次平均出来高(万株)
                "turnover_oku": round(turnover / 1e8, 2),         # 日次平均売買代金(億円)
                "chart_url": chart_url(code),
            }
            (section2 if price < price_ceiling else section3).append(entry)

    section2.sort(key=lambda x: x["gap_ratio"])
    section3.sort(key=lambda x: x["gap_ratio"])

    return {
        "section2": section2[:TOP_N],
        "section3": section3[:TOP_N],
        "screened_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
        "universe_size": len(tickers),
    }


def main():
    parser = argparse.ArgumentParser(description="週足GC直前スクリーニング")
    parser.add_argument("--out", help="結果JSONの出力先パス（省略時は標準出力）")
    parser.add_argument("--check-day-only", action="store_true",
                        help="取引日判定のみ実行（休場日はSKIPを出力し終了コード10）")
    parser.add_argument("--force", action="store_true",
                        help="休場日でもスクリーニングを実行する")
    args = parser.parse_args()

    if not args.force and not is_trading_day():
        print("SKIP: 本日は取引日ではありません（土日・祝日）")
        sys.exit(10)

    if args.check_day_only:
        print("OK: 本日は取引日です")
        return

    result = screen()
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"結果を書き出しました → {args.out} "
              f"(section2={len(result['section2'])}, section3={len(result['section3'])})",
              file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
