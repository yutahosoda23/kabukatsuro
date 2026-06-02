"""
メール整形・送信スクリプト（Gmail SMTP）

Routineエージェントが用意したJSONを読み込んでHTMLメールを組み立て送信する。
Web検索（好材料・午後候補）はRoutineエージェント側が行い、結果をJSONで渡す。

使い方:
  朝8:00:
    python scripts/mailer.py morning --screen screen.json --hot hot.json
  昼12:30:
    python scripts/mailer.py afternoon --candidates afternoon.json

JSON形式:
  screen.json    : screener.py の出力（section2 / section3 / screened_at / universe_size）
  hot.json       : [{"code","name","price","reason"}, ...]   好材料銘柄
  afternoon.json : [{"code","name","reason"}, ...]           午後候補（株価等はyfinanceで付加）

環境変数:
  GMAIL_USER          送信元Gmailアドレス
  GMAIL_APP_PASSWORD  Googleアプリパスワード
  TO_EMAIL            送信先（カンマ区切りで複数指定可。未設定ならGMAIL_USER宛）
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def chart_url(code: str) -> str:
    return (
        f"https://finance.yahoo.co.jp/quote/{code}.T/chart"
        "?frm=wkly&trm=6m&scl=stndrd&styl=cndl&evnts=volume"
        "&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
    )


def load_json(path: str | None, default):
    if not path:
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"警告: {path} を読めませんでした ({e})。空として扱います。", file=sys.stderr)
        return default


# ---------------------------------------------------------------- HTML 部品

def _row(rank: int, code: str, name: str, price_html: str, extra: str = "") -> str:
    url = chart_url(code)
    return f"""
    <tr style="border-bottom:1px solid #eee;">
      <td style="padding:10px 6px;color:#999;font-size:13px;vertical-align:top;">{rank}</td>
      <td style="padding:10px 6px;vertical-align:top;">
        <a href="{url}" style="font-weight:bold;color:#1a56db;text-decoration:none;font-size:15px;">{code} {name}</a>
        {extra}
      </td>
      <td style="padding:10px 6px;text-align:right;vertical-align:top;white-space:nowrap;">{price_html}</td>
    </tr>"""


def _section(title: str, emoji: str, description: str, rows: str, accent: str, price_head: str) -> str:
    if not rows:
        rows = ('<tr><td colspan="3" style="padding:14px 6px;color:#aaa;font-size:13px;">'
                '該当銘柄がありませんでした。</td></tr>')
    return f"""
    <div style="margin-bottom:32px;">
      <h2 style="font-size:16px;color:#111;border-left:4px solid {accent};padding-left:10px;margin-bottom:4px;">{emoji} {title}</h2>
      <p style="color:#888;font-size:12px;margin:0 0 10px 0;">{description}</p>
      <table style="width:100%;border-collapse:collapse;font-family:sans-serif;">
        <thead>
          <tr style="background:#f5f5f5;">
            <th style="padding:8px 6px;text-align:left;font-size:12px;color:#888;width:30px;">#</th>
            <th style="padding:8px 6px;text-align:left;font-size:12px;color:#888;">銘柄</th>
            <th style="padding:8px 6px;text-align:right;font-size:12px;color:#888;">{price_head}</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _market_section(market: dict) -> str:
    """今朝の市場のまとめ（地合い・主要指数・注目イベント）を寄り前に手早く把握する用。"""
    if not market:
        return ""
    color = {"up": "#e53e3e", "down": "#2b6cb0", "flat": "#666"}
    arrow = {"up": "▲", "down": "▼", "flat": "－"}

    cells = []
    for s in market.get("stats", []):
        d = s.get("dir", "flat")
        c = color.get(d, "#666")
        a = arrow.get(d, "")
        chg = s.get("chg", "")
        chg_html = (f'<span style="font-size:12px;color:{c};font-weight:bold;"> {a} {chg}</span>'
                    if chg else "")
        cells.append(
            '<td style="padding:8px 10px;border:1px solid #eee;width:50%;vertical-align:top;">'
            f'<div style="font-size:11px;color:#888;">{s.get("label","")}</div>'
            f'<div style="font-size:16px;font-weight:bold;color:#111;">{s.get("value","-")}{chg_html}</div>'
            '</td>')
    grid_rows = ""
    for i in range(0, len(cells), 2):
        pair = cells[i:i + 2]
        if len(pair) == 1:
            pair.append('<td style="border:1px solid #eee;"></td>')
        grid_rows += f"<tr>{pair[0]}{pair[1]}</tr>"
    grid = (f'<table style="width:100%;border-collapse:collapse;margin:8px 0;">{grid_rows}</table>'
            if cells else "")

    sentiment = market.get("sentiment", "")
    sentiment_html = (f'<p style="font-size:14px;color:#222;line-height:1.6;margin:0 0 6px 0;'
                      f'background:#fff8e1;border-left:3px solid #f6c343;padding:8px 12px;">{sentiment}</p>'
                      if sentiment else "")

    watch = market.get("watch", [])
    watch_html = ""
    if watch:
        items = "".join(f'<li style="margin-bottom:3px;">{w}</li>' for w in watch)
        watch_html = ('<div style="margin-top:10px;font-size:12px;color:#888;font-weight:bold;">📌 今日の注目</div>'
                      f'<ul style="margin:4px 0 0 0;padding-left:18px;font-size:13px;color:#333;line-height:1.6;">{items}</ul>')

    as_of = market.get("as_of", "")
    return f"""
    <div style="margin-bottom:32px;">
      <h2 style="font-size:16px;color:#111;border-left:4px solid #b45309;padding-left:10px;margin-bottom:4px;">🌅 今朝の市場のまとめ</h2>
      <p style="color:#888;font-size:12px;margin:0 0 10px 0;">寄り前のチェック（{as_of}）— 地合い・指数・注目イベントを手早く把握</p>
      {sentiment_html}{grid}{watch_html}
    </div>"""


