"""評測第二層：LLM-as-judge，採用**二元自適應 rubric**（pass / fail 檢查清單）。

只評「規則層評不了」的東西 —— 語調、賣點覆蓋這類需要語意理解的維度。
順序很重要：**先跑規則層，被擋下來的不必送 judge**，省下的是真金白銀。

---

## 為什麼不用 1–5 分？

這是這個模組最重要的設計決定。

早期的 LLM-as-judge 幾乎都用 Likert 量表（1–5 分）。實務上它有幾個難以修復的問題：

- **分數擠在中間。** 模型很少給 1 或 5，結果多數樣本都是 3–4 分，鑑別度低。
- **不可重現。** 同一份文案今天 4 分明天 3 分，你無法判斷是模型變差還是評審漂移。
- **跨模型不一致。** 換一個評審模型，整組分數就平移，歷史數據全部作廢。
- **容易被長度騙。** 寫得長、寫得華麗容易拿高分，這正是 verbosity bias。
- **「3.8 分」無法行動。** 你不知道要改什麼。

二元 rubric 把一個模糊的大問題拆成一組**具體、可檢查的 yes/no 小問題**：

    ✗  「這份文案的品質有幾分？」        → 3.8 / 5，然後呢？
    ✓  「文案是否提到 30mg 這個含量？」  → 否 → 知道要補什麼

好處是直接的：**判準明確、可重現、可累積、能直接對應到修改動作**，
而且 pass/fail 很難用堆字數來灌水。這也是為什麼 Vertex AI 的
Gen AI Evaluation Service 把 adaptive rubrics 形容成「像單元測試」。

> 註：Vertex AI 有託管版本的 rubric 評測。本模組選擇手寫，原因有二：
> 一是要看得到 rubric 長什麼樣子，那才是可帶走的概念；
> 二是託管服務的 SDK 介面仍在變動（本機安裝的 `vertexai.evaluation`
> 只有舊的 Likert 型 PointwiseMetric，新的 adaptive rubric 走另一個介面）。
> 概念完全相同，要換成託管版本時，換的是呼叫方式，不是方法論。

---

## 公平性：rubric 只從商品資料生成，不看被評的文案

這點很容易做錯，做錯了整張對比表就沒有意義。

rubric **對每個商品產生一次，v0～v3 共用同一組**。
如果讓評審看著文案即興出題，每個版本會被問不同的問題，
分數就不可比 —— 那等於每個考生考不同的考卷。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import config

# --------------------------------------------------------------------------
# 已知偏誤與本專案的緩解方式
# --------------------------------------------------------------------------
JUDGE_BIASES = {
    "self-preference": {
        "說明": "模型傾向給自己產出的內容較高分。",
        "緩解": f"評審模型（{config.JUDGE_MODEL}）與生成模型（{config.GEN_MODEL}）刻意選不同的。",
    },
    "verbosity": {
        "說明": "較長、較華麗的回答容易被評為較好，即使內容沒有更好。",
        "緩解": "改用 pass/fail 判準，「有沒有提到 30mg」無法靠寫得長來灌水。",
    },
    "position": {
        "說明": "成對比較時，先出現的選項容易獲勝。",
        "緩解": "採 pointwise（單篇對照 rubric），不做 pairwise，從源頭避開。",
    },
    "score-clustering": {
        "說明": "Likert 分數容易全部擠在 3–4 分，鑑別度低且不可重現。",
        "緩解": "不用分數。二元判準沒有中間地帶可以躲。",
    },
    "criteria-drift": {
        "說明": "評審每次自己想判準，等於每個版本考不同的考卷。",
        "緩解": "rubric 只從商品資料生成一次，v0～v3 共用同一組。",
    },
}

# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
RUBRIC_GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "rubrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "R1, R2, ..."},
                    "criterion": {
                        "type": "string",
                        "description": "一句可用是／否回答的具體判準",
                    },
                    "dimension": {
                        "type": "string",
                        "enum": ["賣點覆蓋", "品牌語調", "消費者可讀性"],
                    },
                    "critical": {
                        "type": "boolean",
                        "description": "未通過就不該上架者為 true",
                    },
                },
                "required": ["id", "criterion", "dimension", "critical"],
            },
        }
    },
    "required": ["rubrics"],
}

RUBRIC_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "evidence": {
                        "type": "string",
                        "description": "通過就引用文案中的原文；未通過就說明缺什麼",
                    },
                },
                "required": ["id", "passed", "evidence"],
            },
        }
    },
    "required": ["results"],
}

# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
RUBRIC_GEN_PROMPT = """你是資深電商文案主管，要為一個商品訂出「文案驗收清單」。

