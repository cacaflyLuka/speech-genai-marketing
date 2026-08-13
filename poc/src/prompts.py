"""Prompt v0 → v3 演進。

設計原則：**每一版只加一件事**，這樣評測表上每一欄的改善都能歸因到單一改動。
這是 §2 的核心。

    v0  naive          什麼都不給              → 基準線
    v1  + 通路約束      角色/受眾/字數/必含規格   → 修好「長度」與「規格覆蓋」
    v2  + 法規與語調    禁詞清單 + few-shot     → 修好「禁詞」與「語調」
    v3  + 結構化輸出    responseSchema         → 修好「可機器讀取」

刻意不做的事：不在 v1 就把法規塞進去。若一次加三件事，評測表會一次全綠，
就失去「哪個改動帶來哪個改善」的教學價值。
"""

import json

from . import config

# --------------------------------------------------------------------------
# v3 的輸出 schema。同時給 Gemini 當 responseSchema，也給規則層當驗證依據。
# --------------------------------------------------------------------------
COPY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": f"電商商品標題，最多 {config.SHOPEE_TITLE_MAX} 字",
        },
        "bullets": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"{config.BULLET_COUNT} 條賣點，每條最多 {config.BULLET_MAX} 字",
        },
        "seo_description": {
            "type": "string",
            "description": f"SEO 描述，最多 {config.SEO_DESC_MAX} 字",
        },
        "hashtags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 個標籤，不含 # 符號",
        },
    },
    "required": ["title", "bullets", "seo_description", "hashtags"],
}


def _product_block(product: dict) -> str:
    """把商品資料整理成 prompt 用的文字區塊。"""
    specs = "\n".join(f"  - {k}：{v}" for k, v in product["specs"].items())
    return (
        f"商品名稱：{product['name']}\n"
        f"品牌：{product['brand']}\n"
        f"分類：{product['category']}\n"
        f"售價：NT${product['price']}\n"
        f"規格：\n{specs}"
    )


# --------------------------------------------------------------------------
# v0 — naive
# --------------------------------------------------------------------------
def build_v0(product: dict, **_) -> str:
    """大多數人第一次寫的 prompt。刻意保持這麼爛。"""
    return f"幫我寫這個商品的電商文案。\n\n{_product_block(product)}"


# --------------------------------------------------------------------------
# v1 — 加通路約束
# --------------------------------------------------------------------------
def build_v1(product: dict, **_) -> str:
    """加入角色、受眾、通路硬限制、必含規格。

    這一版修好的是「可上架」：長度符合平台規則、規格沒有漏。
    還沒處理法規，所以禁詞仍會出現 —— 這是刻意的。
    """
    must = "、".join(product["must_include_keywords"])
    return f"""你是台灣電商平台的資深商品文案編輯。

請為以下商品撰寫文案，目標受眾是{product['target_audience']}。

【格式要求】
- 商品標題：**不超過 {config.SHOPEE_TITLE_MAX} 個字**
- 賣點：{config.BULLET_COUNT} 條，每條**不超過 {config.BULLET_MAX} 個字**
- SEO 描述：**不超過 {config.SEO_DESC_MAX} 個字**
- 標籤：3-5 個

【必須包含的規格資訊】
以下關鍵字必須出現在文案中，不可省略或改寫：{must}

【商品資料】
{_product_block(product)}"""


# --------------------------------------------------------------------------
# v2 — 加法規約束與品牌語調
# --------------------------------------------------------------------------
def build_v2(product: dict, banned_terms: list[str], tone_examples: list[dict] = None, **_) -> str:
    """在 v1 之上加兩件事：法規禁令、品牌語調 few-shot。

    禁詞清單依商品的 regulated_category 動態帶入 —— 保健食品和 3C 適用的規則不同，
    這是規則層必須「按商品屬性套用」的原因。
    """
    base = build_v1(product)

    banned_display = "、".join(banned_terms[:60])
    legal = {
        "food": "《食品安全衛生管理法》第 28 條",
        "cosmetic": "《化粧品衛生安全管理法》第 10 條",
        "general": "《公平交易法》關於不實廣告之規範",
    }[product["regulated_category"]]

    block = f"""

【法規限制 — 這是硬性要求，違反會被開罰】
本商品受{legal}規範。文案**絕對不可**出現下列詞彙或其同義表達：
{banned_display}

具體而言，不可宣稱：
- 疾病的預防、改善、減輕、診斷或治療
- 維持或改變人體器官、組織、生理或外觀之功能
- 無證據支持的絕對化描述（最有效、保證、100%、立即見效等）

若某個賣點只能用上述詞彙表達，請改用「描述使用情境」或「描述成分事實」的方式改寫，
不要為了避開禁詞而寫出空洞的句子。

【品牌語調】
{product['brand_tone']}"""

    if tone_examples:
        samples = "\n\n".join(
            f"範例 {i + 1}（商品：{ex['product']}）\n標題：{ex['title']}\n賣點：{ex['bullet']}"
            for i, ex in enumerate(tone_examples)
        )
        block += f"""

以下是本品牌既有的合規文案，請模仿其語氣與用字習慣：

{samples}"""

    return base + block


