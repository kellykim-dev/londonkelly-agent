"""
LondonKelly Collection Auto-Sorter v2
排序規則：
1. 有貨 + 新貨（15日內）— 交替 Handbags/Wallets/Jewellery/Other
2. 有貨 + 熱賣（銷量×0.6 + GA4瀏覽量×0.4，過去30日）— 交替
3. 有貨 + 普通 — 交替
4. Sold Out — 最底
"""

import requests
import json
import os
import time
from datetime import datetime, timezone, timedelta

try:
    from google.oauth2 import service_account
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import RunReportRequest, Dimension, Metric, DateRange
    GA4_AVAILABLE = True
except ImportError:
    GA4_AVAILABLE = False

# ─── 設定 ───────────────────────────────────────────────
SHOPIFY_STORE = "londonkelly.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
GA4_PROPERTY  = "357906508"
GA4_KEY_FILE  = "ga4_key.json"
BACKUP_DIR    = "backups"
LAST_RUN_FILE = "last_run.txt"
NEW_DAYS      = 15
SALES_DAYS    = 30
SCORE_SALES   = 0.6
SCORE_VIEWS   = 0.4

HEADERS  = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
BASE_URL = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
CAT_ORDER = ["Handbags", "Wallets", "Jewellery", "Other"]

# ─── 3日檢查 ─────────────────────────────────────────────

def should_run():
    if not os.path.exists(LAST_RUN_FILE):
        return True
    with open(LAST_RUN_FILE) as f:
        last = datetime.fromisoformat(f.read().strip())
    return (datetime.now() - last).days >= 3

def mark_run():
    with open(LAST_RUN_FILE, "w") as f:
        f.write(datetime.now().isoformat())

# ─── Shopify API ─────────────────────────────────────────

def shopify_get(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    all_items = []
    while url:
        resp = requests.get(url, headers=HEADERS, params=params)
        if resp.status_code == 429:
            time.sleep(2); continue
        resp.raise_for_status()
        data = resp.json()
        key = list(data.keys())[0]
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

# ─── 庫存：用 inventory_levels API（最準確）──────────────

def get_inventory_map(product_list):
    """返回 {product_id: True/False} — True = 有貨"""
    # 收集所有 inventory_item_id → product_id 對應（一個產品可以有多個 variants）
    item_to_product = {}  # {inventory_item_id: product_id}
    untracked_products = set()  # 唔追蹤庫存嘅產品 = 永遠有貨

    for p in product_list:
        for v in p.get("variants", []):
            mgmt = v.get("inventory_management")
            if not mgmt:
                # 唔追蹤庫存 = 永遠有貨
                untracked_products.add(p["id"])
            else:
                iid = v.get("inventory_item_id")
                if iid:
                    item_to_product[iid] = p["id"]

    if not item_to_product:
        # 全部都唔追蹤庫存
        return {p["id"]: True for p in product_list}

    # 用 inventory_levels API 查各 location 庫存（加埋所有 location）
    inventory_totals = {}  # {product_id: total_available}
    item_ids = list(item_to_product.keys())

    batch_size = 50
    for i in range(0, len(item_ids), batch_size):
        batch = item_ids[i:i+batch_size]
        ids_str = ",".join(str(x) for x in batch)
        try:
            resp = requests.get(
                f"{BASE_URL}/inventory_levels.json",
                headers=HEADERS,
                params={"inventory_item_ids": ids_str, "limit": 250}
            )
            if resp.status_code == 429:
                time.sleep(2); continue
            resp.raise_for_status()
            for level in resp.json().get("inventory_levels", []):
                iid = level.get("inventory_item_id")
                avail = level.get("available")
                if avail is None:
                    avail = 0
                pid = item_to_product.get(iid)
                if pid:
                    inventory_totals[pid] = inventory_totals.get(pid, 0) + avail
        except Exception as e:
            print(f"  ⚠️  inventory_levels error: {e}")
        time.sleep(0.3)

    # 轉成 {product_id: is_in_stock}
    result = {}
    for p in product_list:
        pid = p["id"]
        if pid in untracked_products:
            result[pid] = True
        else:
            total = inventory_totals.get(pid, 0)
            result[pid] = total > 0

    return result

# ─── GA4 ─────────────────────────────────────────────────

def get_ga4_views():
    if not GA4_AVAILABLE:
        print("  ⚠️  GA4 套件未安裝")
        return {}
    if not os.path.exists(GA4_KEY_FILE):
        print(f"  ⚠️  找不到 {GA4_KEY_FILE}，退回純銷量排序")
        return {}
    print("  📊 GA4 取得瀏覽量...")
    try:
        creds = service_account.Credentials.from_service_account_file(
            GA4_KEY_FILE,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"]
        )
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY}",
            dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name="screenPageViews")],
            date_ranges=[DateRange(start_date=f"{SALES_DAYS}daysAgo", end_date="today")],
            limit=10000
        )
        response = client.run_report(request)
        views = {}
        for row in response.rows:
            path  = row.dimension_values[0].value
            count = int(row.metric_values[0].value)
            if "/products/" in path:
                handle = path.split("/products/")[-1].split("?")[0].strip("/")
                if handle:
                    views[handle] = views.get(handle, 0) + count
        print(f"  GA4: {len(views)} 個產品有瀏覽數據")
        return views
    except Exception as e:
        print(f"  ⚠️  GA4 失敗: {e}")
        return {}

