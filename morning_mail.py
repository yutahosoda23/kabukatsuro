"""
朝8時メール送信スクリプト
Section 1: 好材料銘柄10個（Claude APIでウェブ検索）
Section 2: GC直前ランキング10個（乖離率低い順）
Section 3: 株価2300円超のGC直前銘柄10個
"""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import anthropic
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from screener import screen_stocks


def get_hot_stocks_from_claude() -> list[dict]:
    """Claude APIで本日の好材料銘柄を取得"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    
    today = datetime.now().strftime("%Y年%m月%d日")
    
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": f"""
{today}の日本株市場で、本日デイトレードに適した好材料が出ている銘柄を10個探してください。

以下の観点で探してください：
- 決算発表（上方修正、増配、好決算）
- 証券会社の目標株価引き上げ・買い推奨
- 自社株買い発表
- M&A・提携・新製品発表
- 出来高急増・話題銘柄

以下のJSON形式のみで返してください（```や説明文は不要）：
[
  {{
    "code": "7272",
    "name": "ヤマハ発動機",
    "price": 1279,
    "reason": "Q1決算で営業利益+43.8%、通期増益予想"
  }},
  ...
]
"""
        }]
    )
    
    # レスポンスからテキストを抽出
    result_text = ""
    for block in response.content:
        if block.type == "text":
            result_text += block.text
    
    # JSON部分を抽出してパース
    try:
        # ```json ブロックがある場合は除去
        clean = result_text.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        stocks = json.loads(clean.strip())
        
        # chart_urlを追加
        for s in stocks:
            code = str(s.get("code", ""))
            s["chart_url"] = f"https://finance.yahoo.co.jp/quote/{code}.T/chart?frm=wkly&trm=6m&scl=stndrd&styl=cndl&evnts=volume&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
        
        return stocks[:10]
    except Exception as e:
        print(f"Claude API パースエラー: {e}\nraw: {result_text}")
        return []


def build_stock_row(s: dict, rank: int, show_reason: bool = False, show_gap: bool = False) -> str:
    """銘柄1行分のHTMLを生成"""
    code = s.get("code", "")
    name = s.get("name", "")
    price = s.get("price", "")
    chart_url = s.get("chart_url", "")
    
    extra = ""
    if show_reason:
        extra = f'<br><span style="color:#555;font-size:13px;">→ {s.get("reason","")}</span>'
    if show_gap:
        extra = f'<br><span style="color:#888;font-size:13px;">乖離率: -{s.get("gap_ratio","")}% ／ SMA13: {s.get("sma13","")} ／ SMA26: {s.get("sma26","")}</span>'
    
    return f"""
    <tr style="border-bottom:1px solid #eee;">
      <td style="padding:10px 6px;color:#999;font-size:13px;">{rank}</td>
      <td style="padding:10px 6px;">
        <a href="{chart_url}" style="font-weight:bold;color:#1a56db;text-decoration:none;font-size:15px;">{code} {name}</a>
        {extra}
      </td>
      <td style="padding:10px 6px;text-align:right;font-size:15px;font-weight:bold;">{price}円</td>
    </tr>"""


def build_morning_email(hot_stocks: list, gc_candidates: list, gc_over_2300: list, screened_at: str) -> str:
    """朝メールのHTMLを構築"""
    today = datetime.now().strftime("%Y/%m/%d")
    
    # Section 1
    section1_rows = ""
    for i, s in enumerate(hot_stocks, 1):
        section1_rows += build_stock_row(s, i, show_reason=True)
    
    # Section 2
    section2_rows = ""
    for i, s in enumerate(gc_candidates, 1):
        section2_rows += build_stock_row(s, i, show_gap=True)
    
    # Section 3
    section3_rows = ""
    for i, s in enumerate(gc_over_2300, 1):
        section3_rows += build_stock_row(s, i, show_gap=True)
    
    def section_table(title: str, emoji: str, rows: str, description: str) -> str:
        return f"""
    <div style="margin-bottom:32px;">
      <h2 style="font-size:16px;color:#111;border-left:4px solid #1a56db;padding-left:10px;margin-bottom:4px;">{emoji} {title}</h2>
      <p style="color:#888;font-size:12px;margin:0 0 10px 0;">{description}</p>
      <table style="width:100%;border-collapse:collapse;font-family:sans-serif;">
        <thead>
          <tr style="background:#f5f5f5;">
            <th style="padding:8px 6px;text-align:left;font-size:12px;color:#888;width:30px;">#</th>
            <th style="padding:8px 6px;text-align:left;font-size:12px;color:#888;">銘柄</th>
            <th style="padding:8px 6px;text-align:right;font-size:12px;color:#888;">株価</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""
    
    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#fff;">

  <div style="background:#1a56db;color:#fff;padding:16px 20px;border-radius:8px;margin-bottom:24px;">
    <div style="font-size:12px;opacity:0.8;">株スクリーニング</div>
    <div style="font-size:20px;font-weight:bold;">📊 {today} 朝の候補銘柄</div>
    <div style="font-size:11px;opacity:0.7;margin-top:4px;">スクリーニング実行: {screened_at}</div>
  </div>

  {section_table(
    "本日の好材料銘柄 TOP10", "📰", section1_rows,
    "決算・買い推奨・自社株買いなど、本日注目の材料が出ている銘柄"
  )}
  
  {section_table(
    "週足GC直前ランキング TOP10", "📈", section2_rows,
    "株価2300円以下／13週SMA＜26週SMA／株価＞26週SMA／乖離率低い順"
  )}
  
  {section_table(
    "GC直前（株価2300円超）参考リスト TOP10", "💡", section3_rows,
    "価格条件は外れるが、テクニカル的にGC直前の銘柄（参考）"
  )}

  <div style="border-top:1px solid #eee;padding-top:12px;color:#aaa;font-size:11px;text-align:center;">
    本メールは自動送信です。投資判断はご自身でお願いします。
  </div>

</body>
</html>"""
    
    return html


def send_email(subject: str, html_body: str):
    """Gmail SMTPでメール送信"""
    gmail_user = os.environ["GMAIL_USER"]          # 送信元Gmailアドレス
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]  # Googleアプリパスワード
    to_email = os.environ.get("TO_EMAIL", gmail_user)  # 送信先（未設定なら自分宛）
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, to_email, msg.as_string())
    
    print(f"メール送信完了 → {to_email}")


def main():
    print("=== 朝のスクリーニング開始 ===")
    
    # テクニカルスクリーニング
    print("テクニカルスクリーニング実行中...")
    result = screen_stocks(gap_threshold=0.05)
    gc_candidates = result["gc_candidates"]
    gc_over_2300 = result["gc_over_2300"]
    screened_at = result["screened_at"]
    
    # Claude APIで好材料銘柄取得
    print("好材料銘柄をClaudeで検索中...")
    hot_stocks = get_hot_stocks_from_claude()
    
    # メール構築・送信
    today = datetime.now().strftime("%Y/%m/%d")
    subject = f"【株スクリーニング】{today} 朝の候補銘柄リスト"
    html = build_morning_email(hot_stocks, gc_candidates, gc_over_2300, screened_at)
    
    send_email(subject, html)
    print("=== 完了 ===")


if __name__ == "__main__":
    main()