這份清單會用來檢查 AI 產出的文案能不能上架。請產生 7 條判準。

【⚠️ 最重要：字數預算】
被檢查的文案有嚴格的通路字數限制，總共只有約 {total_budget} 個字：

  - 標題：最多 {title_max} 字
  - 賣點：{bullet_count} 條，每條最多 {bullet_max} 字
  - SEO 描述：最多 {seo_max} 字

**你的每一條判準都必須是在這個字數預算內可以達成的。**

這是最容易出錯的地方。不要寫出需要長篇說明才能滿足的判準：

  ✗ 「文案是否說明為何隨餐食用有助吸收？」    （解釋機制，30 字的賣點塞不下）
  ✗ 「文案是否說明黃金比例能提供更全面的保護？」（同上）
  ✓ 「文案是否寫出葉黃素 30mg 的含量？」       （幾個字就能達成）
  ✓ 「文案是否點出適合長時間看螢幕的族群？」    （一句話能達成）

**如果一條判準只有把文案寫長才可能通過，它就是壞判準。**
壞判準會讓冗長雜亂的文案得高分、讓精簡合規的文案被扣分，
整張評測表的結論就會顛倒。

【判準的寫法】
- 每一條都必須能用「是」或「否」回答，不可以是程度問題。
  ✗ 「文案的語氣是否夠專業？」（程度問題，無法一致判定）
  ✓ 「文案是否避免使用驚嘆號？」（可以直接看出來）
- 判準要**具體指向這個商品**，不要寫成通用的空話。

【⚠️ 不可與規則層衝突】
以下規格關鍵字是**硬性要求**，文案一定會出現它們：

  {must_include}

**絕對不可以寫出「避免使用某某專有名詞」這類會懲罰上述關鍵字的判準。**

這是真實踩過的坑：規則層要求文案必須寫出「游離型葉黃素 30mg」，
rubric 卻出了一條「是否避免使用『游離型』這種需要解釋的專有名詞」——
兩層互相打架，文案怎麼寫都會被扣分，整張評測表就失去意義。

你可以要求「把專有名詞轉成好懂的說法」，但不可以要求「不要出現它」。

【其他不要納入的範圍】
以下已由程式規則自動檢查，**不要**寫成判準：字數是否超標、JSON 格式是否合法、
法規禁詞、必含關鍵字是否存在。你只負責語意層面。

【維度分配 — 必須照這個比例，不可偏重賣點覆蓋】
- 賣點覆蓋：3 條（把規格轉成消費者看得懂的好處，但要在字數內可達成）
- 品牌語調：2 條（是否符合下面的品牌語調設定）
- 消費者可讀性：2 條（是否精簡、無冗詞、無誇大語氣、可直接上架）

【critical 的判定】
未通過就不該上架的設為 true，請設 2 條為 critical。

【商品資料】
商品名稱：{name}
品牌：{brand}
品牌語調設定：{brand_tone}
目標受眾：{audience}
規格：
{specs}

請依 schema 輸出判準清單。"""

RUBRIC_CHECK_PROMPT = """你是電商文案審核員。請對照驗收清單逐條檢查下面這份文案。

【文案的字數預算】
這份文案受通路限制，總共只有約 {total_budget} 個字可用
（標題 {title_max} 字、{bullet_count} 條賣點各 {bullet_max} 字、SEO 描述 {seo_max} 字）。

**請在這個前提下判斷。** 文案簡潔不是缺點，那是通路要求。
不要因為文案沒有展開說明、沒有解釋原理就判定不通過 ——
只要在字數內把該講的講到了，就算通過。

【檢查原則】
- 每一條**只回答通過或不通過**，不要給分數。
- 判斷依據只能是文案中實際出現的內容，不要腦補。
- 通過時，`evidence` 請引用文案中的原文片段。
- 不通過時，`evidence` 請說明缺少什麼。
- **絕對不要因為文案較長、較華麗就傾向通過。**
  冗長、堆砌形容詞、重複同一個賣點，在「消費者可讀性」維度應判為不通過。
- 文案可能是自由文字，也可能是 JSON，兩者一視同仁看內容。

【驗收清單】
{rubric_list}

【待檢查的文案】
{copy_text}

