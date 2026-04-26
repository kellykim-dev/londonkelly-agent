import os
import json
import anthropic
import requests
from collections import Counter
from datetime import datetime

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "londonkelly.myshopify.com")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

def get_sale_products():
    import time
    print("🛍️ 搵緊本週特價產品...")
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
    params = {"limit": 250, "status": "active"}
    sale_products = []
    while url:
        resp = requests.get(url, headers=HEADERS, params=params)
        if resp.status_code == 429:
            time.sleep(10); continue
        resp.raise_for_status()
        products = resp.json().get("products", [])
        for p in products:
            for v in p.get("variants", []):
                cap = v.get("compare_at_price")
                price = v.get("price")
                inventory = v.get("inventory_quantity", 0)
                # price > 0, compare_at_price > price, inventory > 0
                if (cap and price and
                    float(price) > 0 and
                    float(cap) > float(price) and
                    inventory > 0):
                    discount = round((1 - float(price)/float(cap)) * 100)
                    sale_products.append({
                        "title": p["title"],
                        "vendor": p["vendor"],
                        "price": float(price),
                        "compare_at_price": float(cap),
                        "discount": discount,
                        "handle": p["handle"],
                        "inventory": inventory,
                    })
                    break
        link = resp.headers.get("Link", "")
        url = None; params = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>"); break
        time.sleep(0.3)
    vendor_counts = Counter(p["vendor"] for p in sale_products)
    sale_products.sort(key=lambda x: (vendor_counts[x["vendor"]], x["discount"]), reverse=True)
    print(f"  搵到 {len(sale_products)} 件有貨特價產品")
    for v, c in vendor_counts.most_common(5):
        print(f"  {v}: {c} 件")
    return sale_products[:20]

def generate_content(products):
    print("🤖 Claude 生成緊一週內容...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    product_list = "\n".join([
        f"- {p['vendor']} {p['title']}: HK${p['price']:.0f} (原價 HK${p['compare_at_price']:.0f}, -{p['discount']}%)"
        for p in products[:10]
    ])
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""你係 LondonKelly 嘅社群媒體編輯。LondonKelly 係香港代購服務，主要賣歐洲奢侈品牌。

本週特價產品（{today}）：
{product_list}

請幫我生成 **7日** 嘅社群媒體內容計劃，每日一個 post。

格式要求：
- 用繁體中文
- 每個 post 要有：標題、內文（2-3句）、hashtags（10個）
- 適合 Threads、Instagram、Facebook
- 語氣：專業但親切，突出代購優勢（正品保證、英國直送）
- 唔同日子唔同主題：介紹產品、品牌故事、代購攻略、客戶見證、限時優惠等

輸出格式（JSON）：
{{
  "posts": [
    {{
      "day": "週一",
      "date": "{today}",
      "theme": "主題",
      "title": "標題",
      "content": "內文",
      "hashtags": "#tag1 #tag2...",
      "platform_notes": "平台備註"
    }}
  ]
}}