# --------------------------------------------------------------------------
# v3 — 加結構化輸出
# --------------------------------------------------------------------------
def build_v3(product: dict, banned_terms: list[str], tone_examples: list[dict] = None, **_) -> str:
    """v2 + 結構化輸出。

    注意：prompt 本身只多一句話，真正的工作交給 API 的 responseSchema 參數
    （見 generation.py）。這是重點 —— 不要用 prompt 硬凹 JSON 格式，
    要用 API 原生的 structured output，模型才會被約束在 schema 內。
    """
    return build_v2(product, banned_terms, tone_examples) + """

【輸出格式】
請直接輸出符合指定 schema 的 JSON，不要加上 markdown 程式碼區塊標記，不要加任何說明文字。"""


PROMPT_VERSIONS = {
    "v0": build_v0,
    "v1": build_v1,
    "v2": build_v2,
    "v3": build_v3,
}

# v3 是唯一啟用 API 層 structured output 的版本
STRUCTURED_VERSIONS = {"v3"}


# --------------------------------------------------------------------------
# 品牌語調 few-shot 範例（人工撰寫，已確認合規）
# --------------------------------------------------------------------------
TONE_EXAMPLES = {
    "晨光研選": [
        {
            "product": "B群緩釋錠",
            "title": "晨光研選 緩釋B群錠 90錠 每日一錠 全素可食",
            "bullet": "8種B群一次補齊，緩釋設計",
        },
        {
            "product": "鎂錠",
            "title": "晨光研選 甘胺酸鎂錠 120錠 睡前補充 無鎮靜成分",
            "bullet": "選用好吸收的甘胺酸螯合形式",
        },
    ],
    "青研 CHINGYEN": [
        {
            "product": "神經醯胺乳液",
            "title": "青研 神經醯胺修護乳液 50ml 敏弱肌適用 無香料",
            "bullet": "三種神經醯胺，質地清爽不黏膩",
        },
        {
            "product": "溫和卸妝油",
            "title": "青研 純淨卸妝油 150ml 好沖洗 不致粉刺測試",
            "bullet": "乳化快速，沖水後不留油感",
        },
    ],
    "Volta": [
        {
            "product": "行動電源",
            "title": "Volta 20000mAh 行動電源 45W雙向快充 可上飛機",
            "bullet": "45W輸出，筆電也充得動",
        },
        {
            "product": "USB-C 傳輸線",
            "title": "Volta 240W USB-C 編織線 2M 支援40Gbps傳輸",
            "bullet": "240W過電，8K螢幕直出",
        },
    ],
    "溯源焙所": [
        {
            "product": "日曬西達摩掛耳",
            "title": "溯源焙所 日曬西達摩掛耳咖啡 10入 中淺焙",
            "bullet": "日曬處理，草莓與黑糖尾韻",
        },
        {
            "product": "阿里山烏龍",
            "title": "溯源焙所 阿里山高山烏龍 三角茶包 20入 海拔1400m",
            "bullet": "清香型輕發酵，冷泡熱泡皆宜",
        },
    ],
}


def get_banned_terms_for(product: dict, banned_data: dict) -> list[str]:
    """依商品的 regulated_category 取出適用的禁詞。

    保健食品要擋『護眼』，3C 不用 —— 規則必須跟著商品屬性走，
    這是規則層在真實系統裡最容易被做錯的地方。
    """
    category = product["regulated_category"]
    terms: list[str] = []
    for group in banned_data.values():
        if not isinstance(group, dict) or "terms" not in group:
            continue
        if category in group.get("applies_to", []):
            terms.extend(group["terms"])
    return sorted(set(terms))


if __name__ == "__main__":
    # 快速目視檢查四個版本的差異
    products = json.load(open("poc/data/products.json", encoding="utf-8"))["products"]
    banned = json.load(open("poc/data/banned_terms.json", encoding="utf-8"))
    p = products[0]
    terms = get_banned_terms_for(p, banned)
    for name, fn in PROMPT_VERSIONS.items():
        text = fn(p, banned_terms=terms, tone_examples=TONE_EXAMPLES[p["brand"]])
        print(f"\n{'=' * 70}\n{name}  ({len(text)} 字元)\n{'=' * 70}\n{text}")