請依 schema 逐條回覆，results 的長度必須與清單條數相同。"""


# --------------------------------------------------------------------------
# 資料結構
# --------------------------------------------------------------------------
@dataclass
class Rubric:
    id: str
    criterion: str
    dimension: str
    critical: bool


@dataclass
class RubricSet:
    sku: str
    rubrics: list[Rubric] = field(default_factory=list)
    error: str | None = None

    def as_prompt_list(self) -> str:
        return "\n".join(
            f"{r.id}. [{r.dimension}]{'（critical）' if r.critical else ''} {r.criterion}"
            for r in self.rubrics
        )


@dataclass
class RubricReport:
    sku: str
    version: str
    passed_ids: list[str] = field(default_factory=list)
    failed: list[tuple[str, str, bool]] = field(default_factory=list)  # (id, 原因, critical)
    total: int = 0
    error: str | None = None

    @property
    def pass_rate(self) -> float:
        return round(100 * len(self.passed_ids) / self.total, 1) if self.total else 0.0

    @property
    def critical_failures(self) -> int:
        return sum(1 for _, _, crit in self.failed if crit)

    @property
    def would_publish(self) -> bool:
        """critical 全過，且整體通過率達 80% 才算能上架。"""
        return self.total > 0 and self.critical_failures == 0 and self.pass_rate >= 80.0


# --------------------------------------------------------------------------
# 呼叫
# --------------------------------------------------------------------------
def _call_json(client, prompt: str, schema: dict, tag: str, ledger=None, max_retries: int = 4):
    """走 structured output 呼叫評審模型並解析 JSON。

    評審本身也用 responseSchema —— 解析失敗會讓整張評測表出現空洞，
    比生成失敗更難察覺。

    **必須重試。** 這一層在高並行下會撞到配額限制（429）。原本沒有重試，
    失敗的那一筆會被上層 except 接住、變成一個帶 error 的空結果 ——
    評測表上看不出來，只會發現受評筆數少了幾筆。那比直接報錯更危險。

    429 的退避拉得比一般錯誤久：配額是時間窗限制，馬上重試只會再撞一次。
    """
    import random
    import time

    from .generation import Usage, gen_config

    last_err: Exception | None = None
    for attempt in range(max_retries):
        started = time.time()
        try:
            resp = client.models.generate_content(
                model=config.JUDGE_MODEL,
                contents=prompt,
                config=gen_config(
                    temperature=config.JUDGE_TEMPERATURE,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            meta = resp.usage_metadata
            if ledger is not None:
                ledger.record(
                    tag,
                    Usage(
                        model=config.JUDGE_MODEL,
                        input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
                        output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
                        latency_s=round(time.time() - started, 2),
                    ),
                )
            return json.loads(resp.text)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == max_retries - 1:
                break
            text = str(e)
            throttled = "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower()
            base = 8.0 if throttled else 1.5
            # 加抖動，避免所有執行緒在同一刻一起重試又一起撞牆
            time.sleep(base * (2**attempt) + random.uniform(0, 1.5))

    raise RuntimeError(f"評審呼叫失敗（重試 {max_retries} 次）：{last_err}")


def _budget() -> dict:
    """文案的字數預算。

    rubric 生成與檢查都必須知道這個數字，否則會產生「解釋原理」這種
    在 30 字賣點裡不可能達成的判準 —— 那會讓冗長的文案得高分、
    精簡合規的文案被扣分，整張評測表的結論顛倒過來。
    """
    total = (
        config.SHOPEE_TITLE_MAX
        + config.BULLET_COUNT * config.BULLET_MAX
        + config.SEO_DESC_MAX
    )
    return {
        "title_max": config.SHOPEE_TITLE_MAX,
        "bullet_count": config.BULLET_COUNT,
        "bullet_max": config.BULLET_MAX,
        "seo_max": config.SEO_DESC_MAX,
        "total_budget": total,
    }


def generate_rubrics(client, product: dict, ledger=None) -> RubricSet:
    """為單一商品產生驗收清單。

    ⚠️ 每個商品只做一次，v0～v3 共用。不要對每個版本重新生成 —— 那會讓
    每個版本被問不同的問題，對比表就失去意義。
    """
    specs = "\n".join(f"  - {k}：{v}" for k, v in product["specs"].items())
    prompt = RUBRIC_GEN_PROMPT.format(
        name=product["name"],
        brand=product["brand"],
        brand_tone=product["brand_tone"],
        audience=product["target_audience"],
        specs=specs,
        # 讓 rubric 生成知道哪些字是規則層的硬性要求，否則會出現
        # 「避免使用這個專有名詞」這種與規則層打架的判準。
        must_include="、".join(product["must_include_keywords"]),
        **_budget(),
    )
    try:
        data = _call_json(client, prompt, RUBRIC_GEN_SCHEMA, "judge:rubric_gen", ledger)
        return RubricSet(
            sku=product["sku"],
            rubrics=[
                Rubric(
                    id=str(r["id"]),
                    criterion=str(r["criterion"]),
                    dimension=str(r["dimension"]),
                    critical=bool(r["critical"]),
                )
                for r in data["rubrics"]
            ],
        )
    except Exception as e:  # noqa: BLE001
        return RubricSet(sku=product["sku"], error=str(e))


def check_against_rubrics(
    client,
    copy_text: str,
    rubric_set: RubricSet,
    version: str,
    ledger=None,
) -> RubricReport:
    """逐條檢查文案。"""
    if rubric_set.error or not rubric_set.rubrics:
        return RubricReport(
            sku=rubric_set.sku,
            version=version,
            error=rubric_set.error or "沒有可用的 rubric",
        )

    by_id = {r.id: r for r in rubric_set.rubrics}
    prompt = RUBRIC_CHECK_PROMPT.format(
        rubric_list=rubric_set.as_prompt_list(),
        copy_text=copy_text[:4000],  # 防止異常長輸出把成本吃掉
        **_budget(),
    )
    try:
        data = _call_json(client, prompt, RUBRIC_CHECK_SCHEMA, f"judge:{version}", ledger)
        passed, failed = [], []
        for row in data["results"]:
            rid = str(row["id"])
            rub = by_id.get(rid)
            if rub is None:
                continue  # 評審捏造了不存在的 id，忽略
            if bool(row["passed"]):
                passed.append(rid)
            else:
                failed.append((rid, str(row.get("evidence", "")), rub.critical))
        return RubricReport(
            sku=rubric_set.sku,
            version=version,
            passed_ids=passed,
            failed=failed,
            total=len(by_id),
        )
    except Exception as e:  # noqa: BLE001
        return RubricReport(sku=rubric_set.sku, version=version, error=str(e))


def should_judge(rule_result) -> bool:
    """規則層已經擋下的，就不要送 judge —— 這是省錢的關鍵。

    語意檢查對一份已經違反法規的文案沒有意義，而每一次 judge 呼叫
    都是用比生成更貴的模型在燒錢。
    """
    return rule_result.banned_clean and rule_result.spec_coverage > 0.5


def summarize_rubrics(
    reports: list[RubricReport], total_items: int | None = None
) -> dict[str, dict[str, float]]:
    """彙整成 {版本: 指標}，供對比表使用。

    `total_items` 是**每個版本應有的商品總數**（例如 12）。給了它，
    「可直接上架%」就會用固定分母計算，把規則層擋下、沒送評分的那些
    一律算成不可上架。

    為什麼一定要這樣做 —— 這是實測踩到的坑：

    規則層擋下的都是最爛的那幾筆，它們不會進 rubric 評分。結果 v0 只有
    10 筆受評、v1～v3 各 12 筆，v0 的平均分被「倖存者偏差」灌水成
    74.3%，看起來比實際好。**兩個版本用不同分母，就不能直接比。**

    處理方式：
    - 「可直接上架%」用固定分母。被規則層擋下的本來就不能上架，
      算成不通過完全合理，這樣跨版本才可比，也是真正該拿來做決策的數字。
    - 「rubric通過率%」維持只在受評項目上平均（否則無法區分「沒評」與
      「評了但沒過」），但一定要一起看「受評筆數」。分母不同時不要直接比。
    """
    by_version: dict[str, list[RubricReport]] = {}
    for r in reports:
        if r.error:
            continue
        by_version.setdefault(r.version, []).append(r)

    out = {}
    for version, rows in sorted(by_version.items()):
        if not rows:
            continue
        denom = total_items or len(rows)
        out[version] = {
            "rubric通過率%": round(sum(r.pass_rate for r in rows) / len(rows), 1),
            "critical違反數": sum(r.critical_failures for r in rows),
            "可直接上架%": round(100 * sum(r.would_publish for r in rows) / denom, 1),
            "受評筆數": len(rows),
            "分母": denom,
        }
    return out


def most_common_failures(reports: list[RubricReport], rubric_sets: dict, limit: int = 5):
    """哪些判準最常沒過 —— 這才是能拿去改 prompt 的資訊。

    這正是二元 rubric 勝過分數的地方：「3.8 分」不能行動，
    「有 9 個商品沒寫出含量」可以。
    """
    counts: dict[tuple[str, str], int] = {}
    for rep in reports:
        if rep.error:
            continue
        rs = rubric_sets.get(rep.sku)
        if not rs:
            continue
        text_by_id = {r.id: r.criterion for r in rs.rubrics}
        for rid, _reason, _crit in rep.failed:
            key = (rid, text_by_id.get(rid, rid))
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [(criterion, n) for (_rid, criterion), n in ranked]
