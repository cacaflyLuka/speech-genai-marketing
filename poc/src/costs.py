"""成本估算：從 demo 的實際用量外推到正式營運規模。

原則：**用公式，不要背數字。**
模型與價格每季在變（例如 Gemini 2.5 Flash-Lite 已公告 2026-10-16 退役），
任何寫死的價格很快就會過期。公式不會。

公式是穩定的，價格常數集中在 config，實際金額由執行結果給出。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass
class ScaleEstimate:
    """把 demo 用量外推到正式規模。"""

    sku_count: int
    regen_per_sku: float          # 每個 SKU 平均重新生成幾次（改版、A/B、季節性換檔）
    judge_ratio: float            # 送 judge 的比例（規則層擋掉的不送）
    gen_cost_per_item: float      # 單次生成成本 USD
    judge_cost_per_item: float    # 單次評審成本 USD

    @property
    def total_generations(self) -> float:
        return self.sku_count * self.regen_per_sku

    @property
    def gen_cost(self) -> float:
        return self.total_generations * self.gen_cost_per_item

    @property
    def judge_cost(self) -> float:
        return self.total_generations * self.judge_ratio * self.judge_cost_per_item

    @property
    def total_usd(self) -> float:
        return self.gen_cost + self.judge_cost

    @property
    def total_twd(self) -> float:
        return self.total_usd * config.USD_TO_TWD

    def render(self) -> str:
        return (
            f"規模假設：{self.sku_count:,} 個 SKU × 每個重生成 {self.regen_per_sku} 次"
            f" = {self.total_generations:,.0f} 次生成\n"
            f"           其中 {self.judge_ratio:.0%} 通過規則層、需要送 LLM 評審\n\n"
            f"  生成成本   {self.total_generations:>10,.0f} 次 × US${self.gen_cost_per_item:.6f}"
            f"  = US${self.gen_cost:>10,.2f}\n"
            f"  評審成本   {self.total_generations * self.judge_ratio:>10,.0f} 次 "
            f"× US${self.judge_cost_per_item:.6f}  = US${self.judge_cost:>10,.2f}\n"
            f"  {'─' * 58}\n"
            f"  合計                                       US${self.total_usd:>10,.2f}"
            f"  （約 NT${self.total_twd:,.0f}）"
        )


def estimate_from_ledger(
    ledger,
    sku_count: int = 100_000,
    regen_per_sku: float = 1.5,
    judge_ratio: float = 0.7,
) -> ScaleEstimate:
    """用 demo 實際跑出來的平均單次成本外推。

    這比任何通用估算都準，因為 prompt 長度、輸出長度、中文 token 密度
    全部是這個專案的真實值，不是別人部落格上的數字。
    """
    gen_calls = [u for t, u in ledger.calls if t.startswith("gen")]
    judge_calls = [u for t, u in ledger.calls if t.startswith("judge")]

    gen_avg = sum(u.cost_usd for u in gen_calls) / len(gen_calls) if gen_calls else 0.0
    judge_avg = (
        sum(u.cost_usd for u in judge_calls) / len(judge_calls) if judge_calls else 0.0
    )

    return ScaleEstimate(
        sku_count=sku_count,
        regen_per_sku=regen_per_sku,
        judge_ratio=judge_ratio,
        gen_cost_per_item=gen_avg,
        judge_cost_per_item=judge_avg,
    )


# --------------------------------------------------------------------------
# 降本四招
# --------------------------------------------------------------------------
LEVERS = [
    {
        "名稱": "模型選型降級",
        "作法": "簡單任務改用更小的模型；只有需要判斷力的環節才用大模型。",
        "省下": "視價差而定，通常是最大的一筆",
        "代價": "品質下降風險 —— **必須有評測表才敢降級**，否則是在賭。",
        "適用": "文案生成這種格式固定、判準明確的任務，通常降級後評測分數不會掉。",
    },
    {
        "名稱": "Batch API",
        "作法": "非即時的工作改走批次介面。商品文案本來就不需要即時。",
        "省下": "約 5 折",
        "代價": "延遲從秒級變成小時級。",
        "適用": "初次匯入全站商品、季節性全面改版 —— 這些場景根本不在乎即時性。",
    },
    {
        "名稱": "Context caching",
        "作法": "把共用的前綴（品牌指南、法規禁詞清單、few-shot 範例）快取起來。",
        "省下": "快取命中部分的 input token 大幅折扣",
        "代價": "有最低 token 門檻與存活時間，前綴要夠長、呼叫要夠密集才划算。",
        "適用": "本專案的 v2/v3 prompt 有大量固定前綴，是典型適用情境。",
    },
    {
        "名稱": "結果快取",
        "作法": "商品規格沒變就不要重新生成。用規格的 hash 當 key。",
        "省下": "取決於商品異動率，通常這是最被低估的一招",
        "代價": "幾乎沒有，只需要一個 key-value 存放。",
        "適用": "所有場景。很多團隊每天全量重跑，其實九成商品根本沒變。",
    },
]


def render_levers() -> str:
    out = []
    for i, lever in enumerate(LEVERS, 1):
        out.append(
            f"{i}. {lever['名稱']}（省下：{lever['省下']}）\n"
            f"   作法：{lever['作法']}\n"
            f"   代價：{lever['代價']}\n"
            f"   適用：{lever['適用']}"
        )
    return "\n\n".join(out)


def measure_chinese_token_density(client, samples: list[str]) -> dict:
    """實測中文的 token 密度，不要用經驗法則。

    直接量出來。中文的 token 密度會隨內容（純中文／中英混雜／
    含數字規格）明顯變動，背一個「一字約 X token」的數字是不可靠的。
    """
    from .generation import count_tokens

    rows = []
    for s in samples:
        tokens = count_tokens(client, s)
        chars = len(s)
        rows.append(
            {
                "字元數": chars,
                "token數": tokens,
                "每字token": round(tokens / chars, 3) if chars else 0,
                "預覽": s[:24] + ("..." if len(s) > 24 else ""),
            }
        )
    densities = [r["每字token"] for r in rows if r["每字token"]]
    return {
        "明細": rows,
        "平均每字token": round(sum(densities) / len(densities), 3) if densities else 0,
        "最低": min(densities) if densities else 0,
        "最高": max(densities) if densities else 0,
    }


def price_check_reminder() -> str:
    """執行前要印出來的提醒。"""
    return (
        f"⚠ 價格常數最後查證時間：{config.PRICE_LAST_CHECKED}\n"
        f"  上場前請到 https://cloud.google.com/vertex-ai/generative-ai/pricing "
        f"確認並更新 config.PRICING，\n"
        f"  然後把 PRICE_LAST_CHECKED 改成當天日期。\n"
        f"  不要引用固定的價格數字，以本 notebook 實際印出的金額為準。"
    )
