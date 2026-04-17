import os
import json
import re
import anthropic
import requests
from datetime import datetime
from bs4 import BeautifulSoup

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
}

COMPETITORS = [
    {
        "name": "LBuy",
        "website": "https://lbuy.hk/zh-hant/home/index",
        "instagram": "https://www.instagram.com/lbuy.hk/",
        "facebook": "https://www.facebook.com/lbuyhk",
        "threads": None,
    },
    {
        "name": "Society in Fame",
        "website": "https://www.societyinfame.com/",
        "instagram": "https://www.instagram.com/societyinfame/",
        "facebook": "https://www.facebook.com/societyinfame",
        "threads": None,
    }
]

def scrape_page(url, label):
    print(f"  🔍 爬取 {label}: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script','style','nav','footer']):
            tag.decompose()

        # 攞文字
        text = ' '.join(soup.get_text(separator=' ', strip=True).split())

        # 攞產品/品牌相關詞
        brands = []
        luxury_brands = ['Prada','Gucci','LV','Louis Vuitton','Chanel','Hermes','Hermès','Burberry',
                        'Dior','Valentino','Balenciaga','Saint Laurent','YSL','Celine','Loewe',
                        'Bottega','Miu Miu','Fendi','Givenchy','Versace','Coach','Kate Spade',
                        'Michael Kors','Tory Burch','Mulberry','Vivienne Westwood','Jellycat']
        for brand in luxury_brands:
            if brand.lower() in text.lower():
                brands.append(brand)

        # 攞價格
        prices = re.findall(r'(?:HK\$|HKD|港幣|£|GBP)\s*[\d,]+(?:\.\d{2})?', text)

        # 攞連結
        links = [(a.get_text(strip=True), a.get('href','')) for a in soup.find_all('a', href=True)
                 if a.get_text(strip=True) and len(a.get_text(strip=True)) > 3][:20]

        return {
            "url": url,
            "label": label,
            "text": text[:2000],
            "brands": list(set(brands)),
            "prices": prices[:20],
            "links": [f"{t}: {h}" for t,h in links[:15]],
            "status": "success"
        }
    except Exception as e:
        print(f"  ❌ 失敗: {e}")
        return {"url": url, "label": label, "text": str(e), "brands": [], "prices": [], "links": [], "status": "failed"}

def scrape_competitor(comp):
    print(f"\n📊 開始爬取 {comp['name']}...")
    result = {"name": comp['name'], "pages": {}}

    # Website
    result["pages"]["website"] = scrape_page(comp["website"], "官網")

    # Instagram (public page)
    if comp.get("instagram"):
        result["pages"]["instagram"] = scrape_page(comp["instagram"], "Instagram")

    # Facebook
    if comp.get("facebook"):
        result["pages"]["facebook"] = scrape_page(comp["facebook"], "Facebook")

    # Blog (try /blog path)
    blog_url = comp["website"].rstrip('/') + '/blog'
    result["pages"]["blog"] = scrape_page(blog_url, "Blog")

    return result

def analyze_with_claude(all_data):
    print("\n🤖 Claude 深度分析緊...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    summary = ""
    for comp in all_data:
        summary += f"\n\n{'='*50}\n{comp['name']}\n{'='*50}\n"
        for page_type, page in comp["pages"].items():
            if page["status"] == "success":
                summary += f"\n[{page['label']}]\n"
                summary += f"品牌: {', '.join(page['brands'][:10]) if page['brands'] else '未搵到'}\n"
                summary += f"價格: {', '.join(page['prices'][:8]) if page['prices'] else '未搵到'}\n"
                summary += f"內容: {page['text'][:600]}\n"

    prompt = f"""你係 LondonKelly 嘅市場策略師。今日係 {datetime.now().strftime('%Y-%m-%d')}。

LondonKelly 背景：
- 英國代購服務，主力歐洲奢侈品牌
- 目標客戶：香港、台灣、澳門
- Causeway Bay 辦公室，英國直送，正品保證
- 主要品牌：Prada, Gucci, Burberry, Hermes, LV 等

競爭對手資料：
{summary}

請用繁體中文寫一份完整競爭分析報告：

## 📊 競爭對手概況
每個對手嘅：定位、主打品牌、價格範圍、社交媒體策略

## 💰 價格對比
佢哋嘅定價策略 vs LondonKelly

## 📱 社交媒體策略
佢哋 IG/FB/Threads 嘅內容風格、頻率、互動

## 🏆 LondonKelly 優勢
我哋做得比佢哋好嘅地方

## ⚠️ 需要改善
我哋落後嘅地方

## 🎯 本週行動計劃
具體5個行動建議，幫 LondonKelly 做得更好：
1. 社交媒體內容策略
2. 產品/品牌策略  
3. 定價策略
4. 客戶服務
5. 其他

用 emoji 同清晰格式，要有具體可執行嘅建議。"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def generate_html(all_data, analysis):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.now().strftime("%Y-%m-%d")

    def md2html(t):
        t = re.sub(r'##+ (.+)', r'<h3 style="color:#FFD700;margin:14px 0 8px;font-size:14px;">\1</h3>', t)
        t = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#88DDFF">\1</strong>', t)
        t = re.sub(r'^(\d+)\. (.+)', r'<div style="margin:6px 0;"><span style="color:#FFD700">\1.</span> \2</div>', t, flags=re.MULTILINE)
        t = re.sub(r'^- (.+)', r'<li style="margin:4px 0;">\1</li>', t, flags=re.MULTILINE)
        t = re.sub(r'---+', '<hr style="border-color:#1a1a3e;margin:12px 0;">', t)
        t = t.replace('\n', '<br>')
        return t

    # Brand comparison table
    brand_rows = ""
    for comp in all_data:
        all_brands = set()
        for page in comp["pages"].values():
            all_brands.update(page.get("brands", []))
        brand_rows += f"<tr><td style='color:#FFD700;padding:8px;border-bottom:1px solid #1a1a3e;'>{comp['name']}</td><td style='padding:8px;border-bottom:1px solid #1a1a3e;font-size:11px;color:#ccc;'>{', '.join(sorted(all_brands)) if all_brands else '未搵到'}</td></tr>"

    # Price rows
    price_rows = ""
    for comp in all_data:
        all_prices = []
        for page in comp["pages"].values():
            all_prices.extend(page.get("prices", []))
        price_rows += f"<tr><td style='color:#FFD700;padding:8px;border-bottom:1px solid #1a1a3e;'>{comp['name']}</td><td style='padding:8px;border-bottom:1px solid #1a1a3e;font-size:11px;color:#00FF88;'>{', '.join(list(set(all_prices))[:6]) if all_prices else '未搵到'}</td></tr>"

    # Status cards
    status_cards = ""
    for comp in all_data:
        success = sum(1 for p in comp["pages"].values() if p["status"] == "success")
        total = len(comp["pages"])
        status_cards += f"""
        <div style="background:#0a0a1e;border:1px solid #1a1a3e;border-radius:6px;padding:12px;flex:1;">
            <div style="color:#FFD700;font-size:13px;font-weight:bold;margin-bottom:8px;">{comp['name']}</div>
            <div style="color:#00FF88;font-size:11px;">爬取成功: {success}/{total} 頁面</div>
            {''.join([f'<div style="font-size:10px;color:{\"#00FF88\" if p[\"status\"]==\"success\" else \"#FF4444\"};margin-top:4px;">{"✅" if p["status"]==\"success\" else "❌"} {p["label"]}</div>' for p in comp["pages"].values()])}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>競爭對手報告 {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#1a1208;color:#eee;font-family:sans-serif;padding:16px;}}
.wrap{{max-width:720px;margin:0 auto;}}
.title{{font-family:'Press Start 2P',monospace;color:#FFD700;font-size:9px;text-align:center;padding:12px;background:#2a1808;border:2px solid #5C4A2A;margin-bottom:16px;}}
.back{{display:block;text-align:center;color:#FFD700;font-size:11px;margin-bottom:12px;text-decoration:none;font-family:'Press Start 2P',monospace;}}
.section-title{{font-family:'Press Start 2P',monospace;color:#00FF88;font-size:7px;margin:16px 0 10px;}}
.analysis{{background:#0a0a1e;border:1px solid #1a1a3e;border-radius:6px;padding:16px;font-size:13px;line-height:1.9;}}
table{{width:100%;border-collapse:collapse;background:#0a0a1e;border-radius:6px;overflow:hidden;}}
th{{background:#1a1a3e;color:#FFD700;padding:10px 8px;text-align:left;font-size:12px;}}
.footer{{color:#555;font-size:11px;text-align:center;margin-top:16px;}}
</style>
</head>
<body>
<div class="wrap">
  <a href="index.html" class="back">← 返回辦公室</a>
  <div class="title">★ 競爭對手報告 {today} ★</div>

  <div class="section-title">&gt;_ 爬取狀態</div>
  <div style="display:flex;gap:10px;margin-bottom:16px;">{status_cards}</div>

  <div class="section-title">&gt;_ 品牌對比</div>
  <table style="margin-bottom:16px;">
    <tr><th>競爭對手</th><th>搵到品牌</th></tr>
    {brand_rows}
    <tr><td style="color:#FFD700;padding:8px;"><strong>LondonKelly</strong></td><td style="padding:8px;font-size:11px;color:#ccc;">Prada, Gucci, LV, Hermes, Burberry, Chanel, Dior, Celine...</td></tr>
  </table>

  <div class="section-title">&gt;_ 價格對比</div>
  <table style="margin-bottom:16px;">
    <tr><th>競爭對手</th><th>發現價格</th></tr>
    {price_rows}
  </table>

  <div class="section-title">&gt;_ Claude 深度分析</div>
  <div class="analysis">{md2html(analysis)}</div>

  <div class="footer">由 LondonKelly Agent 咕嚕 生成 · {now}</div>
</div>
</body>
</html>"""

    with open("competitor.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ competitor.html 生成完成")

if __name__ == "__main__":
    print("🔍 開始全面競爭對手分析...")
    all_data = [scrape_competitor(c) for c in COMPETITORS]
    analysis = analyze_with_claude(all_data)
    generate_html(all_data, analysis)
    print("✅ 完成！去睇 competitor.html")
