import requests
import time
from google.oauth2 import service_account
import googleapiclient.discovery
import os

# ===== 設定 =====
KEY_FILE = "ga4_key.json"  # GitHub Actions 會放喺同一目錄
SHOPIFY_STORE = "londonkelly.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")  # 從 env 攞
BASE_URL = "https://londonkelly.com.hk"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}

urls = []

# ===== Custom Collections =====
print("📦 拉 custom collections...")
since_id = 0
while True:
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/custom_collections.json?limit=250&since_id={since_id}",
        headers=HEADERS
    )
    data = r.json().get("custom_collections", [])
    if not data:
        break
    for c in data:
        urls.append(f"{BASE_URL}/collections/{c['handle']}")
    since_id = data[-1]["id"]
    time.sleep(0.3)

print(f"  → {len(urls)} custom collections")

# ===== Smart Collections =====
print("📦 拉 smart collections...")
count_before = len(urls)
since_id = 0
while True:
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/smart_collections.json?limit=250&since_id={since_id}",
        headers=HEADERS
    )
    data = r.json().get("smart_collections", [])
    if not data:
        break
    for c in data:
        urls.append(f"{BASE_URL}/collections/{c['handle']}")
    since_id = data[-1]["id"]
    time.sleep(0.3)

print(f"  → {len(urls) - count_before} smart collections")
print(f"✅ Collections total: {len(urls)}")

# ===== Products =====
print("🛍️ 拉 products...")
since_id = 0
prod_count = 0
while True:
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250&since_id={since_id}&fields=id,handle",
        headers=HEADERS
    )
    data = r.json().get("products", [])
    if not data:
        break
    for p in data:
        urls.append(f"{BASE_URL}/products/{p['handle']}")
        prod_count += 1
    since_id = data[-1]["id"]
    print(f"  → {prod_count} products so far...")
    time.sleep(0.3)

print(f"✅ Products total: {prod_count}")
print(f"✅ Grand total: {len(urls)} URLs（需要 {len(urls)//200 + 1} 日跑完）")

# ===== Submit to Google Indexing API =====
print("\n🚀 開始 submit 去 Google...")
SCOPES = ["https://www.googleapis.com/auth/indexing"]
credentials = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
service = googleapiclient.discovery.build("indexing", "v3", credentials=credentials)

submitted = 0
failed = 0

for i, url in enumerate(urls):
    if submitted >= 200:
        print(f"\n⚠️ 今日200個額度用完！剩低 {len(urls)-i} 個，明日再跑。")
        break
    try:
        service.urlNotifications().publish(
            body={"url": url, "type": "URL_UPDATED"}
        ).execute()
        submitted += 1
        print(f"✅ [{submitted}/200] {url}")
        time.sleep(0.1)
    except Exception as e:
        failed += 1
        print(f"❌ {url}: {e}")

print(f"\n🎉 完成！成功: {submitted} 個，失敗: {failed} 個")
