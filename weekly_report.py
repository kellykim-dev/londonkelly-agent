import os
import json
import anthropic
from datetime import datetime, timedelta
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric
from google.oauth2 import service_account

GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "")
GA4_KEY_FILE    = os.environ.get("GA4_KEY_FILE", "ga4_key.json")
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")

def get_ga4_data():
    creds = service_account.Credentials.from_service_account_file(
        GA4_KEY_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[DateRange(
            start_date=last_monday.strftime("%Y-%m-%d"),
            end_date=last_sunday.strftime("%Y-%m-%d")
        )],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="screenPageViews"),
            Metric(name="addToCarts"),
            Metric(name="ecommercePurchases"),
            Metric(name="purchaseRevenue"),
        ]
    )
    response = client.run_report(request)
    row = response.rows[0].metric_values if response.rows else None
    if row:
        return {
            "sessions": int(row[0].value),
            "users": int(row[1].value),
            "pageviews": int(row[2].value),
            "add_to_carts": int(row[3].value),
            "purchases": int(row[4].value),
            "revenue": float(row[5].value),
            "week_start": last_monday.strftime("%Y-%m-%d"),
            "week_end": last_sunday.strftime("%Y-%m-%d"),
        }
    return {}

def get_ads_data():
    # 之後從 Sheets 讀，暫時用上週真實數據
    return {
        "cost": 1259.92,
        "roas": 34.9,
        "clicks": 0,
        "conversions": 0,
        "conv_value": 0
    }

def analyze_with_claude(ga4, ads):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = f"""你係 LondonKelly 嘅數據分析師，用繁體中文寫週報。
LondonKelly 係香港代購服務，主要賣歐洲奢侈品牌。

上週數據（{ga4.get('week_start','')} ~ {ga4.get('week_end','')}）：

【Google Analytics】
Sessions: {ga4.get('sessions',0):,}
用戶數: {ga4.get('users',0):,}
Page Views: {ga4.get('pageviews',0):,}
加購物車: {ga4.get('add_to_carts',0):,}
成交: {ga4.get('purchases',0):,}
收入: HK${ga4.get('revenue',0):,.0f}

【Google Ads】
花費: HK${ads.get('cost',0):,.2f}
ROAS: {ads.get('roas',0)}x

請寫：
1. 本週表現總結
2. 亮點
3. 需要關注問題
4. 下週建議行動3條

用emoji，簡潔，適合手機睇。"""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def generate_html(ga4, ads, analysis):
    week = f"{ga4.get('week_start','')} ~ {ga4.get('week_end','')}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Convert analysis newlines to HTML
    analysis_html = analysis.replace('\n', '<br>')
    html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LondonKelly 週報</title>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#1a1208;color:#eee;font-family:sans-serif;padding:16px;}}
.wrap{{max-width:600px;margin:0 auto;}}
.title{{font-family:'Press Start 2P',monospace;color:#FFD700;font-size:10px;text-align:center;padding:12px;background:#2a1808;border:2px solid #5C4A2A;margin-bottom:16px;}}
.week{{color:#88DDFF;font-size:12px;text-align:center;margin-bottom:16px;}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;}}
.card{{background:#0a0a1e;border:1px solid #1a1a3e;border-radius:6px;padding:12px;text-align:center;}}
.card-label{{color:#888;font-size:11px;margin-bottom:4px;}}
.card-value{{color:#00FF88;font-size:20px;font-weight:bold;}}
.card-value.gold{{color:#FFD700;}}
.card-value.blue{{color:#88DDFF;}}
.analysis{{background:#0a0a1e;border:1px solid #1a1a3e;border-radius:6px;padding:16px;font-size:14px;line-height:1.8;}}
.analysis-title{{font-family:'Press Start 2P',monospace;color:#00FF88;font-size:7px;margin-bottom:12px;}}
.footer{{color:#555;font-size:11px;text-align:center;margin-top:12px;}}
.back{{display:block;text-align:center;color:#FFD700;font-size:11px;margin-bottom:16px;text-decoration:none;font-family:'Press Start 2P',monospace;}}
</style>
</head>
<body>
<div class="wrap">
  <a href="index.html" class="back">← 返回辦公室</a>
  <div class="title">★ LondonKelly 週報 ★</div>
  <div class="week">📅 {week}</div>
  <div class="cards">
    <div class="card">
      <div class="card-label">Sessions</div>
      <div class="card-value blue">{ga4.get('sessions',0):,}</div>
    </div>
    <div class="card">
      <div class="card-label">用戶數</div>
      <div class="card-value blue">{ga4.get('users',0):,}</div>
    </div>
    <div class="card">
      <div class="card-label">加購物車</div>
      <div class="card-value">{ga4.get('add_to_carts',0):,}</div>
    </div>
    <div class="card">
      <div class="card-label">成交</div>
      <div class="card-value">{ga4.get('purchases',0):,}</div>
    </div>
    <div class="card">
      <div class="card-label">Ads 花費</div>
      <div class="card-value gold">HK${ads.get('cost',0):,.0f}</div>
    </div>
    <div class="card">
      <div class="card-label">ROAS</div>
      <div class="card-value gold">{ads.get('roas',0)}x</div>
    </div>
  </div>
  <div class="analysis">
    <div class="analysis-title">&gt;_ Claude 分析</div>
    {analysis_html}
  </div>
  <div class="footer">由 LondonKelly Agent 生成 · {now}</div>
</div>
</body>
</html>"""
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ report.html 生成完成")

if __name__ == "__main__":
    print("📊 拉 GA4 數據...")
    ga4 = get_ga4_data()
    print(f"  Sessions: {ga4.get('sessions',0)}")
    print("📈 拉 Ads 數據...")
    ads = get_ads_data()
    print("🤖 Claude 分析緊...")
    analysis = analyze_with_claude(ga4, ads)
    print("📄 生成 report.html...")
    generate_html(ga4, ads, analysis)
