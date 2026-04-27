import requests
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
SHOPIFY_STORE    = os.environ.get("SHOPIFY_STORE", "londonkelly.myshopify.com")
SHOPIFY_TOKEN    = os.environ.get("SHOPIFY_TOKEN", "")
SHEETS_URL       = "https://docs.google.com/spreadsheets/d/1Ef5whhbOuUh-hQn8N1GGKKzSJ8UrjinXigZmkS0RiyE/edit"

# ─────────────────────────────────────────────
# TARGET BENCHMARKS (adjust as needed)
# ─────────────────────────────────────────────
TARGETS = {
    "roas_good": 4.0,       # ROAS ≥ 4x = good
    "roas_ok": 2.0,         # ROAS 2–4x = ok, watch
    "roas_bad": 1.0,        # ROAS < 1x = pause candidate
    "ctr_good": 3.0,        # CTR % threshold
    "conv_rate_good": 0.5,  # conv rate % threshold
    "budget_util_high": 85, # % budget used → consider increasing
    "spend_waste_threshold": 200,  # HKD spend with 0 conv → investigate
    "weekly_budget_total": 3000,   # HKD total weekly budget (adjust)
}

def get_date_range():
    today = datetime.now()
    start = today - timedelta(days=7)
    end = today - timedelta(days=1)
    return start, end

# ─────────────────────────────────────────────
# DATA FETCHING (unchanged from v1)
# ─────────────────────────────────────────────
def get_ga4_data():
    print("📊 拉 GA4 數據...")
    creds = service_account.Credentials.from_service_account_file(
        GA4_KEY_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)
    date_start, date_end = get_date_range()
    date_range = DateRange(
        start_date=date_start.strftime("%Y-%m-%d"),
        end_date=date_end.strftime("%Y-%m-%d")
    )

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
            "week_start": date_start.strftime("%Y-%m-%d"),
            "week_end": date_end.strftime("%Y-%m-%d"),
        }

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

    ads_keywords = []
    try:
        ads_kw_req = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[date_range],
            dimensions=[Dimension(name="sessionGoogleAdsKeyword")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="ecommercePurchases"),
                Metric(name="purchaseRevenue"),
            ],
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
        print(f"  ⚠️ Ads KW error: {e}")

    print(f"  ✅ Sessions: {overview.get('sessions',0):,}")
    return overview, channels, [], landing_pages, ads_keywords, []

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
        overview_sheet = sh.worksheet("總覽")
        overview_data = overview_sheet.get_all_records()
        latest = overview_data[-1] if overview_data else {}

        try:
            ag_sheet = sh.worksheet("Ad Groups")
            ag_data = ag_sheet.get_all_records()
        except:
            ag_data = []

        try:
            kw_sheet = sh.worksheet("Keywords")
            kw_data = kw_sheet.get_all_records()
        except:
            kw_data = []

        try:
            st_sheet = sh.worksheet("Search Terms")
            st_data = st_sheet.get_all_records()
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
        print(f"  ✅ 花費: HK${ads['cost']:,.0f} | ROAS: {ads['roas']}x | KW: {len(kw_data)} | ST: {len(st_data)}")
        return ads
    except Exception as e:
        print(f"  ⚠️ Sheets 讀取失敗: {e}")
        return {"cost": 0, "roas": "0", "clicks": 0, "impressions": 0,
                "conversions": 0, "conv_value": 0, "ctr": "0%", "week": "",
                "ad_groups": [], "keywords": [], "search_terms": []}

