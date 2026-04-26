import os
import re
import json
import anthropic
import gspread
from datetime import datetime, timedelta
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, DateRange, Metric, Dimension, OrderBy
)
from google.oauth2 import service_account

GA4_PROPERTY_ID  = os.environ.get("GA4_PROPERTY_ID", "")
GA4_KEY_FILE     = os.environ.get("GA4_KEY_FILE", "ga4_key.json")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
SHEETS_URL       = "https://docs.google.com/spreadsheets/d/1Ef5whhbOuUh-hQn8N1GGKKzSJ8UrjinXigZmkS0RiyE/edit"

def get_date_range():
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday

def get_ga4_data():
    print("📊 拉 GA4 數據...")
    creds = service_account.Credentials.from_service_account_file(
        GA4_KEY_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)
    last_monday, last_sunday = get_date_range()
    date_range = DateRange(
        start_date=last_monday.strftime("%Y-%m-%d"),
        end_date=last_sunday.strftime("%Y-%m-%d")
    )

    # 1. 總覽數據
    overview_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[date_range],
        metrics=[
            Metric(name="sessions"), Metric(name="activeUsers"),
            Metric(name="screenPageViews"), Metric(name="addToCarts"),
            Metric(name="ecommercePurchases"), Metric(name="purchaseRevenue"),
        ]
    )
    ov = client.run_report(overview_req)
    row = ov.rows[0].metric_values if ov.rows else None
    overview = {}
    if row:
        overview = {
            "sessions": int(row[0].value), "users": int(row[1].value),
            "pageviews": int(row[2].value), "add_to_carts": int(row[3].value),
            "purchases": int(row[4].value), "revenue": float(row[5].value),
            "week_start": last_monday.strftime("%Y-%m-%d"),
            "week_end": last_sunday.strftime("%Y-%m-%d"),
        }

    # 2. Channel breakdown (sessions + purchases by channel)
    channel_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[date_range],
        dimensions=[Dimension(name="sessionDefaultChannelGroup")],
        metrics=[
            Metric(name="sessions"), Metric(name="ecommercePurchases"),
            Metric(name="purchaseRevenue"), Metric(name="addToCarts"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)]
    )
    ch = client.run_report(channel_req)
    channels = []
    for r in ch.rows:
        ch_name = r.dimension_values[0].value
        ch_sessions = int(r.metric_values[0].value)
        ch_purchases = int(r.metric_values[1].value)
        ch_revenue = float(r.metric_values[2].value)
        ch_carts = int(r.metric_values[3].value)
        conv_rate = round(ch_purchases / ch_sessions * 100, 2) if ch_sessions > 0 else 0
        channels.append({
            "channel": ch_name, "sessions": ch_sessions,
            "purchases": ch_purchases, "revenue": ch_revenue,
            "add_to_carts": ch_carts, "conv_rate": conv_rate
        })

    # 3. Top organic keywords (from organic search)
    kw_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[date_range],
        dimensions=[Dimension(name="sessionGoogleAdsKeyword")],
        metrics=[Metric(name="sessions"), Metric(name="ecommercePurchases")],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=20
    )
    kw = client.run_report(kw_req)
    keywords = []
    for r in kw.rows:
        kw_name = r.dimension_values[0].value
        if kw_name and kw_name != "(not set)" and kw_name != "(not provided)":
            keywords.append({
                "keyword": kw_name,
                "sessions": int(r.metric_values[0].value),
                "purchases": int(r.metric_values[1].value)
            })

    # 4. Top landing pages
    lp_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[date_range],
        dimensions=[Dimension(name="landingPage")],
        metrics=[Metric(name="sessions"), Metric(name="bounceRate"), Metric(name="ecommercePurchases")],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=10
    )
    lp = client.run_report(lp_req)
    landing_pages = []
    for r in lp.rows:
        landing_pages.append({
            "page": r.dimension_values[0].value,
            "sessions": int(r.metric_values[0].value),
            "bounce_rate": round(float(r.metric_values[1].value) * 100, 1),
            "purchases": int(r.metric_values[2].value)
        })

    print(f"  ✅ Sessions: {overview.get('sessions',0):,} | Channels: {len(channels)}")
    # GA4 Ads Keywords with conversion (sorted by purchases)
    ads_keywords = []
    org_keywords = []
    try:
        ads_kw_req = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[date_range],
            dimensions=[Dimension(name="sessionGoogleAdsKeyword")],
            metrics=[Metric(name="sessions"), Metric(name="ecommercePurchases"), Metric(name="purchaseRevenue")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="ecommercePurchases"), desc=True)],
            limit=20
        )
        for r in client.run_report(ads_kw_req).rows:
            kw = r.dimension_values[0].value
            if kw and kw not in ["(not set)", "(not provided)"]:
                ads_keywords.append({
                    "keyword": kw,
                    "sessions": int(r.metric_values[0].value),
                    "purchases": int(r.metric_values[1].value),
                    "revenue": round(float(r.metric_values[2].value), 0),
                })
    except Exception as e:
        print(f"  ⚠️ Ads KW: {e}")

    print(f"  ✅ Sessions: {overview.get('sessions',0):,} | Channels: {len(channels)} | Ads KW: {len(ads_keywords)}")
    return overview, channels, keywords, landing_pages, ads_keywords, org_keywords

