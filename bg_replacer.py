import requests
import base64
from PIL import Image
from io import BytesIO
import time

SHOPIFY_STORE = "londonkelly.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
PHOTOROOM_KEY = "sk_pr_default_5537147bd723bbd4a57f440742144f10668dee26"
COLLECTION_ID = "284196143168"
TARGET_BG_HEX = "#EEECEA"
CANVAS_W = 1600
CANVAS_H = 2000
PADDING = 0.90  # 物件最多佔畫布 90%

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def remove_background_photoroom(image_bytes):
    response = requests.post(
        "https://sdk.photoroom.com/v1/segment",
        headers={"x-api-key": PHOTOROOM_KEY},
        files={"image_file": image_bytes},
        data={"format": "png", "size": "original"}
    )
    if response.status_code == 200:
        return response.content
    else:
        print(f"PhotoRoom 錯誤: {response.status_code} - {response.text}")
        return None

def compose_image(png_bytes):
    bg_rgb = hex_to_rgb(TARGET_BG_HEX)
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), bg_rgb)
    obj_img = Image.open(BytesIO(png_bytes)).convert("RGBA")
    obj_w, obj_h = obj_img.size

    # 計算最大允許大小（90% 畫布）
    max_w = int(CANVAS_W * PADDING)
    max_h = int(CANVAS_H * PADDING)

    # 按比例 fit，唔放大唔縮小超過需要
    scale = min(max_w / obj_w, max_h / obj_h)
    new_w = int(obj_w * scale)
    new_h = int(obj_h * scale)

    obj_img = obj_img.resize((new_w, new_h), Image.LANCZOS)

    # 置中
    x = (CANVAS_W - new_w) // 2
    y = (CANVAS_H - new_h) // 2

    canvas.paste(obj_img, (x, y), obj_img)

    output = BytesIO()
    canvas.save(output, format="JPEG", quality=95)
    return output.getvalue()

def upload_image_to_shopify(product_id, image_id, new_image_bytes):
    encoded = base64.b64encode(new_image_bytes).decode('utf-8')
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}/images/{image_id}.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    payload = {"image": {"id": image_id, "attachment": encoded}}
    response = requests.put(url, headers=headers, json=payload)
    return response.status_code == 200

def get_collection_products():
    products = []
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/collections/{COLLECTION_ID}/products.json?limit=250"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    while url:
        response = requests.get(url, headers=headers)
        data = response.json()
        products.extend(data.get("products", []))
        link_header = response.headers.get("Link", "")
        if 'rel="next"' in link_header:
            url = link_header.split('<')[1].split('>')[0]
        else:
            url = None
    return products

def main():
    print(f"開始處理 Collection {COLLECTION_ID}...")
    products = get_collection_products()
    print(f"找到 {len(products)} 件產品")

    processed = 0
    errors = 0
    for product in products:
        for image in product.get("images", []):
            image_url = image["src"]
            image_id = image["id"]
            product_id = product["id"]
            print(f"\n處理: {product['title']} (圖片 {image_id})")
            img_response = requests.get(image_url)
            print("  → 去背中...")
            png_bytes = remove_background_photoroom(img_response.content)
            if not png_bytes:
                errors += 1
                continue
            print("  → 合成 1600x2000 畫布...")
            final_image = compose_image(png_bytes)
            success = upload_image_to_shopify(product_id, image_id, final_image)
            if success:
                print("  ✓ 完成")
                processed += 1
            else:
                print("  ✗ 上傳失敗")
                errors += 1
            time.sleep(0.5)
    print(f"\n===== 完成 =====")
    print(f"換底: {processed} 張")
    print(f"錯誤: {errors} 張")

if __name__ == "__main__":
    main()