# ─── Shopify 銷量 ─────────────────────────────────────────

def get_shopify_sales():
    print("  🛍️  Shopify 取得銷量...")
    since = (datetime.now(timezone.utc) - timedelta(days=SALES_DAYS)).isoformat()
    sales = {}
    try:
        orders = shopify_get("orders.json", params={
            "status": "any", "created_at_min": since,
            "limit": 250, "fields": "line_items"
        })
        for order in orders:
            for item in order.get("line_items", []):
                pid = item.get("product_id")
                qty = item.get("quantity", 0)
                if pid:
                    sales[pid] = sales.get(pid, 0) + qty
        print(f"  Shopify: {len(sales)} 個產品有銷售記錄")
    except Exception as e:
        print(f"  ⚠️  銷量取得失敗: {e}")
    return sales

# ─── 備份 ────────────────────────────────────────────────

def backup_all(collections):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    date_str    = datetime.now().strftime("%Y%m%d_%H%M")
    backup_file = os.path.join(BACKUP_DIR, f"backup_{date_str}.json")
    print(f"📦 備份中...")
    backup_data = {}
    for i, col in enumerate(collections):
        products = shopify_get(
            f"collections/{col['id']}/products.json",
            params={"limit": 250, "fields": "id"}
        )
        backup_data[str(col["id"])] = {
            "title":       col["title"],
            "sort_order":  col.get("sort_order", ""),
            "product_ids": [p["id"] for p in products]
        }
        if i % 10 == 0:
            print(f"  進度: {i+1}/{len(collections)}")
        time.sleep(0.2)
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 備份: {backup_file}")
    return backup_file

# ─── 排序邏輯 ────────────────────────────────────────────

def get_category(p):
    pt = p.get("product_type", "")
    if any(x in pt for x in ["Handbag","handbag","手袋"]):               return "Handbags"
    if any(x in pt for x in ["Wallet","wallet","銀包"]):                  return "Wallets"
    if any(x in pt for x in ["Jewellery","jewellery","Jewelry","jewelry","首飾"]): return "Jewellery"
    return "Other"