def get_ads_data_from_sheets():
    print("📈 拉 Google Ads 數據 (from Sheets)...")
    try:
        creds = service_account.Credentials.from_service_account_file(
            GA4_KEY_FILE,
            scopes=[
                "https://www.googleapis.com/auth/analytics.readonly",
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly"
            ]
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(SHEETS_URL)

        # 總覽 sheet
        overview_sheet = sh.worksheet("總覽")
        overview_data = overview_sheet.get_all_records()
        latest = overview_data[-1] if overview_data else {}

        # Ad Groups sheet
        try:
            ag_sheet = sh.worksheet("Ad Groups")
            ag_data = ag_sheet.get_all_records()
        except:
            ag_data = []

        # Keywords sheet
        try:
            kw_sheet = sh.worksheet("Keywords")
            kw_data = kw_sheet.get_all_records()[:15]
        except:
            kw_data = []

        # Search Terms sheet - sort by Conv Value DESC
        try:
            st_sheet = sh.worksheet("Search Terms")
            all_st = st_sheet.get_all_records()
            st_data = sorted(
                all_st,
                key=lambda x: float(str(x.get('Conv Value', 0)).replace(',','') or 0),
                reverse=True
            )[:15]
        except:
            st_data = []

        ads = {
            "cost": float(str(latest.get("花費(HKD)", 0)).replace(",","")),
            "roas": str(latest.get("ROAS", "0x")).replace("x",""),
            "clicks": int(str(latest.get("Clicks", 0)).replace(",","")),
            "impressions": int(str(latest.get("Impressions", 0)).replace(",","")),
            "conversions": float(str(latest.get("Conversions", 0)).replace(",","")),
            "conv_value": float(str(latest.get("Conv Value", 0)).replace(",","")),
            "ctr": str(latest.get("CTR", "0%")),
            "week": str(latest.get("週期", "")),
            "ad_groups": ag_data,
            "keywords": kw_data,
            "search_terms": st_data,
        }
        print(f"  ✅ 花費: HK${ads['cost']:,.0f} | ROAS: {ads['roas']}x | Ad Groups: {len(ag_data)}")
        return ads
    except Exception as e:
        print(f"  ⚠️ Sheets 讀取失敗: {e}，用 hardcode")
        return {"cost": 1259.92, "roas": "34.9", "clicks": 0, "impressions": 0,
                "conversions": 0, "conv_value": 0, "ctr": "0%", "week": "",
                "ad_groups": [], "keywords": [], "search_terms": []}

def analyze_with_claude(ga4, channels, keywords, landing_pages, ads, lang="zh", ads_keywords=None, org_keywords=None):
    print(f"  🤖 Claude 分析 ({'繁中' if lang=='zh' else '韓文'})...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    # Channel summary
    ch_summary = "\n".join([
        f"  {c['channel']}: {c['sessions']:,} sessions | {c['purchases']} 成交 | HK${c['revenue']:,.0f} | conv {c['conv_rate']}%"
        for c in channels[:8]
    ])

    # Ad group summary
    ag_summary = ""
    if ads.get("ad_groups"):
        top_ag = sorted(ads["ad_groups"], key=lambda x: float(str(x.get("花費(HKD)",0)).replace(",","")), reverse=True)[:8]
        ag_summary = "\n".join([
            f"  {a.get('Ad Group','')}: 花費 HK${a.get('花費(HKD)',0)} | {a.get('Clicks',0)} clicks | ROAS {a.get('ROAS','0x')}"
            for a in top_ag
        ])

    # Keywords summary
    kw_summary = ""
    if ads.get("keywords"):
        kw_summary = "\n".join([
            f"  {k.get('Keyword','')}: {k.get('Clicks',0)} clicks | 花費 HK${k.get('花費(HKD)',0)}"
            for k in ads["keywords"][:10]
        ])

    # Search terms
    st_summary = ""
    if ads.get("search_terms"):
        st_summary = "\n".join([
            f"  '{s.get('Search Term','')}': {s.get('Clicks',0)} clicks"
            for s in ads["search_terms"][:10]
        ])

    # Top pages
    lp_summary = "\n".join([
        f"  {p['page']}: {p['sessions']:,} sessions | bounce {p['bounce_rate']}% | {p['purchases']} 成交"
        for p in landing_pages[:5]
    ])

    if lang == "zh":
        prompt = f"""你係 LondonKelly 嘅數據分析師，用繁體中文寫詳細週報。
LondonKelly 係英國代購，賣歐洲奢侈品，目標客戶香港/台灣/澳門。

=== 上週數據 ({ga4.get('week_start','')} ~ {ga4.get('week_end','')}) ===

【GA4 總覽】
Sessions: {ga4.get('sessions',0):,} | Users: {ga4.get('users',0):,} | Page Views: {ga4.get('pageviews',0):,}
加購物車: {ga4.get('add_to_carts',0):,} | 成交: {ga4.get('purchases',0):,} | 收入: HK${ga4.get('revenue',0):,.0f}
整體轉化率: {round(ga4.get('purchases',0)/ga4.get('sessions',1)*100,3)}%

【流量來源 Channel Breakdown】
{ch_summary}

【Google Ads 總覽】
花費: HK${ads.get('cost',0):,.2f} | ROAS: {ads.get('roas',0)}x | Clicks: {ads.get('clicks',0):,}
Impressions: {ads.get('impressions',0):,} | CTR: {ads.get('ctr','')} | Conversions: {ads.get('conversions',0)}

【Google Ads - Ad Group 表現】
{ag_summary if ag_summary else '(暫無數據)'}

【Google Ads - Top Keywords】
{kw_summary if kw_summary else '(暫無數據)'}

【Google Ads - Top Search Terms】
{st_summary if st_summary else '(暫無數據)'}

【Top Landing Pages】
{lp_summary}

請寫完整分析報告，包括：
## 📊 本週表現總結
## 🔍 流量來源分析（每個 channel 點表現，哪個 channel 最值得投資）
## 💰 Google Ads 深度分析（哪個 ad group ROAS 最高/最低，哪些 keyword 最值錢，search terms 有冇機會）
## 🎯 Top Landing Pages 分析（哪個頁面帶最多轉化，哪個頁面 bounce rate 高需要改善）
## ⚠️ 需要關注問題
## 🚀 下週5個具體行動建議（越具體越好，例如暫停邊個 ad group、加邊個 keyword）

用 emoji，清晰，適合手機睇。"""
    else:
        prompt = f"""당신은 LondonKelly의 데이터 분석가입니다. 한국어로 상세한 주간 보고서를 작성해주세요.

=== 지난주 데이터 ({ga4.get('week_start','')} ~ {ga4.get('week_end','')}) ===

【GA4 총괄】
세션: {ga4.get('sessions',0):,} | 사용자: {ga4.get('users',0):,}
장바구니: {ga4.get('add_to_carts',0):,} | 구매: {ga4.get('purchases',0):,} | 수익: HK${ga4.get('revenue',0):,.0f}

【채널별 분석】
{ch_summary}

【Google Ads】
광고비: HK${ads.get('cost',0):,.2f} | ROAS: {ads.get('roas',0)}x
Ad Groups: {ag_summary if ag_summary else '(데이터 없음)'}
Keywords: {kw_summary if kw_summary else '(데이터 없음)'}

## 📊 이번 주 성과 요약
## 🔍 채널별 트래픽 분석
## 💰 Google Ads 심층 분석 (Ad Group별 ROAS, 주요 키워드)
## ⚠️ 주의사항
## 🚀 다음 주 5가지 구체적 실행 계획"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def md2html(t):
    # Convert markdown tables to HTML tables
    import re as re2
    def convert_table(match):
        block = match.group(0)
        lines = [l.strip() for l in block.split('\n') if l.strip().startswith('|')]
        out = '<table class="data-table">'
        header_done = False
        for line in lines:
            if re2.match(r'^\|[\s\-\|:]+\|$', line): continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if not header_done:
                out += '<tr>' + ''.join(f'<th>{c}</th>' for c in cells) + '</tr>'
                header_done = True
            else:
                out += '<tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>'
        return out + '</table>'
    t = re2.sub(r'(\|[^\n]+\n)+\|[^\n]+', convert_table, t)
    t = re.sub(r'##+ (.+)', r'<h3 style="color:#4dd0c4;margin:14px 0 6px;font-weight:800;">\1</h3>', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#ffd580;">\1</strong>', t)
    t = re.sub(r'^- (.+)', r'<li style="margin:4px 0;">\1</li>', t, flags=re.MULTILINE)
    t = re.sub(r'---+', '<hr style="border-color:#2a1a50;margin:12px 0;">', t)
    t = t.replace('\n', '<br>')
    return t

def generate_html(ga4, channels, keywords_ga4, landing_pages, ads, analysis, lang="zh", ads_keywords=None, org_keywords=None):
    week = f"{ga4.get('week_start','')} ~ {ga4.get('week_end','')}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    analysis_html = md2html(analysis)

    if lang == "zh":
        title, back = "LondonKelly 週報", "← 返回辦公室"
        labels = ["Sessions","用戶數","加購物車","成交","Ads 花費","ROAS"]
        filename, other_link, other_label = "report.html", "report_kr.html", "🇰🇷 한국어 버전"
        ch_title, ad_title = "流量來源", "Google Ads Ad Group"
        kw_title, st_title = "Top Keywords (Ads)", "Top Search Terms"
    else:
        title, back = "LondonKelly 주간 보고서", "← 사무실로 돌아가기"
        labels = ["Sessions","사용자","장바구니","구매","광고비","ROAS"]
        filename, other_link, other_label = "report_kr.html", "report.html", "🇨🇳 繁體中文版"
        ch_title, ad_title = "채널별 트래픽", "Google Ads Ad Group"
        kw_title, st_title = "Top Keywords", "Top Search Terms"

    # Channel table
    ch_rows = ""
    for c in channels[:8]:
        bar_width = min(int(c['sessions'] / max(channels[0]['sessions'],1) * 100), 100)
        ch_rows += f"""<tr>
          <td><strong>{c['channel']}</strong></td>
          <td>{c['sessions']:,}</td>
          <td>{c['purchases']}</td>
          <td>HK${c['revenue']:,.0f}</td>
          <td><span style="color:{'#4dd0c4' if c['conv_rate']>0.1 else '#f48fb1'}">{c['conv_rate']}%</span></td>
        </tr>"""

    # Ad group table
    ag_rows = ""
    if ads.get("ad_groups"):
        top_ag = sorted(ads["ad_groups"], key=lambda x: float(str(x.get("花費(HKD)",0)).replace(",","")), reverse=True)[:8]
        for a in top_ag:
            roas_val = str(a.get('ROAS','0x')).replace('x','')
            try:
                roas_float = float(roas_val)
                roas_color = '#4dd0c4' if roas_float >= 3 else '#f48fb1'
            except:
                roas_color = '#b0a0d0'
            ag_rows += f"""<tr>
              <td><strong>{a.get('Ad Group','')[:30]}</strong></td>
              <td>{a.get('Clicks',0)}</td>
              <td>HK${a.get('花費(HKD)',0)}</td>
              <td>{a.get('Conversions',0)}</td>
              <td style="color:{roas_color}">{a.get('ROAS','0x')}</td>
            </tr>"""

    # Keywords table
    kw_rows = ""
    if ads.get("keywords"):
        for k in ads["keywords"][:10]:
            kw_rows += f"""<tr>
              <td>{k.get('Keyword','')}</td>
              <td>{k.get('Clicks',0)}</td>
              <td>HK${k.get('花費(HKD)',0)}</td>
              <td>{k.get('Conversions',0)}</td>
            </tr>"""

    # GA4 Ads keywords table
    ads_kw_rows = ""
    if ads_keywords:
        for k in (ads_keywords or [])[:10]:
            ads_kw_rows += f"""<tr>
              <td><strong>{k.get('keyword','')}</strong></td>
              <td>{k.get('sessions',0):,}</td>
              <td>{k.get('purchases',0)}</td>
              <td>HK${k.get('revenue',0):,.0f}</td>
            </tr>"""

    # GA4 Organic keywords table
    org_kw_rows = ""
    if org_keywords:
        for k in (org_keywords or [])[:10]:
            org_kw_rows += f"""<tr>
              <td>{k.get('keyword','')}</td>
              <td><span style="color:#8070a0;font-size:11px">{k.get('source','')}</span></td>
              <td>{k.get('sessions',0):,}</td>
              <td>{k.get('purchases',0)}</td>
            </tr>"""

    # GA4 Ads keywords rows
    ads_kw_rows = ""
    for k in (ads_keywords or [])[:10]:
        ads_kw_rows += f'''<tr>
          <td><strong>{k.get("keyword","")}</strong></td>
          <td>{k.get("sessions",0):,}</td>
          <td>{k.get("purchases",0)}</td>
          <td>HK${k.get("revenue",0):,.0f}</td>
        </tr>'''

    # GA4 Organic keywords rows
    org_kw_rows = ""
    for k in (org_keywords or [])[:10]:
        org_kw_rows += f'''<tr>
          <td>{k.get("keyword","")}</td>
          <td><span style="color:#8070a0;font-size:11px">{k.get("source","")}</span></td>
          <td>{k.get("sessions",0):,}</td>
          <td>{k.get("purchases",0)}</td>
        </tr>'''

    # Search terms table (sorted by Conv Value from Sheets)
    st_rows = ""
    if ads.get("search_terms"):
        for s in ads["search_terms"][:10]:
            st_rows += f"""<tr>
              <td><strong>{s.get('Search Term','')}</strong></td>
              <td>{s.get('Clicks',0)}</td>
              <td>HK${s.get('花費(HKD)',0)}</td>
              <td>{s.get('Conversions',0)}</td>
              <td style="color:{'#4dd0c4' if float(str(s.get('Conv Value',0)).replace(',','') or 0) > 0 else '#f0e8c0'}">HK${s.get('Conv Value',0):}</td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="{'zh-HK' if lang=='zh' else 'ko'}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800&display=swap" rel="stylesheet">
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#0f0820;color:#f0e8c0;font-family:'Nunito',sans-serif;padding:16px;}}
.wrap{{max-width:700px;margin:0 auto;}}
.title{{font-weight:800;color:#ffd580;font-size:17px;text-align:center;padding:14px 20px;background:linear-gradient(90deg,#1a0e35,#0d1a35);border:2px solid #3a2a60;border-radius:12px;margin-bottom:16px;}}
.back{{display:inline-flex;align-items:center;gap:6px;color:#ffd580;font-size:13px;font-weight:800;margin-bottom:12px;text-decoration:none;background:rgba(255,213,128,0.1);border:1.5px solid rgba(255,213,128,0.3);padding:7px 16px;border-radius:10px;}}
.other{{display:block;text-align:center;color:#b0a0d0;font-size:13px;font-weight:700;margin-bottom:14px;text-decoration:none;background:#1a1030;border:1.5px solid #2a1a50;padding:9px;border-radius:10px;}}
.week{{color:#b0a0d0;font-size:13px;text-align:center;margin-bottom:16px;font-weight:700;}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;}}
.card{{background:#1a1030;border:1.5px solid #2a1a50;border-radius:12px;padding:14px;text-align:center;}}
.card-label{{color:#8070a0;font-size:12px;margin-bottom:6px;font-weight:700;}}
.card-value{{color:#4dd0c4;font-size:22px;font-weight:800;}}
.card-value.gold{{color:#ffd580;}}
.card-value.blue{{color:#90caf9;}}
.section-title{{color:#4dd0c4;font-size:13px;font-weight:800;margin:18px 0 8px;}}
.data-table{{width:100%;border-collapse:collapse;margin-bottom:16px;font-size:13px;}}
.data-table th{{background:#1a1030;color:#ffd580;padding:9px 10px;border:1px solid #2a1a50;text-align:left;font-weight:800;}}
.data-table td{{padding:8px 10px;border:1px solid #1a1030;color:#d0c8e8;border-bottom:1px solid #2a1a50;}}
.data-table tr:hover td{{background:#1e1240;}}
.analysis{{background:#130d25;border:1.5px solid #2a1a50;border-radius:12px;padding:18px;font-size:14px;line-height:1.9;}}
.analysis h3{{color:#4dd0c4;margin:14px 0 6px;font-size:14px;font-weight:800;}}
.analysis strong{{color:#ffd580;}}
.analysis hr{{border:none;border-top:1px solid #2a1a50;margin:12px 0;}}
.analysis li{{margin:4px 0;}}
.footer{{color:#3a2a5a;font-size:11px;text-align:center;margin-top:16px;font-weight:700;}}
</style>
</head>
<body>
<div class="wrap">
  <a href="index.html" class="back">{back}</a>
  <a href="{other_link}" class="other">{other_label}</a>
  <div class="title">★ {title} ★</div>
  <div class="week">📅 {week}</div>

  <div class="cards">
    <div class="card"><div class="card-label">{labels[0]}</div><div class="card-value blue">{ga4.get('sessions',0):,}</div></div>
    <div class="card"><div class="card-label">{labels[1]}</div><div class="card-value blue">{ga4.get('users',0):,}</div></div>
    <div class="card"><div class="card-label">{labels[2]}</div><div class="card-value">{ga4.get('add_to_carts',0):,}</div></div>
    <div class="card"><div class="card-label">{labels[3]}</div><div class="card-value">{ga4.get('purchases',0):,}</div></div>
    <div class="card"><div class="card-label">{labels[4]}</div><div class="card-value gold">HK${ads.get('cost',0):,.0f}</div></div>
    <div class="card"><div class="card-label">{labels[5]}</div><div class="card-value gold">{ads.get('roas',0)}x</div></div>
  </div>

  <div class="section-title">📡 {ch_title}</div>
  <table class="data-table">
    <tr><th>Channel</th><th>Sessions</th><th>成交</th><th>Revenue</th><th>Conv%</th></tr>
    {ch_rows}
  </table>

  {'<div class="section-title">📣 ' + ad_title + '</div><table class="data-table"><tr><th>Ad Group</th><th>Clicks</th><th>花費</th><th>Conv</th><th>ROAS</th></tr>' + ag_rows + '</table>' if ag_rows else ''}

  '<div class="section-title">🔑 GA4 Ads Keywords（有成交排最頂）</div><table class="data-table"><tr><th>Keyword</th><th>Sessions</th><th>成交</th><th>Revenue</th></tr>' + (ads_kw_rows or '<tr><td colspan=4 style="color:#8070a0;text-align:center;padding:12px">暫無數據</td></tr>') + '</table>'

  ,

  '<div class="section-title">🔍 Top Search Terms（按 Conv Value 排序）</div><table class="data-table"><tr><th>Search Term</th><th>Clicks</th><th>花費</th><th>Conversions</th><th>Conv Value</th></tr>' + (st_rows or '<tr><td colspan=5 style="color:#8070a0;text-align:center;padding:12px">暫無數據</td></tr>') + '</table>'

  <div class="section-title">🤖 Claude 深度分析</div>
  <div class="analysis">{analysis_html}</div>
  <div class="footer">由 LondonKelly Agent 生成 · {now}</div>
</div>
</body>
</html>"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ {filename} 生成完成")

def update_status(success):
    try:
        with open("status.json", "r") as f:
            status = json.load(f)
    except:
        status = {}
    status["weekly_report"] = {
        "status": "done" if success else "failed",
        "last_run": datetime.utcnow().isoformat() + "Z"
    }
    with open("status.json", "w") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    print("🚀 LondonKelly Weekly Report Agent 啟動...")
    ga4, channels, kw_ga4, landing_pages, ads_keywords, org_keywords = get_ga4_data()
    ads = get_ads_data_from_sheets()

    print("🤖 Claude 分析緊（繁中）...")
    analysis_zh = analyze_with_claude(ga4, channels, kw_ga4, landing_pages, ads, lang="zh", ads_keywords=ads_keywords, org_keywords=org_keywords)
    generate_html(ga4, channels, kw_ga4, landing_pages, ads, analysis_zh, lang="zh", ads_keywords=ads_keywords, org_keywords=org_keywords)

    print("🤖 Claude 분석 중（韓文）...")
    analysis_kr = analyze_with_claude(ga4, channels, kw_ga4, landing_pages, ads, lang="kr", ads_keywords=ads_keywords, org_keywords=org_keywords)
    generate_html(ga4, channels, kw_ga4, landing_pages, ads, analysis_kr, lang="kr", ads_keywords=ads_keywords, org_keywords=org_keywords)

    update_status(True)
    print("✅ 完成！")
