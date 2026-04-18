"""
LondonKelly Collection Sorter — RESTORE SCRIPT
選擇備份日期，還原所有 collection 排序
"""

import requests
import json
import os
import time
from datetime import datetime

SHOPIFY_STORE = "londonkelly.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
BACKUP_DIR    = "backups"

HEADERS  = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
BASE_URL = f"https://{SHOPIFY_STORE}/admin/api/2024-01"


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


def restore_from_backup(backup_filename):
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    print(f"\n📂 載入備份: {backup_filename}")
    with open(backup_path, "r", encoding="utf-8") as f:
        backup_data = json.load(f)
    print(f"   找到 {len(backup_data)} 個 collections")

    success = failed = 0

    for i, (col_id_str, data) in enumerate(backup_data.items()):
        col_id      = int(col_id_str)
        col_title   = data.get("title", "unknown")
        product_ids = data.get("product_ids", [])
        sort_order  = data.get("sort_order", "manual")

        print(f"\n[{i+1}/{len(backup_data)}] {col_title}")
        if not product_ids:
            print(f"  ⚠️  空，跳過"); continue

        try:
            # 還原 sort_order
            for endpoint in [f"custom_collections/{col_id}.json", f"smart_collections/{col_id}.json"]:
                try:
                    key = endpoint.split("/")[0].replace("_collections", "_collection").replace("custom_collection","custom_collection").replace("smart_collection","smart_collection")
                    # 簡化：直接試兩個
                    if "custom" in endpoint:
                        shopify_put(endpoint, {"custom_collection": {"id": col_id, "sort_order": sort_order}})
                    else:
                        shopify_put(endpoint, {"smart_collection": {"id": col_id, "sort_order": sort_order}})
                    break
                except:
                    continue
            time.sleep(0.3)

            # 取得 collects
            collects    = shopify_get("collects.json", params={"collection_id": col_id, "limit": 250})
            collect_map = {c["product_id"]: c["id"] for c in collects}

            # 還原排序
            for pos, pid in enumerate(product_ids, start=1):
                cid = collect_map.get(pid)
                if cid:
                    try:
                        shopify_put(f"collects/{cid}.json", {"collect": {"id": cid, "position": pos}})
                    except:
                        pass
                    time.sleep(0.15)

            print(f"  ✅ 完成 ({len(product_ids)} 個產品)")
            success += 1

        except Exception as e:
            print(f"  ❌ 失敗: {e}")
            failed += 1

        time.sleep(0.5)

    print("\n" + "=" * 60)
    print(f"✅ 還原完成！成功:{success} | 失敗:{failed}")
    print("=" * 60)


def main():
    print("=" * 60)
    print("🔄 LondonKelly Collection Sorter — RESTORE")
    print("=" * 60)

    if not os.path.exists(BACKUP_DIR):
        print("❌ 未找到備份資料夾"); return

    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("backup_") and f.endswith(".json")],
        reverse=True
    )
    if not backups:
        print("❌ 沒有可用的備份"); return

    print("\n📋 可用備份（最新先）：")
    for i, fn in enumerate(backups):
        try:
            dt      = datetime.strptime(fn.replace("backup_","").replace(".json",""), "%Y%m%d_%H%M")
            display = dt.strftime("%Y年%m月%d日 %H:%M")
        except:
            display = fn
        print(f"  [{i+1}] {display}  ({fn})")
    print("  [0] 取消")

    while True:
        try:
            choice = int(input("\n請選擇備份編號: ").strip())
            if choice == 0:
                print("已取消"); return
            if 1 <= choice <= len(backups):
                selected = backups[choice - 1]; break
            print(f"請輸入 0-{len(backups)}")
        except ValueError:
            print("請輸入數字")

    print(f"\n⚠️  還原: {selected}")
    if input("確認？(yes/no): ").strip().lower() in ["yes", "y"]:
        restore_from_backup(selected)
    else:
        print("已取消")


if __name__ == "__main__":
    main()
