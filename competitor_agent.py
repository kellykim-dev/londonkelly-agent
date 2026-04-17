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
    },
    {
        "name": "Society in Fame",
        "website": "https://www.societyinfame.com/",
        "instagram": "https://www.instagram.com/societyinfame/",
        "facebook": "https://www.facebook.com/societyinfame",
    }
]

LUXURY_BRANDS = ['Prada','Gucci','LV','Louis Vuitton','Chanel','Hermes','Hermès','Burberry',
                'Dior','Valentino','Balenciaga','Saint Laurent','YSL','Celine','Loewe',
                'Bottega','Miu Miu','Fendi','Givenchy','Versace','Coach','Kate Spade',
                'Mulberry','Vivienne Westwood','Jellycat','Roger Vivier']

def scrape_page(url, label):
    print(f"  🔍 爬取 {label}: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script','style','nav','footer']):
            tag.decompose()
        text = ' '.join(soup.get_text(separator=' ', strip=True).split())
        brands = [b for b in LUXURY_BRANDS if b.lower() in text.lower()]
        prices = re.findall(r'(?:HK\$|HKD|港幣|£|GBP)\s*[\d,]+(?:\.\d{2})?', text)
        links = [(a.get_text(strip=True), a.get('href','')) for a in soup.find_all('a', href=True)
                 if len(a.get_text(strip=True)) > 3][:15]
        return {
            "url": url, "label": label,
            "text": text[:2000],
            "brands": list(set(brands)),
            "prices": prices[:15],
            "links": [t for t,h in links[:10]],
            "status": "success"
        }
    except Exception as e:
        print(f"  ❌ 失敗: {e}")
        return {"url": url, "label": label, "text": str(e), "brands": [], "prices": [], "links": [], "status": "failed"}

def scrape_competitor(comp):
    print(f"\n📊 開始爬取 {comp['name']}...")
    result = {"name": comp['name'], "pages": {}}
    result["pages"]["website"] = scrape_page(comp["website"], "官網")
    if comp.get("instagram"):
        result["pages"]["instagram"] = scrape_page(comp["instagram"], "Instagram")
    if comp.get("facebook"):
        result["pages"]["facebook"] = scrape_page(comp["facebook"], "Facebook")
    blog_url = comp["website"].rstrip('/') + '/blog'
    result["pages"]["blog"] = scrape_page(blog_url, "Blog")
    return result

def analyze_with_claude(all_data, lang="zh"):
    print(f"\n🤖 Claude 分析緊 ({'繁中' if lang=='zh' else '韓文'})...")
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

    if lang == "zh":
        prompt = f"""你係 LondonKelly 嘅市場策略師。今日係 {datetime.now().strftime('%Y-%m-%d')}。

LondonKelly 背景：英國代購服務，主力歐洲奢侈品牌，目標客戶香港、台灣、澳門，Causeway Bay 辦公室，英國直送，正品保證。

競爭對手資料：
{summary}

請用繁體中文寫完整競爭分析：

## 📊 競爭對手概況
每個對手嘅定位、主打品牌、價格範圍、社交媒體策略

## 💰 價格對比
佢哋嘅定價策略 vs LondonKelly

## 📱 社交媒體策略
佢哋 IG/FB 嘅內容風格、頻率

## 🏆 LondonKelly 優勢
我哋做得比佢哋好嘅地方

## ⚠️ 需要改善
我哋落後嘅地方

## 🎯 本週5個行動建議
具體可執行，幫 LondonKelly 做得更好

用 emoji，清晰格式。"""
    else:
        prompt = f"""당신은 LondonKelly의 시장 전략가입니다. 오늘은 {datetime.now().strftime('%Y-%m-%d')}입니다.

LondonKelly 소개: 영국 대리구매 서비스, 유럽 명품 브랜드 전문, 홍콩/대만/마카오 고객 대상, 영국 직배송, 정품 보증.

경쟁사 데이터:
{summary}

한국어로 완전한 경쟁사 분석 보고서를 작성해주세요:

## 📊 경쟁사 현황
각 경쟁사의 포지셔닝, 주요 브랜드, 가격대, SNS 전략

## 💰 가격 비교
경쟁사 가격 전략 vs LondonKelly

## 📱 SNS 전략
Instagram/Facebook 콘텐츠 스타일, 빈도

## 🏆 LondonKelly 강점
우리가 경쟁사보다 잘하는 점

## ⚠️ 개선 필요 사항
우리가 뒤처지는 부분

## 🎯 이번 주 5가지 실행 계획
LondonKelly를 더 잘하기 위한 구체적인 실행 가능한 제안

이모지 사용, 명확한 형식."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def build_status_cards(all_data):
    cards = ""
    for comp in all_data:
        success = sum(1 for p in comp["pages"].values() if p["status"] == "success")
        total = len(comp["pages"])
        page_lines = ""
        for p in comp["pages"].values():
            color = "#00FF88" if p["status"] == "success" else "#FF4444"
            icon = "✅" if p["status"] == "success" else "❌"
            page_lines += f'<div style="font-size:10px;color:{color};margin-top:4px;">{icon} {p["label"]}</div>'
        cards += f'''<div style="background:#0a0a1e;border:1px solid #1a1a3e;border-radius:6px;padding:12px;flex:1;">
            <div style="color:#FFD700;font-size:13px;font-weight:bold;margin-bottom:8px;">{comp["name"]}</div>
            <div style="color:#00FF88;font-size:11px;">爬取成功: {success}/{total}</div>
            {page_lines}
        </div>'''
    return cards

def generate_html(all_data, analysis, lang="zh"):
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

    brand_rows = ""
    for comp in all_data:
        all_brands = set()
        for page in comp["pages"].values():
            all_brands.update(page.get("brands", []))
        brand_rows += f"<tr><td style='color:#FFD700;padding:8px;border-bottom:1px solid #1a1a3e;'>{comp['name']}</td><td style='padding:8px;border-bottom:1px solid #1a1a3e;font-size:11px;color:#ccc;'>{', '.join(sorted(all_brands)) if all_brands else '未搵到'}</td></tr>"

    price_rows = ""
    for comp in all_data:
        all_prices = []
        for page in comp["pages"].values():
            all_prices.extend(page.get("prices", []))
        price_rows += f"<tr><td style='color:#FFD700;padding:8px;border-bottom:1px solid #1a1a3e;'>{comp['name']}</td><td style='padding:8px;border-bottom:1px solid #1a1a3e;font-size:11px;color:#00FF88;'>{', '.join(list(set(all_prices))[:6]) if all_prices else '未搵到'}</td></tr>"

    status_cards = build_status_cards(all_data)

    if lang == "zh":
        title = "競爭對手報告"
        back = "← 返回辦公室"
        other_link = "competitor_kr.html"
        other_label = "🇰🇷 한국어 버전"
        filename = "competitor.html"
        footer_lang = "繁中"
        brand_th = ["競爭對手", "搵到品牌"]
        price_th = ["競爭對手", "發現價格"]
        lk_brands = "Prada, Gucci, LV, Hermes, Burberry, Chanel, Dior, Celine..."
        section_status = "爬取狀態"
        section_brand = "品牌對比"
        section_price = "價格對比"
        section_analysis = "Claude 深度分析"
    else:
        title = "경쟁사 분석 보고서"
        back = "← 사무실로 돌아가기"
        other_link = "competitor.html"
        other_label = "🇨🇳 繁體中文版"
        filename = "competitor_kr.html"
        footer_lang = "한국어"
        brand_th = ["경쟁사", "발견된 브랜드"]
        price_th = ["경쟁사", "발견된 가격"]
        lk_brands = "Prada, Gucci, LV, Hermes, Burberry, Chanel, Dior, Celine..."
        section_status = "수집 현황"
        section_brand = "브랜드 비교"
        section_price = "가격 비교"
        section_analysis = "Claude 심층 분석"

    html = f"""<!DOCTYPE html>
<html lang="{'zh-HK' if lang=='zh' else 'ko'}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#1a1208;color:#eee;font-family:sans-serif;padding:16px;}}
.wrap{{max-width:720px;margin:0 auto;}}
.title{{font-family:'Press Start 2P',monospace;color:#FFD700;font-size:9px;text-align:center;padding:12px;background:#2a1808;border:2px solid #5C4A2A;margin-bottom:16px;}}
.back{{display:block;text-align:center;color:#FFD700;font-size:11px;margin-bottom:12px;text-decoration:none;font-family:'Press Start 2P',monospace;}}
.other{{display:block;text-align:center;color:#88DDFF;font-size:11px;margin-bottom:16px;text-decoration:none;border:1px solid #1a1a3e;padding:6px;border-radius:4px;}}
.section-title{{font-family:'Press Start 2P',monospace;color:#00FF88;font-size:7px;margin:16px 0 10px;}}
.analysis{{background:#0a0a1e;border:1px solid #1a1a3e;border-radius:6px;padding:16px;font-size:13px;line-height:1.9;}}
table{{width:100%;border-collapse:collapse;background:#0a0a1e;border-radius:6px;overflow:hidden;margin-bottom:16px;}}
th{{background:#1a1a3e;color:#FFD700;padding:10px 8px;text-align:left;font-size:12px;}}
.footer{{color:#555;font-size:11px;text-align:center;margin-top:16px;}}
</style>
</head>
<body>
<div class="wrap">
  <a href="index.html" class="back">{back}</a>
  <a href="{other_link}" class="other">{other_label}</a>
  <div class="title">★ {title} {today} ★</div>
  <div class="section-title">&gt;_ {section_status}</div>
  <div style="display:flex;gap:10px;margin-bottom:16px;">{status_cards}</div>
  <div class="section-title">&gt;_ {section_brand}</div>
  <table>
    <tr><th>{brand_th[0]}</th><th>{brand_th[1]}</th></tr>
    {brand_rows}
    <tr><td style="color:#FFD700;padding:8px;">LondonKelly</td><td style="padding:8px;font-size:11px;color:#ccc;">{lk_brands}</td></tr>
  </table>
  <div class="section-title">&gt;_ {section_price}</div>
  <table>
    <tr><th>{price_th[0]}</th><th>{price_th[1]}</th></tr>
    {price_rows}
  </table>
  <div class="section-title">&gt;_ {section_analysis}</div>
  <div class="analysis">{md2html(analysis)}</div>
  <div class="footer">LondonKelly Agent 咕嚕 · {footer_lang} · {now}</div>
</div>
</body>
</html>"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {filename} 生成完成")

if __name__ == "__main__":
    print("🔍 開始全面競爭對手分析...")
    all_data = [scrape_competitor(c) for c in COMPETITORS]

    print("\n📝 生成繁中版...")
    analysis_zh = analyze_with_claude(all_data, lang="zh")
    generate_html(all_data, analysis_zh, lang="zh")

    print("\n📝 생성 한국어 버전...")
    analysis_kr = analyze_with_claude(all_data, lang="kr")
    generate_html(all_data, analysis_kr, lang="kr")

    print("\n✅ 完成！兩個版本都生成咗。")