只輸出 JSON，唔需要其他文字。"""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = message.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(text)
        return data.get("posts", [])
    except:
        print("⚠️ JSON 解析失敗")
        return []

def generate_html(products, posts):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.now().strftime("%Y-%m-%d")
    product_cards = ""
    for p in products[:6]:
        product_cards += f"""
        <div class="product-card">
            <div class="product-vendor">{p['vendor']}</div>
            <div class="product-title">{p['title'][:40]}...</div>
            <div class="product-price">HK${p['price']:.0f} <span class="original">HK${p['compare_at_price']:.0f}</span></div>
            <div class="discount-badge">-{p['discount']}%</div>
        </div>"""
    post_cards = ""
    for i, post in enumerate(posts):
        post_cards += f"""
        <div class="post-card" id="post-{i}">
            <div class="post-header">
                <span class="post-day">{post.get('day','')}</span>
                <span class="post-theme">{post.get('theme','')}</span>
            </div>
            <div class="post-title">{post.get('title','')}</div>
            <div class="post-content">{post.get('content','').replace(chr(10),'<br>')}</div>
            <div class="post-hashtags">{post.get('hashtags','')}</div>
            <div class="post-notes">{post.get('platform_notes','')}</div>
            <button class="copy-btn" onclick="copyPost({i})">📋 複製</button>
            <div class="copied-msg" id="copied-{i}" style="display:none">✅ 已複製！</div>
        </div>"""
    html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LondonKelly 本週內容</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800&display=swap" rel="stylesheet">
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#0f0820;color:#f0e8c0;font-family:'Nunito',sans-serif;padding:16px;}}
.wrap{{max-width:700px;margin:0 auto;}}
.title{{font-family:'Nunito',sans-serif;font-weight:800;color:#ffd580;font-size:17px;text-align:center;padding:14px 20px;background:linear-gradient(90deg,#1a0e35,#0d1a35);border:2px solid #3a2a60;border-radius:12px;margin-bottom:16px;}}
.back{{display:inline-flex;align-items:center;gap:6px;color:#ffd580;font-size:13px;font-weight:800;margin-bottom:12px;text-decoration:none;background:rgba(255,213,128,0.1);border:1.5px solid rgba(255,213,128,0.3);padding:7px 16px;border-radius:10px;}}
.back:hover{{background:rgba(255,213,128,0.2);}}
.other{{display:block;text-align:center;color:#b0a0d0;font-size:13px;font-weight:700;margin-bottom:14px;text-decoration:none;background:#1a1030;border:1.5px solid #2a1a50;padding:9px;border-radius:10px;}}
.other:hover{{background:#2a1a40;color:#f0e8c0;}}
.section-title{{color:#4dd0c4;font-size:13px;font-weight:800;margin:16px 0 8px;}}
.footer{{color:#3a2a5a;font-size:11px;text-align:center;margin-top:16px;font-weight:700;}}
.products{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:20px;}}
.product-card{{background:#1a1030;border:1.5px solid #2a1a50;border-radius:10px;padding:10px;position:relative;}}
.product-vendor{{color:#ffd580;font-size:11px;margin-bottom:4px;font-weight:800;}}
.product-title{{color:#d0c8e8;font-size:11px;margin-bottom:6px;line-height:1.5;}}
.product-price{{color:#4dd0c4;font-size:14px;font-weight:800;}}
.original{{color:#4a3a6a;font-size:11px;text-decoration:line-through;margin-left:6px;}}
.discount-badge{{position:absolute;top:8px;right:8px;background:#e74c3c;color:white;font-size:10px;font-weight:800;padding:2px 7px;border-radius:20px;}}
.post-card{{background:#1a1030;border:1.5px solid #2a1a50;border-radius:12px;padding:16px;margin-bottom:12px;}}
.post-header{{display:flex;justify-content:space-between;margin-bottom:8px;align-items:center;}}
.post-day{{color:#ffd580;font-size:12px;font-weight:800;}}
.post-theme{{color:#8070a0;font-size:11px;font-weight:700;}}
.post-title{{color:#ffd580;font-size:15px;font-weight:800;margin-bottom:8px;}}
.post-content{{color:#d0c8e8;font-size:13px;line-height:1.8;margin-bottom:10px;}}
.post-hashtags{{color:#4a90d9;font-size:11px;margin-bottom:8px;line-height:1.8;}}
.post-notes{{color:#6a5a8a;font-size:11px;margin-bottom:10px;font-style:italic;}}
.copy-btn{{background:#1a2a3a;border:1.5px solid #2a3a5a;color:#90caf9;padding:7px 16px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;font-family:'Nunito',sans-serif;}}
.copy-btn:hover{{background:#2a3a5a;}}
.copied-msg{{color:#81c784;font-size:12px;margin-top:6px;}}
</style>
</head>
<body>
<div class="wrap">
  <a href="index.html" class="back">← 返回辦公室</a>
  <div class="title">★ 本週社群內容 {today} ★</div>
  <div class="section-title">&gt;_ 本週特價產品（有貨）</div>
  <div class="products">{product_cards}</div>
  <div class="section-title">&gt;_ 7日內容計劃</div>
  {post_cards}
  <div class="footer">由 LondonKelly Agent 啾皮 生成 · {now}</div>
</div>
<script>
function copyPost(i) {{
  const card = document.getElementById('post-' + i);
  const title = card.querySelector('.post-title').textContent;
  const content = card.querySelector('.post-content').textContent;
  const hashtags = card.querySelector('.post-hashtags').textContent;
  const text = title + '\\n\\n' + content + '\\n\\n' + hashtags;
  navigator.clipboard.writeText(text).then(() => {{
    const msg = document.getElementById('copied-' + i);
    msg.style.display = 'block';
    setTimeout(() => msg.style.display = 'none', 2000);
  }});
}}
</script>
</body>
</html>"""
    with open("content.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ content.html 生成完成")

if __name__ == "__main__":
    products = get_sale_products()
    if not products:
        print("⚠️ 冇搵到有貨特價產品")
    posts = generate_content(products)
    generate_html(products, posts)
    print("✅ 完成！")