def _header(accent: str, emoji: str, title: str, sub: str) -> str:
    return f"""
  <div style="background:{accent};color:#fff;padding:16px 20px;border-radius:8px;margin-bottom:24px;">
    <div style="font-size:12px;opacity:0.8;">株スクリーニング</div>
    <div style="font-size:20px;font-weight:bold;">{emoji} {title}</div>
    <div style="font-size:11px;opacity:0.7;margin-top:4px;">{sub}</div>
  </div>"""


FOOTER = """
  <div style="border-top:1px solid #eee;padding-top:12px;color:#aaa;font-size:11px;text-align:center;">
    本メールは自動送信です。投資判断はご自身でお願いします。
  </div>"""


def _wrap(body: str) -> str:
    return (f'<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:600px;'
            f'margin:0 auto;padding:20px;background:#fff;">{body}{FOOTER}</body></html>')


# ---------------------------------------------------------------- 朝メール

def build_morning(screen: dict, matsuri: dict, market: dict | None = None) -> str:
    today = datetime.now().strftime("%Y/%m/%d")

    # お祭り銘柄（デイトレ予習）— 最下部セクションへ
    s1 = ""
    for i, s in enumerate(matsuri.get("matsuri", [])[:10], 1):
        extra = f'<br><span style="color:#555;font-size:13px;">→ {s.get("reason","")}</span>'
        price = s.get("price", "")
        price_html = f'<span style="font-size:15px;font-weight:bold;">{price}円</span>' if price != "" else "-"
        s1 += _row(i, str(s.get("code", "")), s.get("name", ""), price_html, extra)

    # 急落リバウンド候補（履歴が貯まると出現）
    rebound_rows = ""
    for i, s in enumerate(matsuri.get("rebound", []), 1):
        extra = f'<br><span style="color:#555;font-size:13px;">→ {s.get("reason","")}</span>'
        rebound_rows += _row(i, str(s.get("code", "")), s.get("name", ""), "-", extra)

    def tech_rows(items):
        out = ""
        for i, s in enumerate(items, 1):
            extra = (f'<br><span style="color:#888;font-size:13px;">乖離率: {s.get("gap_ratio","")}% ／ '
                     f'SMA13: {s.get("sma13","")} ／ SMA26: {s.get("sma26","")}</span>')
            price_html = f'<span style="font-size:15px;font-weight:bold;">{s.get("price","")}円</span>'
            out += _row(i, s.get("code", ""), s.get("name", ""), price_html, extra)
        return out

    # 順序: ① 今朝の市場のまとめ（地合いを手早く把握）→ ② 週足GCテクニカル
    #       → ③ お祭り銘柄（デイトレ予習）＋リバウンドは最下部
    body = (
        _header("#1a56db", "📊", f"{today} 朝の市場まとめ & 候補銘柄",
                f'スクリーニング実行: {screen.get("screened_at","-")} ／ 対象 {screen.get("universe_size","-")} 銘柄')
        + _market_section(market or {})
        + _section("週足GC直前ランキング TOP10", "📈",
                   "株価2300円以下／13週SMA＜26週SMA／株価＞26週SMA／乖離率の低い順",
                   tech_rows(screen.get("section2", [])), "#1a56db", "株価")
        + _section("GC直前（株価2300円超）参考リスト TOP10", "💡",
                   "「株価2300円未満」だけ満たさない銘柄（テクニカルはGC直前／参考）",
                   tech_rows(screen.get("section3", [])), "#1a56db", "株価")
        + _section("お祭り銘柄 TOP10（デイトレ予習）", "🔥",
                   "値上がり率・出来高上位／25日線上抜け／出来高急増／材料・仕手・IPO・常連を加味した強い動きの銘柄",
                   s1, "#e8590c", "株価")
    )
    if rebound_rows:
        body += _section("急落リバウンド候補", "🔄",
                         "ランキング常連だったが本日は圏外。リバウンドを狙える可能性",
                         rebound_rows, "#e8590c", "")
    return _wrap(body)


