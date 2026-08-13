"""場景 B 的離線測試：驗證抽取結果的檢查邏輯。

同樣不需要 API。重點在證明「抽取任務也能自動評測」—— 這是演講「轉 4」的論據。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poc.src.insights import ReviewInsight, business_summary, validate_insights  # noqa: E402


def _r(rid, rating, sentiment, aspects, about_product=True, urgency="low", sug=""):
    return ReviewInsight(
        review_id=rid,
        sku="X-1",
        rating=rating,
        sentiment=sentiment,
        aspects=aspects,
        is_about_product=about_product,
        actionable_suggestion=sug,
        urgency=urgency,
    )


def test_clean_batch_passes():
    insights = [
        _r("R1", 5, "positive", ["產品品質"]),
        _r("R2", 2, "negative", ["物流配送"], about_product=False),
    ]
    out = validate_insights(insights)
    assert out["問題筆數"] == 0
    assert out["通過率"] == 100.0


def test_detects_rating_sentiment_contradiction():
    """1 星卻判 positive —— 模型理解錯了，比寫得不好嚴重。"""
    out = validate_insights([_r("R1", 1, "positive", ["產品品質"])])
    assert out["問題筆數"] == 1
    assert "positive" in out["明細"][0][1]


def test_detects_high_rating_negative():
    out = validate_insights([_r("R1", 5, "negative", ["產品品質"])])
    assert out["問題筆數"] == 1


def test_detects_illegal_aspect_value():
    """enum 外的值必須被抓到，否則進 BigQuery 會污染維度。"""
    out = validate_insights([_r("R1", 3, "neutral", ["宇宙無敵面向"])])
    assert out["問題筆數"] == 1
    assert "未定義值" in out["明細"][0][1]


def test_extraction_error_is_counted():
    bad = _r("R1", 3, "neutral", [])
    bad.error = "timeout"
    out = validate_insights([bad])
    assert out["問題筆數"] == 1
    assert "抽取失敗" in out["明細"][0][1]


def test_five_star_high_urgency_is_flagged():
    out = validate_insights([_r("R1", 5, "positive", ["產品品質"], urgency="high")])
    assert out["問題筆數"] == 1


def test_summary_separates_product_from_service():
    """核心商業邏輯：商品負評與服務負評必須分開統計。

    如果混在一起，採購會以為商品品質有問題，實際上是物流慢。
    這是這個場景真正的價值所在，不是情緒分類本身。
    """
    insights = [
        _r("R1", 1, "negative", ["產品品質"], about_product=True),
        _r("R2", 1, "negative", ["物流配送"], about_product=False),
        _r("R3", 1, "negative", ["物流配送"], about_product=False),
    ]
    text = business_summary(insights)
    assert "商品相關負評     1 則" in text
    assert "服務相關負評     2 則" in text


def test_summary_survives_all_errors():
    bad = _r("R1", 3, "neutral", [])
    bad.error = "boom"
    assert business_summary([bad]) == "無有效資料"


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
