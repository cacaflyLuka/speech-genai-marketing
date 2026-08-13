"""評測第一層：規則層。

不呼叫任何模型，毫秒級，零成本。重點：**先建這一層**。
多數團隊一上來就做 LLM judge，又貴又不穩；規則層能擋掉大部分明確錯誤，
而且結果是確定性的 —— 同樣的輸入永遠得到同樣的判定，可以進 CI。

這個模組刻意不 import 任何 GCP 套件，因此離線可測、可單元測試。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config


# --------------------------------------------------------------------------
# 把模型輸出正規化成統一結構
# --------------------------------------------------------------------------
@dataclass
class ParsedCopy:
    """從模型輸出解析出的文案結構。"""

    title: str = ""
    bullets: list[str] = field(default_factory=list)
    seo_description: str = ""
    hashtags: list[str] = field(default_factory=list)
    raw: str = ""
    is_structured: bool = False  # True = 直接來自合法 JSON，不需猜測


_TITLE_PAT = re.compile(
    r"^\s*(?:\**)\s*(?:商品)?標題\s*(?:\**)\s*[:：]\s*(?:\**)\s*(.+?)\s*(?:\**)\s*$",
    re.MULTILINE,
)
_BULLET_PAT = re.compile(r"^\s*(?:[-*•・‧]|\d+[.、)])\s*(.+?)\s*$", re.MULTILINE)
_SEO_PAT = re.compile(
    r"^\s*(?:\**)\s*(?:SEO\s*)?(?:描述|說明)\s*(?:\**)\s*[:：]\s*(?:\**)\s*(.+?)\s*(?:\**)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_HASHTAG_PAT = re.compile(r"#([^\s#,，、]+)")
_FENCE_PAT = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_structured(text: str) -> ParsedCopy | None:
    """嘗試把輸出當成 JSON 解析。成功才算 schema 合法。"""
    cleaned = _FENCE_PAT.sub("", text).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    required = {"title", "bullets", "seo_description", "hashtags"}
    if not required.issubset(data.keys()):
        return None
    if not isinstance(data["bullets"], list) or not isinstance(data["hashtags"], list):
        return None
    if not isinstance(data["title"], str) or not isinstance(data["seo_description"], str):
        return None

    return ParsedCopy(
        title=data["title"].strip(),
        bullets=[str(b).strip() for b in data["bullets"]],
        seo_description=data["seo_description"].strip(),
        hashtags=[str(h).lstrip("#").strip() for h in data["hashtags"]],
        raw=text,
        is_structured=True,
    )


def parse_freeform(text: str) -> ParsedCopy:
    """從自由文字裡「猜」出結構。

    ⚠️ 這個函式是脆弱的，而那正是重點。
    為了評測 v0～v2 的輸出，我們被迫寫這種靠正則猜測的 parser：
    模型換個排版它就壞掉。v3 用 responseSchema 之後這段就可以整個刪掉。
    這段脆弱的程式碼本身，就是「為什麼要 structured output」最好的論據。
    """
    title_match = _TITLE_PAT.search(text)
    if title_match:
        title = title_match.group(1)
    else:
        # 退而求其次：第一行非空、非 markdown 標記的文字
        title = ""
        for line in text.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped and not stripped.startswith("```"):
                title = stripped
                break

    bullets = [b for b in _BULLET_PAT.findall(text) if len(b) > 2]

    seo_match = _SEO_PAT.search(text)
    seo = seo_match.group(1) if seo_match else ""

    hashtags = _HASHTAG_PAT.findall(text)

    return ParsedCopy(
        title=title.strip(),
        bullets=[b.strip() for b in bullets],
        seo_description=seo.strip(),
        hashtags=hashtags,
        raw=text,
        is_structured=False,
    )


def parse_output(text: str) -> ParsedCopy:
    """先試結構化，失敗才退回猜測。"""
    return parse_structured(text) or parse_freeform(text)


# --------------------------------------------------------------------------
# 規則檢查
# --------------------------------------------------------------------------
@dataclass
class RuleResult:
    sku: str
    version: str
    schema_valid: bool
    title_length_ok: bool
    title_length: int
    bullet_length_ok: bool
    seo_length_ok: bool
    spec_coverage: float          # 0.0 - 1.0
    spec_missing: list[str]
    banned_clean: bool
    banned_hits: list[str]

    @property
    def all_pass(self) -> bool:
        return (
            self.schema_valid
            and self.title_length_ok
            and self.bullet_length_ok
            and self.seo_length_ok
            and self.spec_coverage == 1.0
            and self.banned_clean
        )


def _searchable_text(parsed: ParsedCopy) -> str:
    """組出用來搜尋禁詞與規格關鍵字的文字範圍。

    這裡有一個容易做錯、而且錯了會出事的決定：**掃描範圍要多大？**

    - 結構化輸出（v3）：掃 parsed 後的欄位就夠，範圍精確，不會把 JSON key
      名稱或模型的客套話算進去。
    - 自由文字（v0～v2）：**必須掃 raw 全文**。因為脆弱的 parser 常常只抓到
      第一行，真正的違規詞往往躲在後面幾段。只掃 parsed 欄位會讓違規漏網 ——
      而漏檢比誤判危險得多（誤判只是多花人力複查，漏檢是收罰單）。

    這條差異本身就是「為什麼要用 structured output」的另一個論據：
    有 schema 才能精確掃描，沒有 schema 就只能全文粗掃、誤判率上升。
    """
    if parsed.is_structured:
        return " ".join(
            [parsed.title, *parsed.bullets, parsed.seo_description, *parsed.hashtags]
        ).strip()
    return parsed.raw


def check_banned(text: str, banned_terms: list[str]) -> list[str]:
    """回傳所有命中的禁詞。

    用長詞優先比對，避免「治療」和「治療過敏」重複計數同一段文字。
    """
    hits: list[str] = []
    consumed: list[tuple[int, int]] = []
    for term in sorted(banned_terms, key=len, reverse=True):
        for m in re.finditer(re.escape(term), text):
            span = (m.start(), m.end())
            if any(span[0] >= s and span[1] <= e for s, e in consumed):
                continue  # 已被更長的禁詞涵蓋
            consumed.append(span)
            hits.append(term)
            break  # 同一個詞只記一次
    return hits


def evaluate_rules(
    output_text: str,
    product: dict,
    version: str,
    banned_terms: list[str],
) -> RuleResult:
    """對單一筆模型輸出跑完整規則層。"""
    parsed = parse_output(output_text)
    text = _searchable_text(parsed)

    missing = [kw for kw in product["must_include_keywords"] if kw not in text]
    coverage = 1.0 - len(missing) / max(len(product["must_include_keywords"]), 1)

    bullets_ok = bool(parsed.bullets) and all(
        len(b) <= config.BULLET_MAX for b in parsed.bullets
    )
    seo_ok = 0 < len(parsed.seo_description) <= config.SEO_DESC_MAX

    hits = check_banned(text, banned_terms)

    return RuleResult(
        sku=product["sku"],
        version=version,
        schema_valid=parsed.is_structured,
        title_length_ok=0 < len(parsed.title) <= config.SHOPEE_TITLE_MAX,
        title_length=len(parsed.title),
        bullet_length_ok=bullets_ok,
        seo_length_ok=seo_ok,
        spec_coverage=round(coverage, 3),
        spec_missing=missing,
        banned_clean=not hits,
        banned_hits=hits,
    )


def suggest_fix(hits: list[str], banned_data: dict) -> dict[str, str]:
    """對命中的禁詞給出合規替代寫法。

    重點：規則層不只是「擋」，還能「給修改方向」。
    這讓它從一個惹人厭的 linter 變成一個有用的工具。
    """
    mapping = banned_data.get("safe_alternatives", {}).get("mapping", {})
    return {h: mapping[h] for h in hits if h in mapping}
