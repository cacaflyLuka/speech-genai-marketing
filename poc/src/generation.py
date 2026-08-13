"""呼叫 Gemini 產生文案，並記錄 token 用量。

用 google-genai 統一 SDK。同一份程式碼可切換 Vertex AI 與 Gemini API ——
只差 Client 的建構參數。重點是：
選 Vertex 還是 AI Studio 是**部署決策**，不是**程式碼決策**。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from . import config


def gen_config(**kwargs):
    """建立 generate_content 的 config 物件。

    為什麼不直接用 `types.GenerateContentConfig`：

    離線重播的使用情境是「把單一個 .ipynb 丟到一台沒有網路的機器」——
    這種時候 google-genai 很可能根本沒安裝，而安裝它就需要網路，
    整個「零網路」的前提就破功了。

    但重播其實不需要真的 SDK 型別：`ReplayClient` 只會讀 `response_schema`
    這一個屬性來判斷是不是結構化輸出。所以 SDK 不在時退回一個等效的
    簡單物件即可。

    只有 OFFLINE_MODE 才容許退回。連線模式下缺 SDK 是真的有問題，
    要讓它直接炸出來，不能靜默降級。
    """
    try:
        from google.genai import types

        return types.GenerateContentConfig(**kwargs)
    except ImportError:
        if not config.OFFLINE_MODE:
            raise
        return SimpleNamespace(**kwargs)


@dataclass
class Usage:
    """單次呼叫的 token 用量。所有成本計算都從這裡出發。"""

    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float

    @property
    def cost_usd(self) -> float:
        price = config.PRICING.get(self.model)
        if price is None:
            return 0.0
        return (
            self.input_tokens * price["input"] + self.output_tokens * price["output"]
        ) / 1_000_000


@dataclass
class GenResult:
    text: str
    usage: Usage
    error: str | None = None


@dataclass
class UsageLedger:
    """累計所有呼叫的用量 —— demo §5 成本計算的資料來源。

    刻意把 judge 的呼叫也記進來。評測本身要花錢，這是最常被漏算的一筆。
    """

    calls: list[tuple[str, Usage]] = field(default_factory=list)

    def record(self, tag: str, usage: Usage) -> None:
        self.calls.append((tag, usage))

    def total_cost_usd(self, tag_prefix: str | None = None) -> float:
        return sum(
            u.cost_usd
            for t, u in self.calls
            if tag_prefix is None or t.startswith(tag_prefix)
        )

    def total_tokens(self, tag_prefix: str | None = None) -> tuple[int, int]:
        rows = [u for t, u in self.calls if tag_prefix is None or t.startswith(tag_prefix)]
        return sum(u.input_tokens for u in rows), sum(u.output_tokens for u in rows)

    def summary(self) -> str:
        gen_in, gen_out = self.total_tokens("gen")
        jdg_in, jdg_out = self.total_tokens("judge")
        gen_cost = self.total_cost_usd("gen")
        jdg_cost = self.total_cost_usd("judge")
        total = gen_cost + jdg_cost
        judge_share = (jdg_cost / total * 100) if total else 0.0
        return (
            f"呼叫次數：{len(self.calls)}\n"
            f"  生成  input {gen_in:>7,} / output {gen_out:>7,} tokens → US${gen_cost:.4f}\n"
            f"  評審  input {jdg_in:>7,} / output {jdg_out:>7,} tokens → US${jdg_cost:.4f}\n"
            f"  合計                                        → US${total:.4f}"
            f"（約 NT${total * config.USD_TO_TWD:.2f}）\n"
            f"\n  ⚠ 評審佔總成本 {judge_share:.0f}% —— 這筆最常被漏算。"
        )


# --------------------------------------------------------------------------
# 離線重播 —— 會場網路不穩時的主要策略
# --------------------------------------------------------------------------
def fixture_key(model: str, contents: str, structured: bool) -> str:
    """以 (模型, prompt, 是否結構化) 當索引鍵。

    prompt 完全相同才會命中，所以只要 prompt 有任何改動，重播就會失敗並
    明確報錯 —— 不會靜默拿到舊資料。這是刻意的：寧可在測試時炸掉，
    也不要產出跟程式碼對不上的結果。
    """
    import hashlib

    raw = f"{model}\x00{int(structured)}\x00{contents}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class _ReplayModels:
    def __init__(self, fixtures: dict):
        self._f = fixtures
        self.hits = 0

    def generate_content(self, *, model, contents, config=None):
        structured = bool(config is not None and getattr(config, "response_schema", None))
        key = fixture_key(model, contents if isinstance(contents, str) else str(contents), structured)
        row = self._f.get("calls", {}).get(key)
        if row is None:
            raise KeyError(
                f"離線重播找不到對應輸出（key={key}, model={model}）。\n"
                f"代表 prompt 或模型在錄製之後被改過。\n"
                f"請重新錄製：把 RECORD_FIXTURES 設為 True、在有網路的環境跑一次。"
            )
        self.hits += 1
        return _Recorded(row["text"], row["input_tokens"], row["output_tokens"])

    def count_tokens(self, *, model, contents):
        key = "tok:" + fixture_key(model, contents, False)
        row = self._f.get("token_counts", {}).get(key)
        if row is None:
            raise KeyError(f"離線重播找不到 count_tokens 結果（key={key}）。請重新錄製。")
        self.hits += 1
        return _RecordedTokens(row)


class _Recorded:
    def __init__(self, text: str, pin: int, pout: int):
        self.text = text
        self.usage_metadata = _RecordedUsage(pin, pout)


class _RecordedUsage:
    def __init__(self, pin: int, pout: int):
        self.prompt_token_count = pin
        self.candidates_token_count = pout


class _RecordedTokens:
    def __init__(self, n: int):
        self.total_tokens = n


class ReplayClient:
    """從錄好的 fixtures 回放，完全不碰網路。"""

    def __init__(self, fixtures: dict):
        self.models = _ReplayModels(fixtures)


class _RecordingModels:
    def __init__(self, real):
        self._real = real
        self.fixtures = {"calls": {}, "token_counts": {}}

    def generate_content(self, *, model, contents, config=None):
        resp = self._real.generate_content(model=model, contents=contents, config=config)
        structured = bool(config is not None and getattr(config, "response_schema", None))
        key = fixture_key(model, contents if isinstance(contents, str) else str(contents), structured)
        meta = resp.usage_metadata
        self.fixtures["calls"][key] = {
            "text": resp.text or "",
            "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
        }
        return resp

    def count_tokens(self, *, model, contents):
        resp = self._real.count_tokens(model=model, contents=contents)
        self.fixtures["token_counts"]["tok:" + fixture_key(model, contents, False)] = (
            resp.total_tokens
        )
        return resp


class RecordingClient:
    """包住真實 client，一邊正常呼叫一邊把結果錄下來。"""

    def __init__(self, real_client):
        self.models = _RecordingModels(real_client.models)

    def dump(self) -> dict:
        return self.models.fixtures


def make_client(fixtures: dict | None = None):
    """建立 client。

    三種模式：
      OFFLINE_MODE    → ReplayClient，零網路，重播錄好的輸出（無網路時）
      RECORD_FIXTURES → RecordingClient，正常呼叫並錄下來（有網路時）
      預設             → 真實 client
    """
    if config.OFFLINE_MODE and config.RECORD_FIXTURES:
        raise RuntimeError("OFFLINE_MODE 與 RECORD_FIXTURES 不能同時為 True。")

    if config.OFFLINE_MODE:
        if not fixtures or not fixtures.get("calls"):
            raise RuntimeError(
                "OFFLINE_MODE=True 但沒有可用的 fixtures。\n"
                "請先在有網路的環境設定 RECORD_FIXTURES=True 跑一次，產生 "
                f"{config.FIXTURES_FILE}，再重新產生 notebook。"
            )
        return ReplayClient(fixtures)

    from google import genai

    if config.USE_VERTEX:
        real = genai.Client(
            vertexai=True,
            project=config.PROJECT_ID,
            location=config.LOCATION,
        )
    else:
        if not config.FALLBACK_API_KEY:
            raise RuntimeError(
                "USE_VERTEX=False 但 FALLBACK_API_KEY 是空的。"
                "請在 CONFIG cell 填入 AI Studio key，或改回 USE_VERTEX=True。"
            )
        real = genai.Client(api_key=config.FALLBACK_API_KEY)

    return RecordingClient(real) if config.RECORD_FIXTURES else real


def generate(
    client,
    prompt: str,
    *,
    structured: bool = False,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int = 3,
) -> GenResult:
    """單次生成。

    structured=True 時啟用 API 原生的 responseSchema —— 這是 v3 與 v2 的唯一差別。
    重點：不要用 prompt 硬凹 JSON 格式，要用 API 參數約束，模型才真的被限制在 schema 內。
    """
    from .prompts import COPY_SCHEMA

    model = model or config.GEN_MODEL
    temperature = config.GEN_TEMPERATURE if temperature is None else temperature

    cfg_kwargs = {"temperature": temperature}
    if structured:
        cfg_kwargs["response_mime_type"] = "application/json"
        cfg_kwargs["response_schema"] = COPY_SCHEMA

    last_err = None
    for attempt in range(max_retries):
        started = time.time()
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=gen_config(**cfg_kwargs),
            )
            meta = resp.usage_metadata
            return GenResult(
                text=resp.text or "",
                usage=Usage(
                    model=model,
                    input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
                    latency_s=round(time.time() - started, 2),
                ),
            )
        except Exception as e:  # noqa: BLE001 — demo 要能撐過暫時性錯誤
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2**attempt)  # 指數退避

    return GenResult(
        text="",
        usage=Usage(model=model, input_tokens=0, output_tokens=0, latency_s=0.0),
        error=str(last_err),
    )


def count_tokens(client, text: str, model: str | None = None) -> int:
    """實測中文的 token 數。

    不要背「中文一個字約幾個 token」這種經驗法則 —— 用這個函式直接量。
    量出來的數字比任何通用經驗法則可靠。
    """
    model = model or config.GEN_MODEL
    resp = client.models.count_tokens(model=model, contents=text)
    return resp.total_tokens
