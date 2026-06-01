"""
12:30メール送信スクリプト
午後から上がりそうな銘柄リスト（現在株価・前日比・出来高・コメント付き）
"""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import anthropic
import yfinance as yf


def get_afternoon_candidates() -> list[dict]:
    """Claude APIで午後候補銘柄を取得・株価情報を付加"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    
    today = datetime.now().strftime("%Y年%m月%d日")
    
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": f"""
{today}の日本株市場で、午後（12:30以降）から上昇が期待できる銘柄を10個選んでください。

以下の観点で選んでください：
- 前場で出来高急増・価格帯に注目
- 午前中に押し目を形成して反発しそうな銘柄
- 午後に材料出動が予想される銘柄（決算、IR等）
- 日経平均・セクターの動きに連動しやすい銘柄

以下のJSON形式のみで返してください（```や説明文は不要）：
[
  {{
    "code": "7272",
    "name": "ヤマハ発動機",
    "reason": "前場で26週線タッチ後反発、出来高急増で午後の上昇に期待"
  }},
  ...
]
"""
        }]
    )
    
    result_text = ""
    for block in response.content:
        if block.type == "text":
            result_text += block.text
    
    try:
        clean = result_text.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        candidates = json.loads(clean.strip())
    except Exception as e:
        print(f"パースエラー: {e}")
        return []
    
    # yfinanceで現在株価・前日比・出来高を取得
    enriched = []
    for c in candidates[:10]:
        code = str(c.get("code", ""))
        try:
            ticker = yf.Ticker(f"{code}.T")
            hist = ticker.history(period="3d", interval="1d")
            
            if len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                change = current - prev
                change_pct = (change / prev) * 100
                volume = hist["Volume"].iloc[-1]
                
                # 出来高を万株表示
                volume_man = f"{volume / 10000:.1f}万株"
                change_str = f"+{change:.1f}" if change >= 0 else f"{change:.1f}"
                change_pct_str = f"+{change_pct:.2f}%" if change_pct >= 0 else f"{change_pct:.2f}%"
                change_color = "#e53e3e" if change >= 0 else "#2b6cb0"
                
                c["price"] = round(current, 1)
                c["change"] = change_str
                c["change_pct"] = change_pct_str
                c["change_color"] = change_color
                c["volume"] = volume_man
            else:
                c["price"] = "-"
                c["change"] = "-"
                c["change_pct"] = "-"
                c["change_color"] = "#888"
                c["volume"] = "-"
                
        except Exception as e:
            c["price"] = "-"
            c["change"] = "-"
            c["change_pct"] = "-"
            c["change_color"] = "#888"
            c["volume"] = "-"
        
        c["chart_url"] = f"https://finance.yahoo.co.jp/quote/{code}.T/chart?frm=wkly&trm=6m&scl=stndrd&styl=cndl&evnts=volume&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
        enriched.append(c)
    
    return enriched


def build_afternoon_email(candidates: list) -> str:
    """12:30メールのHTMLを構築"""
    today = datetime.now().strftime("%Y/%m/%d")
    now = datetime.now().strftime("%H:%M")
    
    rows = ""
    for i, s in enumerate(candidates, 1):
        code = s.get("code", "")
        name = s.get("name", "")
        price = s.get("price", "-")
        change = s.get("change", "-")
        change_pct = s.get("change_pct", "-")
        change_color = s.get("change_color", "#888")
        volume = s.get("volume", "-")
        reason = s.get("reason", "")
        chart_url = s.get("chart_url", "")
        
        rows += f"""
    <tr style="border-bottom:1px solid #eee;">
      <td style="padding:12px 6px;color:#999;font-size:13px;vertical-align:top;">{i}</td>
      <td style="padding:12px 6px;vertical-align:top;">
        <a href="{chart_url}" style="font-weight:bold;color:#1a56db;text-decoration:none;font-size:15px;">{code} {name}</a>
        <br>
        <span style="color:#555;font-size:13px;">→ {reason}</span>
        <br>
        <span style="color:#888;font-size:12px;">出来高: {volume}</span>
      </td>
      <td style="padding:12px 6px;text-align:right;vertical-align:top;white-space:nowrap;">
        <div style="font-size:16px;font-weight:bold;">{price}円</div>
        <div style="font-size:13px;color:{change_color};font-weight:bold;">{change}（{change_pct}）</div>
      </td>
    </tr>"""
    
    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#fff;">

  <div style="background:#2d6a4f;color:#fff;padding:16px 20px;border-radius:8px;margin-bottom:24px;">
    <div style="font-size:12px;opacity:0.8;">株スクリーニング</div>
    <div style="font-size:20px;font-weight:bold;">🕧 {today} 午後の候補銘柄</div>
    <div style="font-size:11px;opacity:0.7;margin-top:4px;">配信時刻: {now}</div>
  </div>

  <div style="margin-bottom:32px;">
    <h2 style="font-size:16px;color:#111;border-left:4px solid #2d6a4f;padding-left:10px;margin-bottom:4px;">
      📈 午後から上昇期待の銘柄
    </h2>
    <p style="color:#888;font-size:12px;margin:0 0 10px 0;">
      前場の動きを踏まえ、午後の上昇が期待される銘柄
    </p>
    <table style="width:100%;border-collapse:collapse;font-family:sans-serif;">
      <thead>
        <tr style="background:#f5f5f5;">
          <th style="padding:8px 6px;text-align:left;font-size:12px;color:#888;width:30px;">#</th>
          <th style="padding:8px 6px;text-align:left;font-size:12px;color:#888;">銘柄・コメント</th>
          <th style="padding:8px 6px;text-align:right;font-size:12px;color:#888;">株価 / 前日比</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <div style="border-top:1px solid #eee;padding-top:12px;color:#aaa;font-size:11px;text-align:center;">
    本メールは自動送信です。投資判断はご自身でお願いします。
  </div>

</body>
</html>"""
    
    return html


def send_email(subject: str, html_body: str):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    to_email = os.environ.get("TO_EMAIL", gmail_user)
    
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
    print("=== 12:30 午後スクリーニング開始 ===")
    
    candidates = get_afternoon_candidates()
    
    today = datetime.now().strftime("%Y/%m/%d")
    subject = f"【株スクリーニング】{today} 午後の候補銘柄リスト"
    html = build_afternoon_email(candidates)
    
    send_email(subject, html)
    print("=== 完了 ===")


if __name__ == "__main__":
    main()
