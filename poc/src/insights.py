"""場景 B：評論洞察分析。

方法論與場景 A 完全相同，方向相反：
    場景 A  結構化資料 → 非結構化文字   （生成）
    場景 B  非結構化文字 → 結構化資料   （抽取）

這一節的重點不是評論分析本身，而是證明**這是一套可遷移的流程，
不是一個文案技巧**。同樣要 schema、同樣要評測、同樣要算成本。

商業價值一句話：把「客服每天讀 500 則評論」變成「BigQuery 一句 SQL」。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import config

ASPECTS = ["產品品質", "價格", "物流配送", "包裝", "客服", "使用體驗", "其他"]

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {
            "type": "string",
            "enum": ["positive", "neutral", "negative"],
        },
        "aspects": {
            "type": "array",
            "items": {"type": "string", "enum": ASPECTS},
            "description": "這則評論實際談到的面向，可多選",
        },
        "is_about_product": {
            "type": "boolean",
            "description": "評論主體是商品本身，還是物流／客服等非商品因素",
        },
        "actionable_suggestion": {
            "type": "string",
            "description": "可執行的改善建議；若無則填空字串",
        },
        "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": [
        "sentiment",
        "aspects",
        "is_about_product",
        "actionable_suggestion",
        "urgency",
    ],
}

EXTRACT_PROMPT = """你是電商營運分析師，要把客戶評論轉成結構化資料進資料倉儲。

【重要判準】
- `is_about_product`：評論在抱怨物流慢、客服態度、包裝破損時，**主體不是商品**，
  應為 false。這一欄的用途是把「商品不好」和「服務不好」分開 ——
  兩者要交給不同部門處理，混在一起會導致採購端誤判商品品質。
- `urgency`：只有涉及安全疑慮、法規風險、或大量客戶可能受影響時才是 high。
  單純的個人喜好不合不算。
- `actionable_suggestion`：必須是團隊真的能執行的動作（改包裝、補說明、調規格），
  不要寫「提升品質」這種無法執行的空話。無明確建議就留空字串。

【評論】
商品：{product_name}
評分：{rating} 星
內容：{text}

請依 schema 輸出。"""


@dataclass
class ReviewInsight:
    review_id: str
    sku: str
    rating: int
    sentiment: str
    aspects: list[str]
    is_about_product: bool
    actionable_suggestion: str
    urgency: str
    error: str | None = None


def extract_one(client, review: dict, product_name: str, ledger=None) -> ReviewInsight:
    """把單則評論轉成結構化資料。"""
    import time

    from google.genai import types

    from .generation import Usage

    prompt = EXTRACT_PROMPT.format(
        product_name=product_name,
        rating=review["rating"],
        text=review["text"],
    )

    started = time.time()
    try:
        resp = client.models.generate_content(
            model=config.GEN_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,  # 抽取任務要可重現，不要創意
                response_mime_type="application/json",
                response_schema=REVIEW_SCHEMA,
            ),
        )
        meta = resp.usage_metadata
        if ledger is not None:
            ledger.record(
                "gen:insight",
                Usage(
                    model=config.GEN_MODEL,
                    input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
                    latency_s=round(time.time() - started, 2),
                ),
            )
        data = json.loads(resp.text)
        return ReviewInsight(
            review_id=review["review_id"],
            sku=review["sku"],
            rating=review["rating"],
            sentiment=data["sentiment"],
            aspects=list(data["aspects"]),
            is_about_product=bool(data["is_about_product"]),
            actionable_suggestion=data["actionable_suggestion"],
            urgency=data["urgency"],
        )
    except Exception as e:  # noqa: BLE001
        return ReviewInsight(
            review_id=review["review_id"],
            sku=review["sku"],
            rating=review["rating"],
            sentiment="neutral",
            aspects=[],
            is_about_product=True,
            actionable_suggestion="",
            urgency="low",
            error=str(e),
        )


def validate_insights(insights: list[ReviewInsight]) -> dict:
    """場景 B 也要評測 —— 這是本節的重點。

    抽取任務沒有「好文案」這種主觀標準，但仍有可自動檢查的規則：
    - enum 值是否合法
    - 星等與情緒是否矛盾（1 星卻標 positive，通常是抽取錯誤）
    - 高星等卻標 high urgency（同樣可疑）

    這些規則抓到的不是「模型寫得不好」，而是「模型理解錯了」—— 更嚴重。
    """
    issues = []
    for r in insights:
        if r.error:
            issues.append((r.review_id, f"抽取失敗：{r.error}"))
            continue
        if r.sentiment not in {"positive", "neutral", "negative"}:
            issues.append((r.review_id, f"sentiment 值非法：{r.sentiment}"))
        if bad := [a for a in r.aspects if a not in ASPECTS]:
            issues.append((r.review_id, f"aspects 出現未定義值：{bad}"))
        if r.rating <= 2 and r.sentiment == "positive":
            issues.append((r.review_id, f"{r.rating} 星卻判為 positive，疑似抽取錯誤"))
        if r.rating >= 4 and r.sentiment == "negative":
            issues.append((r.review_id, f"{r.rating} 星卻判為 negative，疑似抽取錯誤"))
        if r.rating == 5 and r.urgency == "high":
            issues.append((r.review_id, "5 星卻標記 high urgency，請人工確認"))

    return {
        "總筆數": len(insights),
        "問題筆數": len(issues),
        "通過率": round(100 * (len(insights) - len(issues)) / max(len(insights), 1), 1),
        "明細": issues,
    }


def to_dataframe(insights: list[ReviewInsight]):
    """轉成 DataFrame。欄位刻意設計成可直接進 BigQuery 的扁平結構。"""
    import pandas as pd

    rows = []
    for r in insights:
        d = asdict(r)
        d["aspects"] = "|".join(r.aspects)  # BigQuery 可用 SPLIT() 還原
        rows.append(d)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# BigQuery —— 把「AI 當 ETL」這件事真的做完
# --------------------------------------------------------------------------
BQ_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS `{{project}}.{{dataset}}.{{table}}` (
  review_id             STRING  NOT NULL,
  sku                   STRING  NOT NULL,
  rating                INT64,
  sentiment             STRING,          -- positive / neutral / negative
  aspects               ARRAY<STRING>,   -- 一則評論可能談到多個面向
  is_about_product      BOOL,            -- 把商品問題與服務問題分開的關鍵欄位
  actionable_suggestion STRING,
  urgency               STRING,          -- low / medium / high
  ingested_at           TIMESTAMP
)
PARTITION BY DATE(ingested_at)
CLUSTER BY sku, sentiment
"""

