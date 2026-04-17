import os
import re
import json
import requests
import anthropic
from datetime import datetime

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "londonkelly.myshopify.com")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")

BLOG_SCHEDULE = [
    {
        "brand": "Chanel", "bag": "CHANEL 22 Bag",
        "celebrities": ["Jennie（BLACKPINK）", "Dua Lipa", "Lily-Rose Depp"],
        "keywords": ["Chanel 22 bag代購", "Chanel 22 bag香港", "jennie chanel bag"],
        "type": "celebrity",
        "collection_handle": "chanel"
    },
    {
        "brand": "Dior", "bag": "Dior Book Tote",
        "celebrities": ["Jisoo（BLACKPINK）", "Natalie Portman", "Jennifer Lawrence"],
        "keywords": ["Dior Book Tote代購", "Dior bag香港", "dior book tote"],
        "type": "celebrity",
        "collection_handle": "dior"
    },
    {
        "brand": "Goyard", "bag": "Goyard Hobo Bag",
        "celebrities": ["Kim Kardashian", "Rihanna", "香港明星"],
        "keywords": ["Goyard Hobo代購", "Goyard bag香港", "goyard hobo bag"],
        "type": "new",
        "collection_handle": "goyard"
    },
    {
        "brand": "Louis Vuitton", "bag": "LV OnTheGo Tote",
        "celebrities": ["Tzuyu（TWICE）", "Emma Stone", "Zendaya"],
        "keywords": ["LV OnTheGo代購", "Louis Vuitton bag香港", "lv onthego"],
        "type": "celebrity",
        "collection_handle": "louis-vuitton"
    },
    {
        "brand": "Prada", "bag": "Prada Re-Edition 2005",
        "celebrities": ["Jennie", "蔡依林 Jolin Tsai", "Angelababy"],
        "keywords": ["Prada Re-Edition代購", "Prada bag香港", "prada nylon bag"],
        "type": "classic",
        "collection_handle": "prada"
    },
    {
        "brand": "Loro Piana", "bag": "Loro Piana L/19 Bag",
        "celebrities": ["Sofia Richie", "Mary-Kate Olsen", "quiet luxury blogger"],
        "keywords": ["Loro Piana代購", "loro piana l19 bag", "quiet luxury bag香港"],
        "type": "quiet_luxury",
        "collection_handle": "loro-piana"
    },
    {
        "brand": "Celine", "bag": "Celine Ava Bag",
        "celebrities": ["IU", "Suzy（秀智）", "劉亦菲"],
        "keywords": ["Celine Ava代購", "Celine bag香港", "celine ava bag"],
        "type": "celebrity",
        "collection_handle": "celine"
    },
    {
        "brand": "Loewe", "bag": "Loewe Puzzle Bag",
        "celebrities": ["Taylor Swift", "Kaia Gerber", "歐陽娜娜"],
        "keywords": ["Loewe Puzzle代購", "Loewe bag香港", "loewe puzzle bag"],
        "type": "celebrity",
        "collection_handle": "loewe"
    },
]

WHATSAPP_LINK = "https://wa.me/85296996990"
WEBSITE = "https://londonkelly.com.hk"
BLOG_ID = "78071889984"  # LondonKelly Shopify blog ID

def get_current_blog_index():
    """追蹤輪到邊個品牌"""
    try:
        with open("blog_index.json", "r") as f:
            data = json.load(f)
            return data.get("index", 0)
    except:
        return 0

def save_blog_index(index):
    with open("blog_index.json", "w") as f:
        json.dump({"index": index, "last_run": datetime.now().isoformat()}, f)

def get_lk_products_for_brand(brand):
    """攞 LondonKelly 該品牌嘅產品"""
    if not SHOPIFY_TOKEN:
        return []
    try:
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
        params = {"limit": 10, "status": "active", "vendor": brand}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        products = resp.json().get("products", [])
        result = []
        for p in products[:5]:
            for v in p.get("variants", [])[:1]:
                price = float(v.get("price") or 0)
                if price > 0:
                    result.append({
                        "title": p.get("title", ""),
                        "price": price,
                        "handle": p.get("handle", ""),
                        "image": p.get("images", [{}])[0].get("src", "") if p.get("images") else ""
                    })
        return result
    except Exception as e:
        print(f"  ⚠️ 攞產品失敗: {e}")
        return []

