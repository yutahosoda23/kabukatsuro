"""
週足GCスクリーニング
条件:
  - 株価 < 2300円
  - SMA(13週) < SMA(26週)  ← GC未成立
  - 株価 > SMA(26週)        ← 26週線を上抜け済み
  - 乖離率 = (SMA26 - SMA13) / SMA26 < 5%  ← GC直前
"""

import yfinance as yf
import pandas as pd
import time
import json
from datetime import datetime

# 東証全銘柄コード（主要銘柄）を取得する
# JPX公式CSVから全銘柄を取得
def get_all_tickers() -> list[str]:
    import urllib.request
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    
    # JPX上場銘柄リスト（東証プライム・スタンダード・グロース）
    # J-Quants APIが使えない場合はcsv直接取得
    try:
        jpx_url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
        # xlsはpandasで読めないのでcsv版を使う
        # 代替: 既知の主要銘柄リストを使用
        pass
    except:
        pass
    
    # 東証プライム主要銘柄（時価総額上位・流動性高い銘柄を幅広くカバー）
    # 2300円以下に絞るので幅広く設定
    tickers = []
    # 1300〜9999のコード帯をカバー
    # 実際には jpx.co.jp のCSVを使うのがベストだが、
    # ここでは yfinance で動作確認できる主要銘柄を使用
    
    major_codes = [
        # 食品・飲料
        2502, 2503, 2587, 2802, 2914,
        # 化学・素材
        3407, 4004, 4005, 4183, 4188, 4208,
        # 医薬・医療
        4502, 4503, 4506, 4507, 4519, 4523, 4543, 4568,
        6869,
        # 電機・電子
        6301, 6326, 6361, 6367, 6376, 6471, 6473, 6479,
        6501, 6503, 6504, 6506, 6594, 6645, 6674, 6701,
        6702, 6703, 6724, 6752, 6753, 6758, 6762, 6770,
        6841, 6857, 6902, 6952, 6954, 6971, 6976,
        # 輸送機器
        7201, 7202, 7203, 7205, 7211, 7261, 7267, 7269,
        7270, 7272,
        # 精密・光学
        7731, 7733, 7735, 7751, 7752, 7762,
        # その他製造
        7951, 7952, 7974,
        # 商社
        8001, 8002, 8015, 8031, 8053, 8058,
        # 金融
        8301, 8304, 8306, 8308, 8309, 8316, 8331,
        8354, 8355, 8358, 8411,
        8601, 8604, 8628, 8630, 8697, 8725, 8750,
        # 不動産
        8801, 8802, 8830,
        # 通信・IT
        9432, 9433, 9434, 9437, 9613, 9984,
        # 小売
        2651, 2753, 2782, 2784, 2802, 3086, 3099,
        7453, 7514, 7522, 7532, 8233, 8252, 8267,
        # サービス・その他
        2413, 2433, 2489, 3289, 3769, 4307, 4324,
        4689, 4704, 4732, 4751, 4755, 4768,
        5019, 5020, 5101, 5108, 5201, 5214, 5232,
        5301, 5332, 5333, 5401, 5406, 5411, 5413,
        5471, 5541, 5631, 5714, 5801, 5802, 5803,
        6103, 6113, 6178, 6273, 6302,
        # 内需・インフラ
        9001, 9005, 9007, 9008, 9009, 9020, 9022,
        9062, 9064, 9101, 9104, 9107,
        9501, 9502, 9503,
    ]
    
    tickers = [f"{code}.T" for code in major_codes]
    return tickers


def calc_sma(series: pd.Series, period: int) -> float:
    """直近のSMAを計算"""
    if len(series) < period:
        return None
    return series.iloc[-period:].mean()


def screen_stocks(gap_threshold: float = 0.05) -> dict:
    """
    スクリーニング実行
    
    Returns:
        {
          "gc_candidates": [...],   # GC直前（2300円以下）
          "gc_over_2300": [...],    # GC直前（2300円超）
        }
    """
    tickers = get_all_tickers()
    
    gc_candidates = []   # 全条件OK（2300円以下）
    gc_over_2300 = []    # 2300円超のGC直前
    
    print(f"スクリーニング開始: {len(tickers)}銘柄")
    
    for i, ticker in enumerate(tickers):
        try:
            stock = yf.Ticker(ticker)
            # 週足データ取得（約1年分 = 52週以上確保）
            hist = stock.history(period="2y", interval="1wk")
            
            if hist.empty or len(hist) < 30:
                continue
            
            close = hist["Close"]
            current_price = close.iloc[-1]
            
            # SMA計算
            sma13 = calc_sma(close, 13)
            sma26 = calc_sma(close, 26)
            
            if sma13 is None or sma26 is None:
                continue
            if sma26 == 0:
                continue
            
            # 乖離率: (SMA26 - SMA13) / SMA26
            # SMA13 < SMA26 の状態なので正の値になる
            gap_ratio = (sma26 - sma13) / sma26
            
            # 条件チェック
            cond_not_gc = sma13 < sma26          # GC未成立
            cond_above_sma26 = current_price > sma26  # 株価 > SMA26
            cond_gap = gap_ratio < gap_threshold  # 乖離率 < 5%
            
            if cond_not_gc and cond_above_sma26 and cond_gap:
                info = stock.info
                name = info.get("longName") or info.get("shortName") or ticker
                code = ticker.replace(".T", "")
                
                entry = {
                    "code": code,
                    "name": name,
                    "price": round(current_price, 1),
                    "sma13": round(sma13, 1),
                    "sma26": round(sma26, 1),
                    "gap_ratio": round(gap_ratio * 100, 2),  # %表示
                    "chart_url": f"https://finance.yahoo.co.jp/quote/{code}.T/chart?frm=wkly&trm=6m&scl=stndrd&styl=cndl&evnts=volume&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
                }
                
                if current_price < 2300:
                    gc_candidates.append(entry)
                else:
                    gc_over_2300.append(entry)
            
            # API負荷軽減
            if i % 20 == 0:
                time.sleep(1)
                print(f"  {i}/{len(tickers)} 処理中...")
                
        except Exception as e:
            continue
    
    # 乖離率の低い順にソート（GCに近い順）
    gc_candidates.sort(key=lambda x: x["gap_ratio"])
    gc_over_2300.sort(key=lambda x: x["gap_ratio"])
    
    return {
        "gc_candidates": gc_candidates[:10],
        "gc_over_2300": gc_over_2300[:10],
        "screened_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
    }


if __name__ == "__main__":
    result = screen_stocks()
    print(json.dumps(result, ensure_ascii=False, indent=2))
