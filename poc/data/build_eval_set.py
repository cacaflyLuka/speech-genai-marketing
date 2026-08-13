"""產生評測用的商品資料集（預設 200 筆）。

## 為什麼要跟 demo 的 12 筆分開

兩者的目的不同：

- `products.json`（12 筆）—— **台上跑的 demo**。要快、要能一頁看完、
  要內嵌進 notebook 還能保持檔案大小合理。
- `eval_products.json`（200 筆）—— **離線跑的評測集**。用來回答
  「v2 和 v3 的差別是真的還是雜訊」這種需要統計量的問題。

12 筆時，一次檢查翻轉就是 1.2 個百分點，兩三個百分點的差距完全看不出
是不是雜訊。200 筆 × 7 條 rubric = 1400 次檢查，單次翻轉只剩 0.07 個
百分點，才有辦法做小幅比較。

## 為什麼用組合生成，不用 LLM 生成

- **可重現**：固定 seed，任何人跑出來都一樣，評測結果才可比對。
- **零成本**：200 筆商品不需要花錢也不需要網路。
- **避免同源偏誤**：若用同一家的模型生資料又用它產文案，測出來的
  「表現好」可能只是模型在複述自己的用語習慣。

## 產出

    uv run python poc/data/build_eval_set.py            # 200 筆
    uv run python poc/data/build_eval_set.py --count 50 # 先小量試
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random

OUT = pathlib.Path(__file__).parent / "eval_products.json"

# --------------------------------------------------------------------------
# 品牌：語調要有明顯差異，rubric 才評得出「像不像這個品牌」
# --------------------------------------------------------------------------
BRANDS = {
    "晨光研選": ("溫和、專業、不誇大，訴求日常持續補充", "food"),
    "溯源焙所": ("職人感、重視產區與風味描述，不誇大功效", "food"),
    "青研 CHINGYEN": ("清爽、成分透明、理性溫柔，重視敏弱肌友善", "cosmetic"),
    "白日光 SUNDAY": ("明亮、生活感、口語但不輕浮", "cosmetic"),
    "Volta": ("直接、規格導向、略帶科技感，不用形容詞堆砌", "general"),
    "本木 BENMU": ("樸實、耐用取向、強調材質與工法", "general"),
}

AUDIENCES = {
    "food": [
        "25-45 歲長時間使用螢幕的上班族",
        "外食族、作息不規律的上班族",
        "30-50 歲注重外在保養的女性",
        "注重原型食物的家庭與健身族群",
        "40 歲以上開始注意日常保養的族群",
    ],
    "cosmetic": [
        "20-35 歲敏弱肌、成分黨消費者",
        "25-40 歲混合肌、重視質地的上班族",
        "18-30 歲學生與社群重度使用者",
        "30-45 歲重視保濕與溫和配方的族群",
    ],
    "general": [
        "通勤族、遠距工作者",
        "出差族、多裝置使用者",
        "小坪數家庭、養寵物族群",
        "重視 CP 值的首購族",
    ],
}

# --------------------------------------------------------------------------
# 商品模板：(品項, 分類, 主成分/主規格候選, 單位, 數值範圍)
# must_include_keywords 會從實際填入的規格取，保證文案裡真的必須寫到。
# --------------------------------------------------------------------------
FOOD_ITEMS = [
    ("葉黃素膠囊", "保健食品 / 眼部保養", "游離型葉黃素", "mg", (15, 30, 45)),
    ("複方益生菌粉", "保健食品 / 消化保健", "專利益生菌", "億CFU", (50, 100, 300)),
    ("魚膠原蛋白粉", "保健食品 / 美容保養", "深海魚膠原蛋白胜肽", "mg", (2500, 3000, 5000)),
    ("緩釋B群錠", "保健食品 / 精神體力", "維生素B群複方", "mg", (50, 75, 100)),
    ("深海魚油軟膠囊", "保健食品 / 循環保健", "Omega-3", "mg", (500, 800, 1000)),
    ("檸檬酸鈣錠", "保健食品 / 骨骼保健", "檸檬酸鈣", "mg", (300, 500, 600)),
    ("甘胺酸亞鐵錠", "保健食品 / 女性保健", "甘胺酸亞鐵", "mg", (10, 15, 20)),
    ("薑黃萃取膠囊", "保健食品 / 日常保養", "薑黃素", "mg", (100, 200, 300)),
    ("蔓越莓膠囊", "保健食品 / 女性保健", "蔓越莓萃取", "mg", (200, 400, 500)),
    ("芝麻素膠囊", "保健食品 / 舒緩放鬆", "芝麻素", "mg", (10, 20, 30)),
    ("乳鐵蛋白粉", "保健食品 / 日常保養", "乳鐵蛋白", "mg", (100, 200, 300)),
    ("綜合維他命錠", "保健食品 / 綜合補充", "23種維生素礦物質", "種", (23, 25, 28)),
    ("掛耳咖啡", "food / 咖啡", "單一產區豆", "g", (10, 12, 15)),
    ("三角立體茶包", "food / 茶葉", "台灣高山茶", "g", (2, 3, 4)),
    ("低溫烘焙堅果", "food / 零食", "綜合堅果", "g", (200, 350, 500)),
    ("即溶燕麥飲", "food / 沖泡飲", "全穀燕麥", "g", (25, 30, 35)),
    ("乳清蛋白粉", "food / 運動營養", "分離乳清蛋白", "g", (20, 25, 30)),
    ("凍乾果乾", "food / 零食", "整顆凍乾水果", "g", (30, 50, 80)),
]

COSMETIC_ITEMS = [
    ("舒緩精華液", "美妝保養 / 精華液", "積雪草萃取", "%", (2, 5, 10)),
    ("溫和洗面乳", "美妝保養 / 清潔", "胺基酸界面活性劑", "ml", (100, 120, 150)),
    ("保濕面膜", "美妝保養 / 面膜", "多重玻尿酸", "片", (5, 7, 10)),
    ("修護乳液", "美妝保養 / 乳液", "神經醯胺", "ml", (50, 80, 100)),
    ("化妝水", "美妝保養 / 化妝水", "泛醇", "ml", (150, 200, 250)),
    ("礦物防曬乳", "美妝保養 / 防曬", "氧化鋅", "ml", (30, 50, 60)),
    ("純淨卸妝油", "美妝保養 / 卸妝", "植物油脂", "ml", (100, 150, 200)),
    ("眼周精華", "美妝保養 / 眼部", "咖啡因複方", "ml", (15, 20, 30)),
    ("身體乳", "美妝保養 / 身體", "乳油木果脂", "ml", (200, 250, 300)),
    ("護手霜", "美妝保養 / 手部", "尿素", "%", (3, 5, 10)),
    ("頭皮精華", "美妝保養 / 頭皮", "水楊酸", "%", (1, 2, 3)),
    ("唇部修護膏", "美妝保養 / 唇部", "蜂蠟與植物油", "g", (8, 10, 15)),
]

# general 的第 3 欄是規格「欄位名」，第 6 欄才是文案裡真的會出現的詞。
# 兩者要分開：必含關鍵字若寫「每日除濕量」，文案永遠不會這樣寫，
# 規則層就變成不可能通過的檢查，v0→v1 的訊號會被壓平。
GENERAL_ITEMS = [
    ("降噪藍牙耳機", "3C / 音訊", "主動降噪深度", "dB", (35, 42, 50), "降噪"),
    ("氮化鎵快充充電器", "3C / 充電", "總輸出", "W", (45, 65, 100), "氮化鎵"),
    ("USB-C 編織傳輸線", "3C / 線材", "過電瓦數", "W", (100, 140, 240), "USB-C"),
    ("行動電源", "3C / 充電", "電池容量", "mAh", (10000, 20000, 27000), "行動電源"),
    ("機械式鍵盤", "3C / 週邊", "按鍵數", "鍵", (68, 87, 104), "機械式"),
    ("無線滑鼠", "3C / 週邊", "DPI", "DPI", (4000, 8000, 16000), "無線"),
    ("螢幕掛燈", "3C / 週邊", "顯色指數", "Ra", (90, 95, 97), "顯色"),
    ("手持無線吸塵器", "家電 / 清潔", "吸力", "Pa", (12000, 18000, 25000), "吸力"),
    ("空氣清淨機", "家電 / 空氣", "適用坪數", "坪", (8, 15, 20), "坪數"),
    ("除濕機", "家電 / 空氣", "每日除濕量", "L", (6, 10, 16), "除濕"),
    ("循環扇", "家電 / 空調", "風速段數", "段", (8, 12, 32), "風速"),
    ("不鏽鋼保溫瓶", "生活 / 水壺", "容量", "ml", (350, 500, 750), "保溫"),
    ("鑄鐵平底鍋", "生活 / 廚具", "直徑", "cm", (20, 24, 28), "鑄鐵"),
    ("陶瓷刀具組", "生活 / 廚具", "件數", "件", (3, 5, 7), "陶瓷"),
]

POOLS = {"food": FOOD_ITEMS, "cosmetic": COSMETIC_ITEMS, "general": GENERAL_ITEMS}

ORIGINS = ["台灣", "日本", "韓國", "德國", "美國"]
FORMS = {
    "food": ["植物膠囊", "粉末隨身包", "錠劑", "軟膠囊", "獨立包裝"],
    "cosmetic": ["水感質地", "乳霜質地", "凝露質地", "油狀質地"],
    "general": ["霧面鋁合金", "食品級不鏽鋼", "PC+ABS 複合", "陽極處理"],
}


def _make_product(rng: random.Random, idx: int, reg: str) -> dict:
    tpl = rng.choice(POOLS[reg])
    item, category, spec_name, unit, values = tpl[:5]
    # general 的模板多一欄「文案用詞」；食品與美妝的成分名本身就適合當關鍵字
    copy_term = tpl[5] if len(tpl) > 5 else spec_name
    brand = rng.choice([b for b, (_, r) in BRANDS.items() if r == reg])
    tone = BRANDS[brand][0]
    value = rng.choice(values)

    spec_str = f"{value}{unit}"
    # 家電與 3C 是單一物件，不會用「N 入」計數 —— 只有食品與美妝才有盒裝數量
    has_count = reg in ("food", "cosmetic")
    count = rng.choice([20, 30, 60, 90, 120]) if reg == "food" else rng.choice([1, 3, 5, 7])
    count_unit = {"food": "粒", "cosmetic": "入"}.get(reg, "")

    specs = {
        "主要規格": f"{spec_name} {spec_str}",
        "型態": rng.choice(FORMS[reg]),
        "產地": rng.choice(ORIGINS),
    }
    if has_count:
        specs["包裝"] = f"{count}{count_unit} / 盒"
    if reg == "food":
        specs["建議食用"] = rng.choice(["每日1份，隨餐食用", "每日1份，睡前食用", "每日1-2份"])
    elif reg == "cosmetic":
        specs["適用膚質"] = rng.choice(["所有膚質", "敏弱肌適用", "油性與混合肌", "乾燥缺水肌"])
    else:
        specs["保固"] = rng.choice(["原廠一年保固", "兩年保固", "終身技術支援"])

    # 必含關鍵字必須是「文案真的寫得出來」的詞。用欄位名（例如「每日除濕量」）
    # 會讓規則層永遠不通過，v0→v1 的訊號就被壓平了。
    must = [copy_term, spec_str]
    if has_count:
        must.append(f"{count}{count_unit}")

    prefix = {"food": "HB", "cosmetic": "CS", "general": "EL"}[reg]
    return {
        "sku": f"{prefix}-E{idx:04d}",
        "name": (
            f"{brand} {item} {spec_str} {count}{count_unit}"
            if has_count else f"{brand} {item} {spec_str}"
        ),
        "brand": brand,
        "category": category,
        "regulated_category": reg,
        "price": rng.choice([290, 390, 490, 690, 890, 1180, 1580, 2290, 3290, 4680]),
        "specs": specs,
        "must_include_keywords": must,
        "brand_tone": tone,
        "target_audience": rng.choice(AUDIENCES[reg]),
    }


def build(count: int = 200, seed: int = 20260821) -> dict:
    rng = random.Random(seed)

    # 手寫的 12 筆放最前面。
    #
    # 它們的規格比組合生成的豐富（多欄位、真實的台灣電商品名），適合用在
    # demo 裡「看一下 v0 跟 v3 的文案差在哪」那一段 —— 那需要人看得懂的商品。
    # 後面接組合生成的，補足統計需要的樣本量。
    #
    # 這樣 demo 與評測用同一份資料，不會再出現「demo 說 12 筆、結論說 50 筆」
    # 這種要額外解釋的分裂。
    handwritten = json.loads(
        (pathlib.Path(__file__).parent / "products.json").read_text(encoding="utf-8")
    )["products"]

    cycle = ["food", "cosmetic", "general"]
    seen: set[str] = {p["name"] for p in handwritten}
    unique: list[dict] = list(handwritten)
    attempts = 0
    while len(unique) < count and attempts < count * 50:
        reg = cycle[len(unique) % 3]
        p = _make_product(rng, len(unique) + 1, reg)
        attempts += 1
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        unique.append(p)

    if len(unique) < count:
        raise RuntimeError(
            f"模板組合數不足，只湊到 {len(unique)}/{count} 筆。"
            "請在 FOOD_ITEMS / COSMETIC_ITEMS / GENERAL_ITEMS 增加品項。"
        )

    return {
        "_meta": {
            "description": f"評測用商品資料集，前 {len(handwritten)} 筆為手寫，其餘由 seed={seed} 組合產生。",
            "note": "notebook 與 run_eval.py 共用這一份 —— demo 與評測是同一組數字，不再分裂。",
            "handwritten_count": len(handwritten),
            "count": len(unique),
            "seed": seed,
            "channel_limits": {
                "shopee_title_max": 60,
                "momo_title_max": 50,
                "seo_desc_max": 120,
                "bullet_max": 30,
            },
        },
        "products": unique,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260821)
    args = ap.parse_args()

    data = build(args.count, args.seed)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    products = data["products"]
    by_reg: dict[str, int] = {}
    by_brand: dict[str, int] = {}
    for p in products:
        by_reg[p["regulated_category"]] = by_reg.get(p["regulated_category"], 0) + 1
        by_brand[p["brand"]] = by_brand.get(p["brand"], 0) + 1

    print(f"✓ {OUT.name}：{len(products)} 筆（seed={args.seed}）")
    print("  法規類別：" + "　".join(f"{k} {v}" for k, v in sorted(by_reg.items())))
    print("  品牌分佈：" + "　".join(f"{k} {v}" for k, v in sorted(by_brand.items())))
    print(f"  檔案大小：{OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