def is_new(p):
    c = p.get("created_at", "")
    if not c: return False
    try:
        dt = datetime.fromisoformat(c.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days <= NEW_DAYS
    except:
        return False

def interleave(product_list):
    buckets = {cat: [] for cat in CAT_ORDER}
    for p in product_list:
        buckets[get_category(p)].append(p)
    result  = []
    max_len = max((len(v) for v in buckets.values()), default=0)
    for i in range(max_len):
        for cat in CAT_ORDER:
            if i < len(buckets[cat]):
                result.append(buckets[cat][i])
    return result

def sort_products(products, sales, ga4_views, inventory_map):
    max_s = max(sales.values(),     default=1) or 1
    max_v = max(ga4_views.values(), default=1) or 1

    def score(p):
        s = sales.get(p["id"], 0) / max_s
        v = ga4_views.get(p.get("handle", ""), 0) / max_v
        return s * SCORE_SALES + v * SCORE_VIEWS

    new_grp = []; hot_grp = []; normal_grp = []; sold_out = []

    for p in products:
        in_stock = inventory_map.get(p["id"], True)  # 預設有貨，保守估計
        if not in_stock:
            sold_out.append(p)
        elif is_new(p):
            new_grp.append(p)
        elif score(p) > 0:
            hot_grp.append(p)
        else:
            normal_grp.append(p)

    new_grp.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    hot_grp.sort(key=score, reverse=True)

    return [p["id"] for p in (
        interleave(hot_grp) +
        interleave(new_grp) +
        interleave(normal_grp) +
        sold_out
    )]

# ─── Collection 更新 ─────────────────────────────────────

def set_manual(col_id, col_type):
    if col_type == "custom":
        shopify_put(f"custom_collections/{col_id}.json",
                    {"custom_collection": {"id": col_id, "sort_order": "manual"}})
    else:
        shopify_put(f"smart_collections/{col_id}.json",
                    {"smart_collection": {"id": col_id, "sort_order": "manual"}})

def get_products_in_collection(col_id):
    """取得 collection 內所有產品，包含完整 variant 資料"""
    # Step 1: 用 collections API 取得產品 ID 列表
    product_ids = []
    url    = f"{BASE_URL}/collections/{col_id}/products.json"
    params = {"limit": 250, "fields": "id"}
    while url:
        resp = requests.get(url, headers=HEADERS, params=params)
        if resp.status_code == 429:
            time.sleep(2); continue
        resp.raise_for_status()
        product_ids.extend([p["id"] for p in resp.json().get("products", [])])
        link = resp.headers.get("Link", "")
        url = None; params = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>"); break
        time.sleep(0.3)

    if not product_ids:
        return []

    # Step 2: 用 Products API 取得完整資料（包含 variants）
    products = []
    batch_size = 50
    for i in range(0, len(product_ids), batch_size):
        batch = product_ids[i:i+batch_size]
        ids_str = ",".join(str(x) for x in batch)
        resp = requests.get(
            f"{BASE_URL}/products.json",
            headers=HEADERS,
            params={
                "ids": ids_str,
                "limit": 250,
                "fields": "id,title,handle,product_type,created_at,variants,tags"
            }
        )
        if resp.status_code == 429:
            time.sleep(2); continue
        resp.raise_for_status()
        products.extend(resp.json().get("products", []))
        time.sleep(0.3)

    # 保持原有 collection 順序
    id_order = {pid: i for i, pid in enumerate(product_ids)}
    products.sort(key=lambda p: id_order.get(p["id"], 9999))
    return products

def update_order_graphql(col_id, product_ids):
    """用 GraphQL API 更新排序 — 支援 Smart + Custom Collections"""
    GRAPHQL_URL = f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json"
    
    # Shopify GraphQL collection GID 格式
    collection_gid = f"gid://shopify/Collection/{col_id}"
    
    # 每次最多 250 個 moves
    moves = [
        {"id": f"gid://shopify/Product/{pid}", "newPosition": str(i)}
        for i, pid in enumerate(product_ids)
    ]
    
    # 分批處理（每次最多 250）
    batch_size = 250
    for i in range(0, len(moves), batch_size):
        batch = moves[i:i+batch_size]
        mutation = """
        mutation collectionReorderProducts($id: ID!, $moves: [MoveInput!]!) {
            collectionReorderProducts(id: $id, moves: $moves) {
                job {
                    id
                    done
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        variables = {"id": collection_gid, "moves": batch}
        resp = requests.post(
            GRAPHQL_URL,
            headers=HEADERS,
            json={"query": mutation, "variables": variables}
        )
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        result = resp.json()
        errors = result.get("data", {}).get("collectionReorderProducts", {}).get("userErrors", [])
        if errors:
            print(f"    ⚠️  GraphQL errors: {errors}")
        time.sleep(0.5)

def update_order(col_id, col_type, product_ids):
    """更新 collection 產品排序"""
    try:
        update_order_graphql(col_id, product_ids)
    except Exception as e:
        # Fallback: REST API（只適用 Custom Collections）
        if col_type == "custom":
            collects    = shopify_get("collects.json", params={"collection_id": col_id, "limit": 250})
            collect_map = {c["product_id"]: c["id"] for c in collects}
            for pos, pid in enumerate(product_ids, start=1):
                cid = collect_map.get(pid)
                if cid:
                    try:
                        shopify_put(f"collects/{cid}.json", {"collect": {"id": cid, "position": pos}})
                    except:
                        pass
                    time.sleep(0.15)
        else:
            raise e

# ─── 主程式 ──────────────────────────────────────────────

def run():
    print("=" * 60)
    print(f"🚀 LondonKelly Collection Sorter v2")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    if not should_run():
        print("⏰ 未夠3日，跳過。"); return

    print("\n📋 取得所有 collections...")
    custom = shopify_get("custom_collections.json", params={"limit": 250})
    smart  = shopify_get("smart_collections.json",  params={"limit": 250})
    collections = (
        [{"id": c["id"], "title": c["title"], "sort_order": c.get("sort_order",""), "type": "custom"} for c in custom] +
        [{"id": c["id"], "title": c["title"], "sort_order": c.get("sort_order",""), "type": "smart"}  for c in smart]
    )
    SKIP_IDS = {
        280504336448,280473010240,280522391616,277399109696,282038534208,
        273488347200,281966870592,282892206144,272457367616,280636325952,
        281635586112,272457433152,272457465920,272457498688,283464695872,
        272457531456,272457564224,272457629760,280532451392,280532615232,
        279364173888,280532680768,273307074624,280504401984,280636424256,
        280636948544,273209720896,280532484160,281945374784,
        272457695296,272457728064,272457760832,280636883008,
        280618467392,275091488832,284163145792,284163113024,279685005376,
        272457793600,276055294016,275066454080,272457826368,283496251456,
        280532516928,280532418624,280353472576,284163178560,
        281051168832,272457924672,284163211328,283196784704,284163244096,
        280485265472,280636915776,280949129280,280636981312,
        273453809728,282872381504,280794955840,282404880448,272457957440,
        277453307968,273275715648,280637014080,280637046848,280473075776,
        284107604032,277125267520,284078145600,284088401984,276580794432,
        284057108544,277185855552,272458088512,272942006336,284196143168,
    }
    collections = [c for c in collections if c['id'] not in SKIP_IDS]
    print(f"   找到 {len(collections)} 個 collections（已排除品牌 collections）")

    backup_all(collections)

    print("\n📊 取得銷售及瀏覽數據...")
    sales     = get_shopify_sales()
    ga4_views = get_ga4_views()

    print(f"\n🔄 開始排序...")
    success = failed = skipped = 0

    for i, col in enumerate(collections):
        col_id    = col["id"]
        col_title = col["title"]
        col_type  = col["type"]

        print(f"\n[{i+1}/{len(collections)}] {col_title}")
        try:
            set_manual(col_id, col_type)
            time.sleep(0.3)

            products = get_products_in_collection(col_id)
            if not products:
                print(f"  ⚠️  空 collection，跳過")
                skipped += 1
                continue

            # 用 inventory_levels API 判斷有貨/冇貨
            inventory_map = get_inventory_map(products)

            sorted_ids = sort_products(products, sales, ga4_views, inventory_map)

            update_order(col_id, col_type, sorted_ids)

            sold_ct = sum(1 for p in products if not inventory_map.get(p["id"], True))
            new_ct  = sum(1 for p in products if is_new(p) and inventory_map.get(p["id"], True))
            print(f"  ✅ 完成 | 總:{len(products)} 新貨:{new_ct} Sold Out:{sold_ct}")
            success += 1

        except Exception as e:
            print(f"  ❌ 失敗: {e}")
            failed += 1

        time.sleep(0.5)

    mark_run()

    print("\n" + "=" * 60)
    print(f"✅ 全部完成！成功:{success} | 失敗:{failed} | 跳過:{skipped}")
    print("=" * 60)

if __name__ == "__main__":
    run()
