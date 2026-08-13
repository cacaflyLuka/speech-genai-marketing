"""規則層的離線測試。

用手寫的「模型可能產出什麼」樣本，驗證評測邏輯本身是對的 —— 不需要 API、不花錢。
這也是 demo 前一天的保險：就算 GCP 掛掉，這些測試仍能證明評測邏輯沒壞。

執行：python3 -m pytest poc/tests/ -v     或     python3 poc/tests/test_rules.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poc.src import prompts, rules  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
PRODUCTS = json.loads((DATA / "products.json").read_text(encoding="utf-8"))["products"]
BANNED = json.loads((DATA / "banned_terms.json").read_text(encoding="utf-8"))

LUTEIN = next(p for p in PRODUCTS if p["sku"] == "HB-1001")
EARBUDS = next(p for p in PRODUCTS if p["sku"] == "EL-3001")


# --------------------------------------------------------------------------
# 四個版本的「典型產出」樣本（手寫，模擬真實模型行為）
# --------------------------------------------------------------------------

SAMPLE_V0 = """## ✨【護眼首選・熱銷回購】晨光研選 金盞花萃取葉黃素膠囊 — 給你的靈魂之窗最溫柔的守護，長效呵護每一天的清晰視界，現在下單再享優惠！

在這個滿是螢幕的時代，你的眼睛值得最好的呵護。

我們採用頂級金盞花萃取，每一粒都蘊含豐富的游離型葉黃素，能夠有效改善視力，
長期補充還能增強免疫力，讓你告別疲勞。

現在就開始，給眼睛最好的保護吧！"""

SAMPLE_V1 = """標題：晨光研選 金盞花葉黃素膠囊 60粒 游離型30mg 每日一粒

賣點：
- 游離型葉黃素30mg，吸收更直接
- 添加玉米黃素6mg，黃金比例
- 植物膠囊好吞嚥，全素可食
- 台灣製造，每日一粒護眼有感

SEO描述：晨光研選葉黃素膠囊60粒裝，添加游離型葉黃素30mg與玉米黃素，
專為長時間用眼的上班族設計，能有效改善視力疲勞，每日一粒隨餐食用。

#葉黃素 #護眼 #保健食品"""

SAMPLE_V2 = """標題：晨光研選 金盞花葉黃素膠囊 60粒 游離型30mg 全素可食

賣點：
- 游離型葉黃素30mg，無需轉換
- 添加玉米黃素6mg，複方設計
- 植物膠囊，全素者可食用
- 台灣製造，每日一粒隨餐

SEO描述：晨光研選金盞花萃取葉黃素膠囊，每盒60粒，含游離型葉黃素30mg與玉米黃素6mg，
植物膠囊全素可食，適合長時間面對螢幕的日常補充，建議每日一粒隨餐食用。

#葉黃素 #金盞花 #全素可食"""

SAMPLE_V3 = json.dumps(
    {
        "title": "晨光研選 金盞花葉黃素膠囊 60粒 游離型30mg 全素可食",
        "bullets": [
            "游離型葉黃素30mg，無需轉換",
            "添加玉米黃素6mg，複方設計",
            "植物膠囊，全素者可食用",
            "台灣製造，每日一粒隨餐",
        ],
        "seo_description": (
            "晨光研選金盞花萃取葉黃素膠囊，每盒60粒，含游離型葉黃素30mg與玉米黃素6mg，"
            "植物膠囊全素可食，適合長時間面對螢幕的日常補充。"
        ),
        "hashtags": ["葉黃素", "金盞花", "全素可食"],
    },
    ensure_ascii=False,
)

SAMPLES = {"v0": SAMPLE_V0, "v1": SAMPLE_V1, "v2": SAMPLE_V2, "v3": SAMPLE_V3}


def _eval(version: str, product=LUTEIN):
    terms = prompts.get_banned_terms_for(product, BANNED)
    return rules.evaluate_rules(SAMPLES[version], product, version, terms)


# --------------------------------------------------------------------------
# 測試
# --------------------------------------------------------------------------

def test_v0_fails_broadly():
    """v0 應該在多個面向失敗，才有改善空間可以展示。"""
    r = _eval("v0")
    assert not r.schema_valid, "v0 是自由文字，不該被判定為結構化"
    assert not r.banned_clean, "v0 應命中禁詞（護眼／改善視力／增強免疫力）"
    assert r.spec_coverage < 1.0, "v0 應漏掉部分必含規格"
    assert not r.all_pass


def test_v0_title_exceeds_channel_limit():
    """naive 輸出的標題會超出蝦皮 60 字上限。

    註：這是「單一樣本」的行為。實際 demo 跑 12 個商品時，v0 在這一欄
    不會是乾淨的 0%，而是某個中間值 —— 講稿不要說死「v0 全部不合格」。
    """
    r = _eval("v0")
    assert not r.title_length_ok, f"v0 標題 {r.title_length} 字，應超過 60"


def test_length_check_cannot_see_semantic_garbage():
    """規則層只能檢查它看得懂的東西 —— 這是它的天花板。

    把 v0 的長標題截短，長度檢查就會通過，但那段文字仍然不是一個「標題」，
    只是文章的第一句話。規則層無法分辨。這正是為什麼還需要第二層 LLM judge。
    """
    fake = "這是一句還算短的開場白，但它根本不是商品標題\n\n內文開始..."
    r = rules.evaluate_rules(fake, LUTEIN, "demo", [])
    assert r.title_length_ok, "長度檢查會通過"
    assert not r.all_pass, "但其他規則仍會擋下來"


