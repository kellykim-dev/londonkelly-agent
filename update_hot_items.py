"""
LondonKelly Hot Items Updater
==============================
1. 移除所有現有 hot tag
2. GA4 抽過去7日 add_to_cart Top 48
3. 加 hot tag（Smart Collection 自動同步）
"""

import requests
import time
import os
from datetime import datetime
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, Dimension, Metric, DateRange

# ─── 設定 ───────────────────────────────────────────────
SHOPIFY_STORE = "londonkelly.myshopify.com"
SHOPIFY_TOKEN = "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"
GA4_PROPERTY  = "357906508"
GA4_KEY_FILE  = "ga4_key.json"
HOT_TAG       = "hot"
TOP_N         = 48
DAYS          = 7

HEADERS  = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
BASE_URL = f"https://{SHOPIFY_STORE}/admin/api/2024-01"

# ─── Shopify API ─────────────────────────────────────────

def shopify_get(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    all_items = []
    while url:
        resp = requests.get(url, headers=HEADERS, params=params)
        if resp.status_code == 429:
            time.sleep(2); continue
        resp.raise_for_status()
        data  = resp.json()
        key   = list(data.keys())[0]
        items = data[key]
        if isinstance(items, list):
            all_items.extend(items)
        else:
            return items
        link = resp.headers.get("Link", "")
        url = None; params = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>"); break
        time.sleep(0.3)
    return all_items

def shopify_put(endpoint, payload):
    url  = f"{BASE_URL}/{endpoint}"
    resp = requests.put(url, headers=HEADERS, json=payload)
    if resp.status_code == 429:
        time.sleep(2); return shopify_put(endpoint, payload)
    resp.raise_for_status()
    return resp.json()

# ─── Step 1: 移除所有 hot tag ────────────────────────────

def remove_all_hot_tags():
    print("🧹 Step 1: 移除所有 hot tag...")
    products = shopify_get("products.json", params={
        "tag": HOT_TAG, "limit": 250, "fields": "id,title,tags"
    })
    if not products:
        print("  沒有產品有 hot tag，跳過")
        return
    print(f"  找到 {len(products)} 個有 hot tag 嘅產品")
    for p in products:
        pid      = p["id"]
        tags     = [t.strip() for t in p.get("tags", "").split(",") if t.strip()]
        new_tags = [t for t in tags if t.lower() != HOT_TAG.lower()]
        if len(new_tags) != len(tags):
            shopify_put(f"products/{pid}.json", {
                "product": {"id": pid, "tags": ", ".join(new_tags)}
            })
            time.sleep(0.3)
    print(f"  ✅ 完成移除")

# ─── Step 2: GA4 抽 add_to_cart ──────────────────────────

def get_ga4_add_to_cart():
    print(f"\n📊 Step 2: GA4 抽過去{DAYS}日 add_to_cart 數據...")
    if not os.path.exists(GA4_KEY_FILE):
        print(f"  ❌ 找不到 {GA4_KEY_FILE}"); return {}
    try:
        creds  = service_account.Credentials.from_service_account_file(
            GA4_KEY_FILE,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"]
        )
        client  = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY}",
            dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name="addToCarts")],
            date_ranges=[DateRange(start_date=f"{DAYS}daysAgo", end_date="today")],
            limit=500
        )
        response   = client.run_report(request)
        cart_data  = {}
        for row in response.rows:
            path  = row.dimension_values[0].value
            count = int(row.metric_values[0].value)
            if "/products/" in path and count > 0:
                handle = path.split("/products/")[-1].split("?")[0].strip("/")
                if handle:
                    cart_data[handle] = cart_data.get(handle, 0) + count
        sorted_handles = sorted(cart_data.items(), key=lambda x: x[1], reverse=True)
        print(f"  GA4: {len(cart_data)} 個產品有數據，取 Top {TOP_N}")
        print(f"  Top 5 預覽:")
        for handle, count in sorted_handles[:5]:
            print(f"    {handle}: {count} 次")
        return dict(sorted_handles[:TOP_N])
    except Exception as e:
        print(f"  ❌ GA4 失敗: {e}"); return {}

# ─── Step 3: 加 hot tag ──────────────────────────────────

def add_hot_tags(top_handles):
    print(f"\n🔥 Step 3: 加 hot tag 落 Top {TOP_N} 產品...")
    if not top_handles:
        print("  ❌ 沒有數據"); return
    success = not_found = 0
    for i, (handle, cart_count) in enumerate(top_handles.items()):
        resp     = requests.get(f"{BASE_URL}/products.json", headers=HEADERS,
                                params={"handle": handle, "fields": "id,title,tags", "limit": 1})
        products = resp.json().get("products", [])
        if not products:
            print(f"  ⚠️  搵唔到: {handle}")
            not_found += 1
            time.sleep(0.2); continue
        p    = products[0]
        pid  = p["id"]
        tags = [t.strip() for t in p.get("tags", "").split(",") if t.strip()]
        if HOT_TAG not in [t.lower() for t in tags]:
            tags.append(HOT_TAG)
            shopify_put(f"products/{pid}.json", {
                "product": {"id": pid, "tags": ", ".join(tags)}
            })
        print(f"  ✅ [{i+1}/{len(top_handles)}] {p['title'][:45]} ({cart_count}次加入購物車)")
        success += 1
        time.sleep(0.3)
    print(f"\n  完成！成功:{success} | 搵唔到:{not_found}")

# ─── 主程式 ──────────────────────────────────────────────

def run():
    print("=" * 60)
    print(f"🔥 LondonKelly Hot Items Updater")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Top {TOP_N} | 過去 {DAYS} 日 add_to_cart")
    print("=" * 60)
    remove_all_hot_tags()
    top_handles = get_ga4_add_to_cart()
    if not top_handles:
        print("\n❌ 冇 GA4 數據，停止"); return
    add_hot_tags(top_handles)
    print("\n" + "=" * 60)
    print(f"✅ 完成！Hot collection 自動更新")
    print("=" * 60)

if __name__ == "__main__":
    run()