def get_shopify_data():
    print("🛍️ 拉 Shopify 訂單數據...")
    try:
        date_start, date_end = get_date_range()
        start = date_start.strftime("%Y-%m-%dT00:00:00+08:00")
        end = (date_end + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+08:00")
        headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/orders.json"
        params = {
            "status": "any", "created_at_min": start, "created_at_max": end,
            "limit": 250,
            "fields": "id,created_at,total_price,subtotal_price,financial_status,line_items,cancel_reason"
        }
        all_orders = []
        while url:
            resp = requests.get(url, headers=headers, params=params)
            resp.raise_for_status()
            orders = resp.json().get("orders", [])
            all_orders.extend(orders)
            link = resp.headers.get("Link", "")
            url = None
            params = None
            if 'rel="next"' in link:
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split(";")[0].strip().strip("<>")
                        break
        paid_orders = [o for o in all_orders if o.get("financial_status") in ["paid", "partially_paid"]]
        cancelled = [o for o in all_orders if o.get("cancel_reason")]
        total_revenue = sum(float(o.get("total_price", 0)) for o in paid_orders)
        total_orders = len(paid_orders)
        avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
        print(f"  ✅ 成交: {total_orders} 單 | 收入: HK${total_revenue:,.0f}")
        return {
            "orders": total_orders, "revenue": round(total_revenue, 0),
            "avg_order_value": round(avg_order_value, 0),
            "cancelled": len(cancelled), "all_orders": len(all_orders),
            "week_start": date_start.strftime("%Y-%m-%d"),
            "week_end": date_end.strftime("%Y-%m-%d"),
        }
    except Exception as e:
        print(f"  ⚠️ Shopify 拉取失敗: {e}")
        return {"orders": 0, "revenue": 0, "avg_order_value": 0, "cancelled": 0, "all_orders": 0}


# ─────────────────────────────────────────────
# MODULAR AI ANALYSIS — ONE FUNCTION PER SECTION
# ─────────────────────────────────────────────

def _call_claude(prompt, max_tokens=1500):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


def analyze_overview(ga4, ads, shopify):
    """Section 1: Overall health score + highlights"""
    print("  🤖 [1/6] 總覽分析...")
    diff_orders = shopify.get('orders', 0) - ga4.get('purchases', 0) if shopify else 0
    prompt = f"""你係 LondonKelly Google Ads 分析師。用繁體中文，emoji，手機友好格式。

【本週數據】
Sessions: {ga4.get('sessions',0):,} | Users: {ga4.get('users',0):,}
加購: {ga4.get('add_to_carts',0):,} | GA4成交: {ga4.get('purchases',0)} | GA4收入: HK${ga4.get('revenue',0):,.0f}
Shopify成交: {shopify.get('orders',0) if shopify else 'N/A'} | Shopify收入: HK${shopify.get('revenue',0) if shopify else 0:,.0f}
GA4 vs Shopify差距: {diff_orders:+d} 單
Ads花費: HK${ads.get('cost',0):,.0f} | ROAS: {ads.get('roas',0)}x | Clicks: {ads.get('clicks',0):,}
整體轉化率: {round(ga4.get('purchases',0)/max(ga4.get('sessions',1),1)*100,3)}%

請輸出：
## 📊 本週整體評分
健康度：X/10（附簡短理由）

## ✅ 本週3大亮點（每點一行，附數字）

## ⚠️ 本週3大問題（每點一行，附數字）

## 🔄 GA4 vs Shopify 差距
差距原因分析（正常/異常），一兩句說明。
"""
    return _call_claude(prompt, 800)


def analyze_channels(channels, ga4):
    """Section 2: Channel breakdown with per-channel actions"""
    print("  🤖 [2/6] Channel分析...")
    ch_lines = "\n".join([
        f"  {c['channel']}: {c['sessions']:,} sessions | {c['purchases']} 成交 | HK${c['revenue']:,.0f} | conv {c['conv_rate']}%"
        for c in channels[:8]
    ])
    prompt = f"""你係 LondonKelly 數據分析師，用繁體中文，emoji，手機格式。

【Channel數據】
{ch_lines}
總Sessions: {ga4.get('sessions',0):,}

對每個主要channel，用以下格式：
▸ **[Channel名]** — {'{'}sessions{'}'}session | conv {'{'}%{'}'}
  狀態：🟢好 / 🟡一般 / 🔴差
  原因：一句說明
  行動：具體下週要做咩（或「維持」）

最後：
## 💡 Channel整體建議（1-2點）
"""
    return _call_claude(prompt, 1000)


def analyze_ad_groups(ad_groups, ads):
    """Section 3: Per ad group ROAS analysis + budget/bid actions"""
    print("  🤖 [3/6] Ad Group分析...")
    if not ad_groups:
        return "<p style='color:#8070a0'>暫無Ad Group數據</p>"

    sorted_ag = sorted(ad_groups, key=lambda x: float(str(x.get("花費(HKD)",0)).replace(",","")), reverse=True)
    ag_lines = "\n".join([
        f"  [{a.get('Ad Group','')[:35]}]: 花費HK${a.get('花費(HKD)',0)} | Clicks:{a.get('Clicks',0)} | Conv:{a.get('Conversions',0)} | ConvValue:HK${a.get('Conv Value', a.get('conv_value',0))} | ROAS:{a.get('ROAS','0x')}"
        for a in sorted_ag[:12]
    ])

    total_cost = ads.get('cost', 0)
    prompt = f"""你係 LondonKelly Google Ads 優化師，用繁體中文，emoji，手機格式。
目標ROAS: {TARGETS['roas_good']}x+ = 好 | {TARGETS['roas_ok']}-{TARGETS['roas_good']}x = 觀察 | <{TARGETS['roas_ok']}x = 差
本週總花費: HK${total_cost:,.0f}

【Ad Group數據（花費排序）】
{ag_lines}

對每個Ad Group，輸出：
▸ **[名稱]** ROAS:[X]x | 花費:HK$[X] | Conv:[X]
  評級：🟢[ROAS≥{TARGETS['roas_good']}x] / 🟡[{TARGETS['roas_ok']}-{TARGETS['roas_good']}x] / 🔴[<{TARGETS['roas_ok']}x]
  診斷：[一句原因]
  行動：[具體操作 — 例: 加預算+20% / 降Bid 15% / Pause / 加Negative KW / 維持]

最後：
## 💰 預算重新分配建議
列出：哪些Ad Group加錢 / 哪些減錢 / 哪些Pause，及金額。
"""
    return _call_claude(prompt, 1500)


def analyze_keywords(keywords, search_terms):
    """Section 4: Keyword performance + add/pause/negative suggestions"""
    print("  🤖 [4/6] Keywords分析...")
    if not keywords and not search_terms:
        return "<p style='color:#8070a0'>暫無Keywords數據</p>"

    kw_lines = "\n".join([
        f"  [{k.get('Keyword','')[:40]}] ({k.get('Match Type', k.get('match_type','?'))}): Clicks:{k.get('Clicks',0)} | 花費:HK${k.get('花費(HKD)',0)} | Conv:{k.get('Conversions',0)} | ConvValue:HK${k.get('Conv Value', k.get('conv_value',0))} | CPC:HK${k.get('CPC', k.get('Avg CPC','?'))} | QS:{k.get('Quality Score','?')}"
        for k in keywords[:15]
    ])

    st_lines = "\n".join([
        f"  '{s.get('Search Term','')}': Clicks:{s.get('Clicks',0)} | Conv:{s.get('Conversions',0)} | 花費:HK${s.get('花費(HKD)',0)}"
        for s in search_terms[:20]
    ])

    prompt = f"""你係 LondonKelly Google Ads Keywords 優化師，用繁體中文，emoji。
LondonKelly = 英國奢侈品代購，目標: 香港/台灣客戶。

【現有Keywords表現】
{kw_lines if kw_lines else '(無數據)'}

【本週Search Terms（觸發嘅實際搜索）】
{st_lines if st_lines else '(無數據)'}

輸出以下4個部分：

## 🏆 高效Keywords（建議加Bid）
格式: • [keyword] — ROAS佳/高Conv，建議加Bid +X%

## ⚰️ 低效Keywords（建議Pause或降Bid）
格式: • [keyword] — 原因（例: {TARGETS['spend_waste_threshold']}+HKD 0成交），建議: Pause / 降Bid X%

## ➕ 建議新增Keywords（從Search Terms提取）
格式: • [keyword] | [Exact/Phrase] | 原因（有X次轉換/高相關）

## 🚫 建議新增Negative Keywords
格式: • [keyword] — 原因（例: 搜fake/dupe/山寨，浪費預算）

每部分最多5個，有數字支持。
"""
    return _call_claude(prompt, 1200)


def analyze_search_terms(search_terms):
    """Section 5: Search term audit — add/negative/watch list"""
    print("  🤖 [5/6] Search Terms審核...")
    if not search_terms:
        return "<p style='color:#8070a0'>暫無Search Terms數據</p>"

    all_st = "\n".join([
        f"  '{s.get('Search Term','')}': Clicks:{s.get('Clicks',0)} | Conv:{s.get('Conversions',0)} | 花費:HK${s.get('花費(HKD)',0)} | Impressions:{s.get('Impressions',0)}"
        for s in search_terms[:25]
    ])

    prompt = f"""你係 LondonKelly Google Ads Search Term 審核員，用繁體中文，emoji。
LondonKelly = 英國奢侈品代購（Loewe, Burberry, Mulberry等），絕非 fake/dupe/replica。

【本週所有Search Terms】
{all_st}

將每個search term分類，輸出3個表格：

## ✅ 建議加入為正式Keyword
| Search Term | 建議Match Type | 建議加入哪個Ad Group | 原因 |

## 🚫 建議加入Negative Keywords（立即阻止）
| Search Term | 原因 |

## 👀 觀察名單（未夠數據，下週再睇）
| Search Term | 現況 | 觀察什麼 |

唔使包所有，只列最重要/最需要行動嘅。
"""
    return _call_claude(prompt, 1200)


def analyze_action_plan(ga4, ads, shopify, channels):
    """Section 6: Prioritized weekly action plan"""
    print("  🤖 [6/6] 行動計劃...")
    paid_ch = next((c for c in channels if 'Paid' in c.get('channel','')), None)
    organic_ch = next((c for c in channels if 'Organic' in c.get('channel','')), None)

    prompt = f"""你係 LondonKelly 數字行銷顧問，用繁體中文，emoji。

【本週核心數字】
Ads花費: HK${ads.get('cost',0):,.0f} | ROAS: {ads.get('roas',0)}x
Sessions: {ga4.get('sessions',0):,} | 轉化率: {round(ga4.get('purchases',0)/max(ga4.get('sessions',1),1)*100,3)}%
Shopify成交: {shopify.get('orders',0) if shopify else 'N/A'} 單 | 收入: HK${shopify.get('revenue',0) if shopify else 0:,.0f}
Paid Search: {paid_ch.get('sessions',0) if paid_ch else '?'} sessions, conv {paid_ch.get('conv_rate',0) if paid_ch else '?'}%
Organic: {organic_ch.get('sessions',0) if organic_ch else '?'} sessions, conv {organic_ch.get('conv_rate',0) if organic_ch else '?'}%

根據以上數據，輸出：

## 🚀 下週行動計劃（按優先級）

格式（每項一行）：
🔴【立即做】[操作] — [原因附數字] — [預期效果]
🟡【本週內】[操作] — [原因附數字] — [預期效果]
🟢【有時間做】[操作] — [原因附數字] — [預期效果]

最少8個行動，涵蓋：Keywords調整、預算調配、Negative KW、Landing Page優化、新廣告方向。

## 📅 下週監察重點
3個最需要密切留意嘅指標或趨勢。
"""
    return _call_claude(prompt, 1000)


# ─────────────────────────────────────────────
# HTML GENERATION
# ─────────────────────────────────────────────

def md2html(t):
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
    t = re.sub(r'##+ (.+)', r'<h3 class="sec-h3">\1</h3>', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong class="gold">\1</strong>', t)
    t = re.sub(r'^▸ (.+)', r'<div class="ag-item">▸ \1</div>', t, flags=re.MULTILINE)
    t = re.sub(r'^• (.+)', r'<li>\1</li>', t, flags=re.MULTILINE)
    t = re.sub(r'🔴', r'<span class="pill red">🔴</span>', t)
    t = re.sub(r'🟡', r'<span class="pill yellow">🟡</span>', t)
    t = re.sub(r'🟢', r'<span class="pill green">🟢</span>', t)
    t = re.sub(r'---+', '<hr class="divider">', t)
    t = t.replace('\n', '<br>')
    return t


def generate_section(icon, title, content_html, collapsible=True):
    """Generate a collapsible section card"""
    sid = title.replace(' ', '_').replace('/', '_')
    if collapsible:
        return f"""
<details class="section-card" open>
  <summary class="section-summary">{icon} {title}</summary>
  <div class="section-body">{content_html}</div>
</details>"""
    return f"""
<div class="section-card">
  <div class="section-summary">{icon} {title}</div>
  <div class="section-body">{content_html}</div>
</div>"""


def generate_html_v2(ga4, channels, ads, shopify,
                     analysis_overview, analysis_channels,
                     analysis_ad_groups, analysis_keywords,
                     analysis_search_terms, analysis_action_plan,
                     ads_keywords, lang="zh"):
    week = f"{ga4.get('week_start','')} ~ {ga4.get('week_end','')}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if lang == "zh":
        title = "LondonKelly 週報"
        filename = "report.html"
        other_link, other_label = "report_kr.html", "🇰🇷 한국어"
    else:
        title = "LondonKelly 주간 보고서"
        filename = "report_kr.html"
        other_link, other_label = "report.html", "🇨🇳 繁中"

    # Summary cards
    roas_val = float(str(ads.get('roas', 0)).replace('x', '') or 0)
    roas_color = '#4dd0c4' if roas_val >= TARGETS['roas_good'] else ('#ffe08a' if roas_val >= TARGETS['roas_ok'] else '#f48fb1')
    diff_orders = (shopify.get('orders', 0) - ga4.get('purchases', 0)) if shopify else 0

    # Channel table
    ch_rows = ""
    for c in channels[:8]:
        cr_color = '#4dd0c4' if c['conv_rate'] >= TARGETS['conv_rate_good'] else '#f48fb1'
        ch_rows += f"<tr><td><strong>{c['channel']}</strong></td><td>{c['sessions']:,}</td><td>{c['purchases']}</td><td>HK${c['revenue']:,.0f}</td><td style='color:{cr_color}'>{c['conv_rate']}%</td></tr>"

    # Ad group table (top 8 by spend)
    ag_rows = ""
    if ads.get("ad_groups"):
        top_ag = sorted(ads["ad_groups"], key=lambda x: float(str(x.get("花費(HKD)",0)).replace(",","")), reverse=True)[:8]
        for a in top_ag:
            rv = str(a.get('ROAS','0x')).replace('x','')
            try:
                rf = float(rv)
                rc = '#4dd0c4' if rf >= TARGETS['roas_good'] else ('#ffe08a' if rf >= TARGETS['roas_ok'] else '#f48fb1')
            except:
                rc = '#b0a0d0'
            try:
                cv = float(str(a.get('Conv Value', a.get('conv_value', 0))).replace(',',''))
                cv_fmt = f"HK${cv:,.0f}"
            except:
                cv_fmt = "HK$0"
            ag_rows += f"<tr><td><strong>{a.get('Ad Group','')[:28]}</strong></td><td>{a.get('Clicks',0)}</td><td>HK${a.get('花費(HKD)',0)}</td><td>{a.get('Conversions',0)}</td><td style='color:#ffe08a'>{cv_fmt}</td><td style='color:{rc}'><strong>{a.get('ROAS','0x')}</strong></td></tr>"

    # Keywords table
    kw_rows = ""
    if ads.get("keywords"):
        for k in ads["keywords"][:10]:
            conv = int(str(k.get('Conversions', 0)).replace(',', '') or 0)
            conv_color = '#4dd0c4' if conv > 0 else '#f48fb1'
            kw_rows += f"<tr><td>{k.get('Keyword','')[:35]}</td><td style='font-size:11px;color:#8070a0'>{k.get('Match Type', k.get('match_type','?'))}</td><td>{k.get('Clicks',0)}</td><td>HK${k.get('花費(HKD)',0)}</td><td style='color:{conv_color}'>{conv}</td><td>HK${k.get('Conv Value', k.get('conv_value',0))}</td><td>HK${k.get('CPC', k.get('Avg CPC','?'))}</td></tr>"

    # Search terms table
    st_rows = ""
    if ads.get("search_terms"):
        for s in ads["search_terms"][:15]:
            conv = int(str(s.get('Conversions', 0)).replace(',', '') or 0)
            conv_color = '#4dd0c4' if conv > 0 else ('#ffe08a' if int(str(s.get('Clicks',0)).replace(',','') or 0) >= 3 else '#d0c8e8')
            st_rows += f"<tr><td>{s.get('Search Term','')[:40]}</td><td>{s.get('Clicks',0)}</td><td>HK${s.get('花費(HKD)',0)}</td><td style='color:{conv_color}'>{conv}</td></tr>"

    # GA4 Ads KW table
    ga4kw_rows = ""
    for k in (ads_keywords or [])[:8]:
        ga4kw_rows += f"<tr><td><strong>{k.get('keyword','')}</strong></td><td>{k.get('sessions',0):,}</td><td>{k.get('purchases',0)}</td><td>HK${k.get('revenue',0):,.0f}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f0820;color:#f0e8c0;font-family:'Nunito',sans-serif;padding:12px;font-size:14px}}
.wrap{{max-width:720px;margin:0 auto}}
.top-nav{{display:flex;gap:8px;margin-bottom:12px;align-items:center}}
.back{{flex:1;color:#ffd580;font-size:13px;font-weight:800;text-decoration:none;background:rgba(255,213,128,.1);border:1.5px solid rgba(255,213,128,.3);padding:7px 14px;border-radius:10px;text-align:center}}
.lang-switch{{color:#b0a0d0;font-size:13px;font-weight:700;text-decoration:none;background:#1a1030;border:1.5px solid #2a1a50;padding:7px 14px;border-radius:10px}}
.report-title{{font-weight:800;color:#ffd580;font-size:17px;text-align:center;padding:14px;background:linear-gradient(90deg,#1a0e35,#0d1a35);border:2px solid #3a2a60;border-radius:12px;margin-bottom:8px}}
.week-label{{color:#b0a0d0;font-size:12px;text-align:center;margin-bottom:14px;font-weight:700}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}}
.card{{background:#1a1030;border:1.5px solid #2a1a50;border-radius:12px;padding:12px;text-align:center}}
.card-label{{color:#8070a0;font-size:11px;margin-bottom:4px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}}
.card-value{{font-size:20px;font-weight:800}}
.cv-teal{{color:#4dd0c4}}.cv-gold{{color:#ffd580}}.cv-blue{{color:#90caf9}}.cv-pink{{color:#ff8fab}}
.section-card{{background:#130d25;border:1.5px solid #2a1a50;border-radius:12px;margin-bottom:10px;overflow:hidden}}
.section-summary{{padding:12px 16px;cursor:pointer;font-weight:800;font-size:13px;color:#ffd580;list-style:none;background:#1a1030;user-select:none;display:flex;align-items:center;gap:6px}}
.section-summary::-webkit-details-marker{{display:none}}
details[open] .section-summary{{border-bottom:1px solid #2a1a50}}
.section-body{{padding:14px 16px;font-size:13px;line-height:1.8}}
.data-table{{width:100%;border-collapse:collapse;margin:8px 0 4px;font-size:12px}}
.data-table th{{background:#1a1030;color:#ffd580;padding:7px 8px;border:1px solid #2a1a50;text-align:left;font-weight:800;font-size:11px}}
.data-table td{{padding:6px 8px;border-bottom:1px solid #1a1030;color:#d0c8e8}}
.data-table tr:hover td{{background:#1e1240}}
.sec-h3{{color:#4dd0c4;margin:12px 0 6px;font-size:13px;font-weight:800}}
.gold{{color:#ffd580}}
.ag-item{{background:#1a1030;border-left:3px solid #3a2a60;padding:8px 10px;margin:6px 0;border-radius:0 8px 8px 0;font-size:12px;line-height:1.7}}
li{{margin:4px 0;padding-left:4px}}
.divider{{border:none;border-top:1px solid #2a1a50;margin:10px 0}}
.pill{{font-size:12px}}
.pill.red{{color:#f48fb1}}.pill.yellow{{color:#ffe08a}}.pill.green{{color:#4dd0c4}}
.tab-nav{{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}}
.tab-btn{{padding:6px 14px;border-radius:8px;border:1.5px solid #2a1a50;background:#1a1030;color:#b0a0d0;font-size:12px;font-weight:700;cursor:pointer;transition:.2s}}
.tab-btn.active{{background:#2a1a50;color:#ffd580;border-color:#4a3a70}}
.footer{{color:#3a2a5a;font-size:11px;text-align:center;margin-top:16px;font-weight:700}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top-nav">
    <a href="index.html" class="back">← 返回辦公室</a>
    <a href="{other_link}" class="lang-switch">{other_label}</a>
  </div>
  <div class="report-title">★ {title} ★</div>
  <div class="week-label">📅 {week} · 生成於 {now}</div>

  <!-- Summary Cards -->
  <div class="cards">
    <div class="card"><div class="card-label">Sessions</div><div class="card-value cv-blue">{ga4.get('sessions',0):,}</div></div>
    <div class="card"><div class="card-label">Users</div><div class="card-value cv-blue">{ga4.get('users',0):,}</div></div>
    <div class="card"><div class="card-label">加購物車</div><div class="card-value cv-teal">{ga4.get('add_to_carts',0):,}</div></div>
    <div class="card"><div class="card-label">Shopify成交</div><div class="card-value cv-pink">{shopify.get('orders',0) if shopify else 'N/A'}</div></div>
    <div class="card"><div class="card-label">{lbl_cost}</div><div class="card-value cv-gold">HK${ads.get('cost',0):,.0f}</div></div>
    <div class="card"><div class="card-label">{lbl_roas}</div><div class="card-value" style="color:{roas_color}">{ads.get('roas',0)}x</div></div>
    <div class="card"><div class="card-label">Shopify收入</div><div class="card-value cv-gold">HK${shopify.get('revenue',0) if shopify else 0:,.0f}</div></div>
    <div class="card"><div class="card-label">GA4 vs Shopify</div><div class="card-value" style="color:{'#f48fb1' if abs(diff_orders)>3 else '#4dd0c4'}">{diff_orders:+d} 單</div></div>
  </div>

  <!-- Section 1: Overview -->
  {generate_section("📊", "本週整體評分 + 亮點問題", md2html(analysis_overview))}

  <!-- Section 2: Channels with raw data + AI -->
  {generate_section("📡", "流量來源分析 + 行動建議", f'''
    <table class="data-table">
      <tr><th>Channel</th><th>Sessions</th><th>成交</th><th>Revenue</th><th>Conv%</th></tr>
      {ch_rows}
    </table>
    {md2html(analysis_channels)}
  ''')}

  <!-- Section 3: Ad Groups -->
  {generate_section("📣", "Ad Group 表現 + 預算調配", f'''
    {'<table class="data-table"><tr><th>Ad Group</th><th>Clicks</th><th>花費</th><th>Conv</th><th>Conv Value</th><th>ROAS</th></tr>' + ag_rows + '</table>' if ag_rows else '<p style="color:#8070a0;padding:8px">暫無Ad Group數據</p>'}
    {md2html(analysis_ad_groups)}
  ''')}

  <!-- Section 4: Keywords -->
  {generate_section("🔑", "Keywords 深度分析 + 新增/暫停建議", f'''
    {'<table class="data-table"><tr><th>Keyword</th><th>Match</th><th>Clicks</th><th>花費</th><th>Conv</th><th>ConvValue</th><th>CPC</th></tr>' + kw_rows + '</table>' if kw_rows else ''}
    {md2html(analysis_keywords)}
    {'<h3 class="sec-h3">🔑 GA4 Ads Keywords（有成交排頂）</h3><table class="data-table"><tr><th>Keyword</th><th>Sessions</th><th>成交</th><th>Revenue</th></tr>' + ga4kw_rows + '</table>' if ga4kw_rows else ''}
  ''')}

  <!-- Section 5: Search Terms -->
  {generate_section("🔍", "Search Terms 審核 — 加入/Negative/觀察", f'''
    {'<table class="data-table"><tr><th>Search Term</th><th>Clicks</th><th>花費</th><th>Conv</th></tr>' + st_rows + '</table>' if st_rows else '<p style="color:#8070a0;padding:8px">暫無Search Term數據</p>'}
    {md2html(analysis_search_terms)}
  ''')}

  <!-- Section 6: Action Plan -->
  {generate_section("🚀", "下週行動計劃（按優先級）", md2html(analysis_action_plan))}

  <div class="footer">由 LondonKelly Agent v2 生成 · {now}</div>
</div>
</body>
</html>"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ {filename} 生成完成")


def generate_actions_html(ga4, ads, shopify, analysis_ad_groups, analysis_keywords, analysis_search_terms, analysis_action_plan, lang="zh"):
    """Generate standalone actions.html / actions_kr.html"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    week = f"{ga4.get('week_start','')} ~ {ga4.get('week_end','')}"

    if lang == "zh":
        filename, other_link, other_label = "actions.html", "actions_kr.html", "\U0001f1f0\U0001f1f7 한국어"
        report_link, page_title = "report.html", "LondonKelly \u884c\u52d5\u6e05\u55ae"
        title_text = f"\U0001f4cb \u884c\u52d5\u6e05\u55ae \u2014 {week}"
        back_text, report_text = "\u2190 \u8fd4\u56de\u8fa6\u516c\u5a92", "\U0001f4ca \u5b8c\u6574\u9031\u5831"
        sec_ag   = "\U0001f4e3 Ad Group ROAS \u2014 \u672c\u9031"
        sec_kw   = "\U0001f511 Keywords \u2014 \u52a0\u5165 / Pause / Negative"
        sec_st   = "\U0001f50d Search Terms \u5be9\u6838"
        sec_plan = "\U0001f680 \u4e0b\u9031\u884c\u52d5\u8a08\u5283\uff08\u6309\u512a\u5148\u7d1a\uff09"
        lbl_roas, lbl_cost, lbl_orders, lbl_revenue = "ROAS", "Ads\u82b1\u8cbb", "\u6210\u4ea4", "\u6536\u5165"
        tbl_ag_heads = "<th>Ad Group</th><th>ROAS</th><th>\u82b1\u8cbb</th><th>Conv</th><th>Conv Value</th><th>\u884c\u52d5</th>"
        no_ag, footer_txt, gen_txt = "\u66ab\u7121Ad Group\u6578\u64da", "\u7531 LondonKelly Agent \u751f\u6210", "\u751f\u6210\u65bc"
    else:
        filename, other_link, other_label = "actions_kr.html", "actions.html", "\U0001f1e8\U0001f1f3 \u7e41\u4e2d"
        report_link, page_title = "report_kr.html", "LondonKelly \uc561\uc158 \ub9ac\uc2a4\ud2b8"
        title_text = f"\U0001f4cb \uc561\uc158 \ub9ac\uc2a4\ud2b8 \u2014 {week}"
        back_text, report_text = "\u2190 \uc0ac\ubb34\uc2e4\ub85c", "\U0001f4ca \uc804\uccb4 \uc8fc\uac04\ubcf4\uace0"
        sec_ag   = "\U0001f4e3 Ad Group ROAS \u2014 \uc774\ubc88 \uc8fc"
        sec_kw   = "\U0001f511 Keywords \u2014 \ucd94\uac00 / Pause / Negative"
        sec_st   = "\U0001f50d Search Terms \uac80\ud1a0"
        sec_plan = "\U0001f680 \ub2e4\uc74c \uc8fc \uc561\uc158 \ud50c\ub7dc (\uc6b0\uc120\uc21c\uc704)"
        lbl_roas, lbl_cost, lbl_orders, lbl_revenue = "ROAS", "\uad11\uace0\ube44", "\uc8fc\ubb38", "\ub9e4\ucd9c"
        tbl_ag_heads = "<th>Ad Group</th><th>ROAS</th><th>\uc9c0\ucd9c</th><th>Conv</th><th>Conv Value</th><th>\uc561\uc158</th>"
        no_ag, footer_txt, gen_txt = "Ad Group \ub370\uc774\ud130 \uc5c6\uc74c", "LondonKelly Agent \uc0dd\uc131", "\uc0dd\uc131\uc77c\uc2dc"

    # ROAS colour
    roas_val = float(str(ads.get('roas', 0)).replace('x', '') or 0)
    roas_color = '#4dd0c4' if roas_val >= TARGETS['roas_good'] else ('#ffe08a' if roas_val >= TARGETS['roas_ok'] else '#f48fb1')

    # Ad group rows — sorted by spend desc, colour by ROAS
    ag_rows = ""
    if ads.get("ad_groups"):
        sorted_ag = sorted(ads["ad_groups"], key=lambda x: float(str(x.get("花費(HKD)",0)).replace(",","")), reverse=True)[:8]
        for a in sorted_ag:
            rv = str(a.get('ROAS','0x')).replace('x','')
            try:
                rf = float(rv)
                badge = ('b-green', '+Budget / Maintain') if rf >= TARGETS['roas_good'] else (('b-amber', 'Watch / -Bid') if rf >= TARGETS['roas_ok'] else ('b-red', 'Pause / Review'))
                bar_pct = min(int(rf / 8 * 100), 100)
                bar_col = '#4dd0c4' if rf >= TARGETS['roas_good'] else ('#ffe08a' if rf >= TARGETS['roas_ok'] else '#f48fb1')
            except:
                badge = ('b-gray', '—'); bar_pct = 0; bar_col = '#666'
            try:
                cv = float(str(a.get('Conv Value', a.get('conv_value', 0))).replace(',',''))
                cv_fmt = f"HK${cv:,.0f}"
            except:
                cv_fmt = "HK$0"
            ag_rows += f"""<tr>
              <td><strong>{a.get('Ad Group','')[:28]}</strong></td>
              <td>
                <span style="font-weight:700;color:{bar_col}">{a.get('ROAS','0x')}</span>
                <div style="height:4px;border-radius:2px;background:#1a1030;margin-top:3px;overflow:hidden"><div style="height:100%;width:{bar_pct}%;background:{bar_col};border-radius:2px"></div></div>
              </td>
              <td>HK${a.get('花費(HKD)',0)}</td>
              <td>{a.get('Conversions',0)}</td>
              <td style="color:#ffe08a">{cv_fmt}</td>
              <td><span class="badge {badge[0]}">{badge[1]}</span></td>
            </tr>"""

    # Keyword suggestion rows from AI analysis — parse from text
    # We'll show raw AI output in styled sections
    ag_html   = md2html(analysis_ad_groups)
    kw_html   = md2html(analysis_keywords)
    st_html   = md2html(analysis_search_terms)
    plan_html = md2html(analysis_action_plan)

    html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f0820;color:#f0e8c0;font-family:'Nunito',sans-serif;padding:12px;font-size:13px}}
.wrap{{max-width:720px;margin:0 auto}}
.top-nav{{display:flex;gap:8px;margin-bottom:12px}}
.back{{flex:1;color:#ffd580;font-size:13px;font-weight:800;text-decoration:none;background:rgba(255,213,128,.1);border:1.5px solid rgba(255,213,128,.3);padding:7px 14px;border-radius:10px;text-align:center}}
.report-link{{color:#b0a0d0;font-size:13px;font-weight:700;text-decoration:none;background:#1a1030;border:1.5px solid #2a1a50;padding:7px 14px;border-radius:10px}}
.title{{font-weight:800;color:#ffd580;font-size:16px;text-align:center;padding:12px;background:linear-gradient(90deg,#1a0e35,#0d1a35);border:2px solid #3a2a60;border-radius:12px;margin-bottom:8px}}
.week{{color:#b0a0d0;font-size:12px;text-align:center;margin-bottom:14px;font-weight:700}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}}
.card{{background:#1a1030;border:1.5px solid #2a1a50;border-radius:10px;padding:10px;text-align:center}}
.card-label{{color:#8070a0;font-size:10px;margin-bottom:3px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}}
.card-value{{font-size:18px;font-weight:800}}
details{{background:#130d25;border:1.5px solid #2a1a50;border-radius:12px;margin-bottom:10px;overflow:hidden}}
summary{{padding:11px 16px;cursor:pointer;font-weight:800;font-size:13px;color:#ffd580;list-style:none;background:#1a1030;user-select:none}}
summary::-webkit-details-marker{{display:none}}
details[open] summary{{border-bottom:1px solid #2a1a50}}
.sec-body{{padding:14px 16px;font-size:13px;line-height:1.8}}
table{{width:100%;border-collapse:collapse;font-size:12px;margin:8px 0}}
th{{background:#1a1030;color:#ffd580;padding:7px 8px;border:1px solid #2a1a50;text-align:left;font-weight:800;font-size:11px}}
td{{padding:7px 8px;border-bottom:1px solid #1a1030;color:#d0c8e8}}
.badge{{display:inline-block;font-size:11px;font-weight:700;padding:2px 9px;border-radius:10px}}
.b-green{{background:#1a3320;color:#4dd0c4;border:1px solid #2a5535}}.b-amber{{background:#2a1e08;color:#ffe08a;border:1px solid #5a3a10}}.b-red{{background:#2a0e10;color:#f48fb1;border:1px solid #5a2030}}.b-gray{{background:#1a1030;color:#8070a0;border:1px solid #2a2040}}.b-blue{{background:#0e1a2a;color:#90caf9;border:1px solid #1a3050}}
.action-row{{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid #1a1030}}
.action-row:last-child{{border-bottom:none}}
.dot{{width:8px;height:8px;border-radius:50%;margin-top:5px;flex-shrink:0}}
.dot-red{{background:#f48fb1}}.dot-amber{{background:#ffe08a}}.dot-green{{background:#4dd0c4}}
.action-text{{flex:1;line-height:1.7}}
.sec-h3{{color:#4dd0c4;margin:12px 0 6px;font-size:13px;font-weight:800}}
.gold{{color:#ffd580}}
.ag-item{{background:#1a1030;border-left:3px solid #3a2a60;padding:7px 10px;margin:5px 0;border-radius:0 8px 8px 0;font-size:12px;line-height:1.7}}
li{{margin:4px 0;padding-left:4px}}
.divider{{border:none;border-top:1px solid #2a1a50;margin:10px 0}}
.footer{{color:#3a2a5a;font-size:11px;text-align:center;margin-top:14px;font-weight:700}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top-nav">
    <a href="index.html" class="back">{back_text}</a>
    <a href="{other_link}" class="report-link">{other_label}</a>
    <a href="{report_link}" class="report-link">{{report_text}}</a>
  </div>
  <div class="title">{title_text}</div>
  <div class="week">{{gen_txt}} {now}</div>

  <!-- Snapshot cards -->
  <div class="cards">
    <div class="card">
      <div class="card-label">{lbl_roas}</div>
      <div class="card-value" style="color:{roas_color}">{ads.get('roas',0)}x</div>
    </div>
    <div class="card">
      <div class="card-label">{lbl_cost}</div>
      <div class="card-value" style="color:#ffe08a">HK${ads.get('cost',0):,.0f}</div>
    </div>
    <div class="card">
      <div class="card-label">{lbl_orders}</div>
      <div class="card-value" style="color:#ff8fab">{shopify.get('orders',0) if shopify else ga4.get('purchases',0)}</div>
    </div>
    <div class="card">
      <div class="card-label">{lbl_revenue}</div>
      <div class="card-value" style="color:#4dd0c4">HK${shopify.get('revenue',0) if shopify else ga4.get('revenue',0):,.0f}</div>
    </div>
  </div>

  <!-- Ad Group ROAS table -->
  <details open>
    <summary>{sec_ag}</summary>
    <div class="sec-body">
      {{'<table><tr>' + tbl_ag_heads + '</tr>' + ag_rows + '</table>' if ag_rows else '<p style="color:#8070a0;padding:4px">' + no_ag + '</p>'}}
      {ag_html}
    </div>
  </details>

  <!-- Keywords -->
  <details open>
    <summary>{sec_kw}</summary>
    <div class="sec-body">{kw_html}</div>
  </details>

  <!-- Search Terms -->
  <details>
    <summary>{sec_st}</summary>
    <div class="sec-body">{st_html}</div>
  </details>

  <!-- Action Plan -->
  <details open>
    <summary>{sec_plan}</summary>
    <div class="sec-body">{plan_html}</div>
  </details>

  <div class="footer">{footer_txt} · {now}</div>
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


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 LondonKelly Weekly Report v2 啟動...")

    # Fetch data
    ga4, channels, kw_ga4, landing_pages, ads_keywords, org_keywords = get_ga4_data()
    ads = get_ads_data_from_sheets()
    shopify = get_shopify_data()

    # Run 6 modular AI analyses (繁中)
    print("🤖 開始6個模組分析...")
    a_overview      = analyze_overview(ga4, ads, shopify)
    a_channels      = analyze_channels(channels, ga4)
    a_ad_groups     = analyze_ad_groups(ads.get("ad_groups", []), ads)
    a_keywords      = analyze_keywords(ads.get("keywords", []), ads.get("search_terms", []))
    a_search_terms  = analyze_search_terms(ads.get("search_terms", []))
    a_action_plan   = analyze_action_plan(ga4, ads, shopify, channels)

    # Generate HTML
    print("🖨️ 生成 HTML 報告...")
    generate_html_v2(
        ga4, channels, ads, shopify,
        a_overview, a_channels, a_ad_groups,
        a_keywords, a_search_terms, a_action_plan,
        ads_keywords, lang="zh"
    )

    # ZH actions page
    print("📋 生成 actions.html...")
    generate_actions_html(ga4, ads, shopify, a_ad_groups, a_keywords, a_search_terms, a_action_plan, lang="zh")

    # Korean translations (done once, reused for report_kr + actions_kr)
    print("🤖 韓文版翻譯...")
    kr_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    def translate_to_kr(text):
        msg = kr_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": f"將以下繁體中文報告翻譯成韓文，保留所有emoji和格式，數字不變：\n\n{text}"}]
        )
        return msg.content[0].text

    kr_overview     = translate_to_kr(a_overview)
    kr_channels     = translate_to_kr(a_channels)
    kr_ad_groups    = translate_to_kr(a_ad_groups)
    kr_keywords     = translate_to_kr(a_keywords)
    kr_search_terms = translate_to_kr(a_search_terms)
    kr_action_plan  = translate_to_kr(a_action_plan)

    generate_html_v2(
        ga4, channels, ads, shopify,
        kr_overview, kr_channels, kr_ad_groups,
        kr_keywords, kr_search_terms, kr_action_plan,
        ads_keywords, lang="kr"
    )

    print("📋 생성 actions_kr.html...")
    generate_actions_html(ga4, ads, shopify,
        kr_ad_groups, kr_keywords, kr_search_terms, kr_action_plan,
        lang="kr"
    )

    update_status(True)
    print("✅ 완료！생성 파일: report.html / report_kr.html / actions.html / actions_kr.html")