def write_blog_with_claude(schedule_item, products):
    """用 Claude 寫 blog"""
    print(f"  ✍️ Claude 寫緊 {schedule_item['bag']} blog...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    celeb_str = "、".join(schedule_item["celebrities"])
    keyword_str = "、".join(schedule_item["keywords"][:3])

    product_info = ""
    if products:
        product_info = "\n現有代購產品：\n"
        for p in products:
            product_info += f"- {p['title']}：HK${p['price']:,.0f}\n"

    type_guidance = {
        "celebrity": "重點係明星用款故事，搵明星用袋嘅場合（紅地毯/街拍/活動）",
        "new": "重點係新款介紹，點解呢個款係今年最熱門",
        "classic": "重點係經典款歷史，點解值得投資",
        "quiet_luxury": "重點係 quiet luxury 趨勢，名媛生活方式"
    }

    prompt = f"""你係 LondonKelly 嘅 blog 編輯，寫繁體中文 SEO blog。

LondonKelly 係英國代購，英國買正品直送香港/台灣/澳門。
WhatsApp：{WHATSAPP_LINK}
網站：{WEBSITE}

今次主題：{schedule_item['bag']} — {type_guidance.get(schedule_item['type'], '')}
相關明星：{celeb_str}
SEO 關鍵詞：{keyword_str}
{product_info}

請寫一篇完整繁體中文 blog，直接輸出 Shopify HTML 格式：

要求：
- 長度：800-1200字
- 風格：生動、有溫度、像時尚雜誌編輯寫，唔係機械式介紹
- 必須包含：
  1. 吸引人開頭（從明星故事/熱門話題切入）
  2. 袋嘅設計特點（尺寸/材質/顏色）
  3. 明星用款故事（{celeb_str} 用過嘅場合、搭配）
  4. 點解值得代購（英國代購優勢）
  5. 代購查詢 CTA（WhatsApp查詢，唔寫實際價格）
  6. FAQ（2-3條常見問題）

HTML 格式要求（完全跟 LondonKelly 現有 blog 格式）：
- 用 <h2> 做大標題
- 用 <h3> 做小標題  
- 用 <p> 做段落
- 圖片用：<p>[📷 圖片：[圖片描述，例如：Jennie 手持 Chanel 22 Bag 街拍]</p>
- 重要字用 <strong>
- 列表用 <ul><li>
- CTA 按鈕：<p><a href="{WHATSAPP_LINK}" style="background:#0D0D0D;color:#C9A96E;padding:12px 24px;text-decoration:none;border-radius:4px;font-weight:bold;">💬 WhatsApp 查詢代購</a></p>
- 唔好用 markdown，只用 HTML

直接輸出 HTML，唔好有任何前言或解釋。"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def generate_seo_title(schedule_item):
    """生成 SEO title"""
    type_suffix = {
        "celebrity": f"｜{schedule_item['celebrities'][0]}同款",
        "new": "｜2026新款介紹",
        "classic": "｜經典款必入",
        "quiet_luxury": "｜Quiet Luxury必備"
    }
    suffix = type_suffix.get(schedule_item["type"], "")
    return f"{schedule_item['bag']}{suffix}｜英國代購攻略 {datetime.now().year}"

def generate_slug(schedule_item):
    brand = schedule_item["brand"].lower().replace(" ", "-")
    bag = schedule_item["bag"].lower().replace(" ", "-").replace(".", "")
    return f"{brand}-{bag}-{datetime.now().strftime('%Y%m')}"

def publish_to_shopify(title, content, tags, slug, schedule_item):
    """直接 publish 去 Shopify blog"""
    if not SHOPIFY_TOKEN:
        print("  ⚠️ 冇 SHOPIFY_TOKEN，跳過 publish")
        return None
    try:
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        headers = {
            "X-Shopify-Access-Token": SHOPIFY_TOKEN,
            "Content-Type": "application/json"
        }
        payload = {
            "article": {
                "title": title,
                "body_html": content,
                "tags": ", ".join(tags),
                "published": False,  # Draft 模式，等你 approve
                "metafields": [
                    {
                        "key": "description_tag",
                        "value": f"{schedule_item['bag']}英國代購｜LondonKelly 正品保證，直送香港台灣澳門。查詢：WhatsApp",
                        "type": "single_line_text_field",
                        "namespace": "global"
                    }
                ]
            }
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        article = resp.json().get("article", {})
        article_id = article.get("id")
        handle = article.get("handle", slug)
        print(f"  ✅ Draft 已上傳 Shopify！Article ID: {article_id}")
        return {"id": article_id, "handle": handle, "url": f"https://{SHOPIFY_STORE}/blogs/news/{handle}"}
    except Exception as e:
        print(f"  ❌ Publish 失敗: {e}")
        return None

def generate_html_report(blogs_drafted):
    """生成 content.html 顯示所有 drafts"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    items = ""
    for b in blogs_drafted:
        items += f"""
        <div style="background:#0a0a1e;border:1px solid #1a1a3e;border-radius:8px;padding:16px;margin-bottom:16px;">
            <div style="color:#FFD700;font-size:14px;font-weight:bold;margin-bottom:8px;">📝 {b['title']}</div>
            <div style="color:#888;font-size:11px;margin-bottom:8px;">品牌：{b['brand']} ｜ 類型：{b['type']}</div>
            {'<div style="color:#00FF88;font-size:11px;margin-bottom:12px;">✅ Shopify Draft: <a href="' + b['shopify_url'] + '" target="_blank" style="color:#88DDFF;">' + b['shopify_url'] + '</a></div>' if b.get('shopify_url') else '<div style="color:#FF8800;font-size:11px;margin-bottom:12px;">⚠️ 未上傳 Shopify</div>'}
            <details>
                <summary style="color:#88DDFF;cursor:pointer;font-size:12px;">👁️ 預覽 HTML 內容</summary>
                <div style="margin-top:12px;padding:12px;background:#050515;border-radius:4px;font-size:12px;color:#ccc;max-height:300px;overflow-y:auto;">
                    {b['content'][:1000]}...
                </div>
            </details>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LondonKelly Blog Drafts</title>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
<style>
body{{background:#1a1208;color:#eee;font-family:sans-serif;padding:16px;}}
.wrap{{max-width:720px;margin:0 auto;}}
.title{{font-family:'Press Start 2P',monospace;color:#FFD700;font-size:9px;text-align:center;padding:12px;background:#2a1808;border:2px solid #5C4A2A;margin-bottom:16px;}}
.back{{display:block;text-align:center;color:#FFD700;font-size:11px;margin-bottom:12px;text-decoration:none;font-family:'Press Start 2P',monospace;}}
.section{{font-family:'Press Start 2P',monospace;color:#00FF88;font-size:7px;margin:16px 0 10px;}}
.note{{background:#0a0a1e;border:1px solid #333;border-radius:6px;padding:12px;margin-bottom:16px;font-size:12px;color:#aaa;line-height:2;}}
.footer{{color:#555;font-size:11px;text-align:center;margin-top:16px;}}
</style>
</head>
<body>
<div class="wrap">
  <a href="index.html" class="back">← 返回辦公室</a>
  <div class="title">★ Blog Drafts {datetime.now().strftime('%Y-%m-%d')} ★</div>
  <div class="note">
    📋 以下 blog drafts 已上傳去 Shopify（Draft 狀態）<br>
    ✅ 請去 Shopify Admin 審核後 Publish<br>
    🔗 <a href="https://{SHOPIFY_STORE}/admin/articles" target="_blank" style="color:#88DDFF;">Shopify Blog 管理</a>
  </div>
  <div class="section">&gt;_ 本次 Drafts</div>
  {items}
  <div class="footer">由 LondonKelly Blog Agent 啾皮 生成 · {now}</div>
</div>
</body>
</html>"""

def update_status(success):
    """更新 status.json"""
    try:
        with open("status.json", "r") as f:
            status = json.load(f)
    except:
        status = {}
    status["blog_agent"] = {
        "status": "done" if success else "failed",
        "last_run": datetime.utcnow().isoformat() + "Z"
    }
    with open("status.json", "w") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    print("✍️ LondonKelly Blog Agent 啾皮 啟動...")

    idx = get_current_blog_index()
    schedule_item = BLOG_SCHEDULE[idx % len(BLOG_SCHEDULE)]
    next_idx = (idx + 1) % len(BLOG_SCHEDULE)

    print(f"📝 今次寫：{schedule_item['bag']} ({schedule_item['type']})")

    # 攞 LK 相關產品
    products = get_lk_products_for_brand(schedule_item["brand"])
    print(f"  搵到 {len(products)} 個相關產品")

    # Claude 寫 blog
    content_html = write_blog_with_claude(schedule_item, products)

    # 生成 title + tags
    title = generate_seo_title(schedule_item)
    slug = generate_slug(schedule_item)
    tags = [schedule_item["brand"], "代購攻略", schedule_item["bag"],
            schedule_item["type"], "英國代購", "名牌代購"]

    print(f"  📄 Title: {title}")

    # Publish 去 Shopify (Draft)
    shopify_result = publish_to_shopify(title, content_html, tags, slug, schedule_item)

    # 生成 content.html
    blogs_drafted = [{
        "title": title,
        "brand": schedule_item["brand"],
        "type": schedule_item["type"],
        "content": content_html,
        "shopify_url": shopify_result["url"] if shopify_result else None,
        "shopify_id": shopify_result["id"] if shopify_result else None,
    }]

    html = generate_html_report(blogs_drafted)
    with open("content.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  ✅ content.html 更新完成")

    # 儲存下次輪到邊個
    save_blog_index(next_idx)
    print(f"  ➡️ 下次：{BLOG_SCHEDULE[next_idx]['bag']}")

    update_status(True)
    print("✅ Blog Agent 完成！去 Shopify Admin 審核 draft。")