# 這句 SQL 就是整個場景 B 的商業價值：客服原本要讀 500 則評論，現在是一句查詢。
BQ_INSIGHT_SQL = """
SELECT
  sku,
  COUNTIF(is_about_product AND sentiment = 'negative') AS 商品負評,
  COUNTIF(NOT is_about_product AND sentiment = 'negative') AS 服務負評,
  COUNTIF(urgency = 'high')                             AS 高急迫,
  ROUND(AVG(rating), 2)                                 AS 平均星等
FROM `{project}.{dataset}.{table}`
GROUP BY sku
HAVING 商品負評 > 0 OR 服務負評 > 0
ORDER BY 商品負評 DESC, 服務負評 DESC
"""


def load_to_bigquery(insights: list[ReviewInsight], verbose: bool = True):
    """把抽取結果寫進 BigQuery。

    這一步讓「非結構化文字 → 結構化資料」這句話變成真的 —— 資料真的落地、
    真的能被 SQL 查詢、真的能接上既有的 BI 報表。

    schema 的設計重點在 `is_about_product`：把「商品不好」與「服務不好」
    分開儲存。混在一起統計，採購會以為商品品質有問題，實際上是物流慢。
    """
    from datetime import datetime, timezone

    from google.cloud import bigquery

    client = bigquery.Client(project=config.PROJECT_ID)
    ds_id = f"{config.PROJECT_ID}.{config.BQ_DATASET}"

    ds = bigquery.Dataset(ds_id)
    ds.location = config.BQ_LOCATION
    client.create_dataset(ds, exists_ok=True)

    table_ref = f"{ds_id}.{config.BQ_TABLE}"
    client.query(
        BQ_SCHEMA_SQL.format(
            project=config.PROJECT_ID, dataset=config.BQ_DATASET, table=config.BQ_TABLE
        )
    ).result()

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "review_id": r.review_id,
            "sku": r.sku,
            "rating": r.rating,
            "sentiment": r.sentiment,
            "aspects": r.aspects,
            "is_about_product": r.is_about_product,
            "actionable_suggestion": r.actionable_suggestion,
            "urgency": r.urgency,
            "ingested_at": now,
        }
        for r in insights
        if not r.error
    ]
    if not rows:
        raise RuntimeError("沒有可寫入的資料（全部抽取失敗）")

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"BigQuery 寫入失敗：{errors}")

    if verbose:
        print(f"✓ 已寫入 {len(rows)} 列 → {table_ref}")
        print(f"  分區：DATE(ingested_at)　叢集：sku, sentiment")
    return table_ref


def query_bigquery_insights():
    """跑那句「取代人工讀 500 則評論」的 SQL。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=config.PROJECT_ID)
    sql = BQ_INSIGHT_SQL.format(
        project=config.PROJECT_ID, dataset=config.BQ_DATASET, table=config.BQ_TABLE
    )
    return client.query(sql).to_dataframe()


def business_summary(insights: list[ReviewInsight]) -> str:
    """重點在這裡：資料變成決策。"""
    ok = [r for r in insights if not r.error]
    if not ok:
        return "無有效資料"

    product_issues = [r for r in ok if r.is_about_product and r.sentiment == "negative"]
    service_issues = [
        r for r in ok if not r.is_about_product and r.sentiment == "negative"
    ]
    urgent = [r for r in ok if r.urgency == "high"]

    aspect_counts: dict[str, int] = {}
    for r in ok:
        if r.sentiment == "negative":
            for a in r.aspects:
                aspect_counts[a] = aspect_counts.get(a, 0) + 1

    top = sorted(aspect_counts.items(), key=lambda kv: -kv[1])[:3]
    suggestions = [r.actionable_suggestion for r in ok if r.actionable_suggestion]

    lines = [
        f"有效評論 {len(ok)} 則",
        "",
        f"  商品相關負評   {len(product_issues):>3} 則  → 採購／研發要看",
        f"  服務相關負評   {len(service_issues):>3} 則  → 物流／客服要看",
        f"  高急迫案件     {len(urgent):>3} 則  → 今天就要處理",
        "",
        "負評集中的面向：",
    ]
    lines += [f"  {a}：{c} 則" for a, c in top] or ["  （無）"]
    lines += ["", f"可執行建議 {len(suggestions)} 條，例如："]
    lines += [f"  - {s}" for s in suggestions[:3]]
    lines += [
        "",
        "↑ 這就是價值所在：把「客服每天讀 500 則評論」變成一句 SQL。",
        "  注意『商品負評』與『服務負評』已經分開 —— 混在一起會讓採購誤判商品品質。",
    ]
    return "\n".join(lines)