def test_v0_catches_the_expensive_violations():
    """v0 命中的必須包含醫療效能類禁詞 —— 這是罰最重的一類。"""
    r = _eval("v0")
    assert "改善視力" in r.banned_hits
    assert "增強免疫力" in r.banned_hits


def test_v1_fixes_length_and_specs():
    """v1 加了通路約束，長度與規格覆蓋應該修好。"""
    r = _eval("v1")
    assert r.title_length_ok, f"標題 {r.title_length} 字，應 <= 60"
    assert r.spec_coverage == 1.0, f"仍漏規格：{r.spec_missing}"


def test_v1_still_violates_regulations():
    """關鍵：v1 沒加法規約束，所以禁詞仍在。

    這個測試證明評測表的階梯是真的 —— v1 修好了長度但沒修好合規，
    如果這裡開始就全綠，demo 就失去說服力了。
    """
    r = _eval("v1")
    assert not r.banned_clean, "v1 不該通過禁詞檢查"
    assert "護眼" in r.banned_hits


def test_v2_fixes_regulations():
    """v2 加了禁詞清單，合規應該修好。"""
    r = _eval("v2")
    assert r.banned_clean, f"v2 仍命中禁詞：{r.banned_hits}"
    assert r.title_length_ok
    assert r.spec_coverage == 1.0


def test_v2_still_not_machine_readable():
    """v2 內容對了，但仍是自由文字，接不進系統。"""
    r = _eval("v2")
    assert not r.schema_valid, "v2 不該被判定為結構化"
    assert not r.all_pass, "v2 不該全過 —— 否則 v3 就沒有存在理由"


def test_v3_passes_everything():
    """v3 是唯一能全過的版本。這是 demo 的收斂點。"""
    r = _eval("v3")
    assert r.schema_valid
    assert r.title_length_ok
    assert r.bullet_length_ok
    assert r.seo_length_ok
    assert r.spec_coverage == 1.0
    assert r.banned_clean
    assert r.all_pass, "v3 應全數通過"


def test_staircase_is_monotonic():
    """整體通過的規則數必須逐版遞增，不能有倒退。

    這是整個 demo 的核心主張。若這個測試掛掉，代表 prompt 演進設計有問題，
    要回頭改 prompt，不是改測試。
    """
    def score(r):
        return sum(
            [
                r.schema_valid,
                r.title_length_ok,
                r.bullet_length_ok,
                r.seo_length_ok,
                r.spec_coverage == 1.0,
                r.banned_clean,
            ]
        )

    scores = [score(_eval(v)) for v in ["v0", "v1", "v2", "v3"]]
    assert scores == sorted(scores), f"階梯不是單調遞增：{scores}"
    assert scores[0] < scores[-1], f"v0 到 v3 沒有改善：{scores}"
    assert scores[-1] == 6, f"v3 應通過全部 6 項，實際 {scores[-1]}"


# --------------------------------------------------------------------------
# 規則層本身的正確性
# --------------------------------------------------------------------------

def test_banned_terms_are_category_specific():
    """3C 商品不該套用保健食品的禁詞。

    『護眼』對葉黃素是違規，對螢幕護目鏡不是。規則必須跟著商品屬性走 ——
    這是規則層在真實系統裡最容易做錯的地方。
    """
    food_terms = prompts.get_banned_terms_for(LUTEIN, BANNED)
    general_terms = prompts.get_banned_terms_for(EARBUDS, BANNED)

    assert "護眼" in food_terms
    assert "護眼" not in general_terms, "3C 不該繼承食品的身體功能禁詞"
    # 誇大類則是所有類別共用
    assert "保證有效" in food_terms and "保證有效" in general_terms


def test_longer_banned_term_wins():
    """『改善視力』命中時不該同時報『視力』類的短詞重複計數。"""
    hits = rules.check_banned("本產品能改善視力", ["改善視力", "改善"])
    assert hits == ["改善視力"], f"重疊詞處理錯誤：{hits}"


def test_structured_parse_tolerates_code_fence():
    """模型常自作主張包上 ```json，不該因此判定 schema 失敗。"""
    fenced = f"```json\n{SAMPLE_V3}\n```"
    parsed = rules.parse_output(fenced)
    assert parsed.is_structured
    assert parsed.title.startswith("晨光研選")


def test_freeform_parser_is_documented_as_fragile():
    """換一種排版，脆弱的 parser 就抓不到標題 —— 這是 v3 的存在理由。"""
    weird = "商品標題\n晨光研選 葉黃素膠囊\n\n賣點\n好吸收"
    parsed = rules.parse_output(weird)
    assert not parsed.is_structured
    # 抓到的是「商品標題」這四個字，不是真正的標題 —— 正是我們要展示的失敗
    assert parsed.title == "商品標題"


def test_suggest_fix_returns_alternatives():
    """規則層要能給修改方向，不只是擋下來。"""
    r = _eval("v0")
    fixes = rules.suggest_fix(r.banned_hits, BANNED)
    assert fixes, "應該至少對一個禁詞給出替代寫法"
    assert all(isinstance(v, str) and v for v in fixes.values())


if __name__ == "__main__":
    import traceback

    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}\n        {e}")
        except Exception:
            failed += 1
            print(f"  ERROR {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