# ---------------------------------------------------------------- 昼メール

def enrich_prices(candidates: list) -> list:
    """yfinanceで現在株価・前日比・出来高を付加。"""
    import yfinance as yf

    enriched = []
    for c in candidates[:10]:
        code = str(c.get("code", ""))
        c.setdefault("price", "-")
        c.setdefault("change", "-")
        c.setdefault("change_pct", "-")
        c.setdefault("change_color", "#888")
        c.setdefault("volume", "-")
        try:
            hist = yf.Ticker(f"{code}.T").history(period="3d", interval="1d")
            if len(hist) >= 2:
                cur = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                change = cur - prev
                pct = (change / prev) * 100 if prev else 0
                vol = float(hist["Volume"].iloc[-1])
                up = change >= 0
                c["price"] = round(cur, 1)
                c["change"] = f"+{change:.1f}" if up else f"{change:.1f}"
                c["change_pct"] = f"+{pct:.2f}%" if up else f"{pct:.2f}%"
                c["change_color"] = "#e53e3e" if up else "#2b6cb0"
                c["volume"] = f"{vol / 10000:.1f}万株"
        except Exception as e:  # noqa: BLE001
            print(f"  株価取得失敗 {code}: {e}", file=sys.stderr)
        enriched.append(c)
    return enriched


def build_afternoon(candidates: list) -> str:
    today = datetime.now().strftime("%Y/%m/%d")
    now = datetime.now().strftime("%H:%M")

    rows = ""
    for i, s in enumerate(candidates, 1):
        extra = (f'<br><span style="color:#555;font-size:13px;">→ {s.get("reason","")}</span>'
                 f'<br><span style="color:#888;font-size:12px;">出来高: {s.get("volume","-")}</span>')
        price_html = (f'<div style="font-size:16px;font-weight:bold;">{s.get("price","-")}円</div>'
                      f'<div style="font-size:13px;color:{s.get("change_color","#888")};font-weight:bold;">'
                      f'{s.get("change","-")}（{s.get("change_pct","-")}）</div>')
        rows += _row(i, str(s.get("code", "")), s.get("name", ""), price_html, extra)

    body = (
        _header("#2d6a4f", "🕧", f"{today} 午後の候補銘柄", f"配信時刻: {now}")
        + _section("午後から上昇期待の銘柄", "📈",
                   "前場の動きを踏まえ、午後の上昇が期待される銘柄",
                   rows, "#2d6a4f", "株価 / 前日比")
    )
    return _wrap(body)


# ---------------------------------------------------------------- 送信

def send_email(subject: str, html_body: str):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    raw_to = os.environ.get("TO_EMAIL", gmail_user)
    recipients = [a.strip() for a in raw_to.split(",") if a.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())

    print(f"メール送信完了 → {', '.join(recipients)}")


def main():
    parser = argparse.ArgumentParser(description="スクリーニング結果メール送信")
    sub = parser.add_subparsers(dest="mode", required=True)

    m = sub.add_parser("morning", help="朝8時メール")
    m.add_argument("--screen", required=True, help="screener.py出力JSON")
    m.add_argument("--matsuri", help="daytrade.py出力JSON（お祭り銘柄）")
    m.add_argument("--market", help="今朝の市場まとめJSON（地合い・指数・注目イベント）")

    a = sub.add_parser("afternoon", help="昼12:30メール")
    a.add_argument("--candidates", required=True, help="午後候補銘柄JSON")

    args = parser.parse_args()
    today = datetime.now().strftime("%Y/%m/%d")

    if args.mode == "morning":
        screen = load_json(args.screen, {})
        matsuri = load_json(args.matsuri, {})
        market = load_json(args.market, {})
        html = build_morning(screen, matsuri, market)
        send_email(f"【株スクリーニング】{today} 朝の市場まとめ＆候補銘柄", html)
    else:
        candidates = enrich_prices(load_json(args.candidates, []))
        html = build_afternoon(candidates)
        send_email(f"【株スクリーニング】{today} 午後の候補銘柄リスト", html)


if __name__ == "__main__":
    main()
