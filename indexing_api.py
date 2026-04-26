import requests
import time
import os
import json
from google.oauth2 import service_account
import googleapiclient.discovery

# ===== 設定 =====
KEY_FILE = "ga4_key.json"
SHOPIFY_STORE = "londonkelly.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
BASE_URL = "https://londonkelly.com.hk"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
DAILY_LIMIT = 190  # 留少少 buffer
PROGRESS_FILE = "indexing_progress.json"

def shopify_get(url, params=None, max_retries=3):
    """Shopify API call with retry + rate limit handling"""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  ⏳ Rate limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                print(f"  ⚠️ HTTP {r.status_code}, retry {attempt+1}")
                time.sleep(5)
                continue
            if not r.text.strip():
                print(f"  ⚠️ Empty response, retry {attempt+1}")
                time.sleep(5)
                continue
            return r.json()
        except Exception as e:
            print(f"  ⚠️ Error: {e}, retry {attempt+1}")
            time.sleep(5)
    return {}

def get_all_urls():
    """Get all URLs from Shopify"""
    urls = []

    # Collections
    print("📦 拉 collections...")
    for endpoint in ["custom_collections", "smart_collections"]:
        since_id = 0
        while True:
            data = shopify_get(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/{endpoint}.json",
                params={"limit": 250, "since_id": since_id}
            ).get(endpoint.replace("_", "_"), [])
            # handle key name
            if not data:
                data = shopify_get(
                    f"https://{SHOPIFY_STORE}/admin/api/2024-01/{endpoint}.json",
                    params={"limit": 250, "since_id": since_id}
                ).get(endpoint, [])
            if not data:
                break
            for c in data:
                urls.append(f"{BASE_URL}/collections/{c['handle']}")
            since_id = data[-1]["id"]
            time.sleep(0.5)
    print(f"  → {len(urls)} collections")

    # Products
    print("🛍️ 拉 products...")
    since_id = 0
    prod_count = 0
    while True:
        resp = shopify_get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json",
            params={"limit": 250, "since_id": since_id, "fields": "id,handle", "status": "active"}
        )
        data = resp.get("products", [])
        if not data:
            break
        for p in data:
            urls.append(f"{BASE_URL}/products/{p['handle']}")
            prod_count += 1
        since_id = data[-1]["id"]
        if prod_count % 500 == 0:
            print(f"  → {prod_count} products...")
        time.sleep(0.5)
    print(f"  → {prod_count} products")
    print(f"✅ Total: {len(urls)} URLs")
    return urls

def load_progress():
    """Load last submitted index"""
    try:
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"last_index": 0, "total_urls": 0, "submitted_today": 0}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

# ===== Main =====
print("🔍 載入進度...")
progress = load_progress()

print("📡 拉取所有 URLs...")
all_urls = get_all_urls()
total = len(all_urls)

# Start from where we left off
start_index = progress.get("last_index", 0)
if start_index >= total:
    print("✅ 所有 URLs 已 submit 完！重新由頭開始...")
    start_index = 0

print(f"\n🚀 開始 submit (從第 {start_index+1}/{total} 個開始)...")

# Google Indexing API
SCOPES = ["https://www.googleapis.com/auth/indexing"]
credentials = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
service = googleapiclient.discovery.build("indexing", "v3", credentials=credentials)

submitted = 0
failed = 0

for i in range(start_index, total):
    if submitted >= DAILY_LIMIT:
        print(f"\n⚠️ 今日 {DAILY_LIMIT} 個額度用完！")
        print(f"   明日會從第 {i+1}/{total} 個繼續")
        progress["last_index"] = i
        progress["total_urls"] = total
        save_progress(progress)
        break

    url = all_urls[i]
    try:
        service.urlNotifications().publish(
            body={"url": url, "type": "URL_UPDATED"}
        ).execute()
        submitted += 1
        if submitted % 50 == 0:
            print(f"  ✅ [{submitted}/{DAILY_LIMIT}] progress: {i+1}/{total}")
        time.sleep(0.15)
    except Exception as e:
        failed += 1
        if failed <= 5:
            print(f"  ❌ {url}: {e}")
else:
    # Finished all URLs
    progress["last_index"] = 0  # Reset for next cycle
    progress["total_urls"] = total
    save_progress(progress)

progress["submitted_today"] = submitted
save_progress(progress)

days_needed = (total - start_index) // DAILY_LIMIT + 1
print(f"\n🎉 完成！成功: {submitted} | 失敗: {failed}")
print(f"📊 進度: {min(start_index + submitted, total)}/{total} URLs submitted")
print(f"⏰ 預計需要 {days_needed} 日完成所有 URLs")
