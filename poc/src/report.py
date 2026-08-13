"""把評測結果整理成「版本 × 指標」對比表。

這張表是整份分析的結論。前面所有步驟都是為了讓它可信。

設計原則：
- 每一欄對應一個 prompt 改動所修好的問題，欄位順序＝改動順序，階梯感才會出來。
- 顯示通過率（%）而非平均分數，因為「12 個商品裡有幾個能直接上架」比
  「平均 3.8 分」更接近商業決策者要的答案。
"""

from __future__ import annotations

from .rules import RuleResult

METRIC_LABELS = {
    "schema_valid": "可機器讀取",
    "title_length_ok": "標題長度合規",
    "bullet_length_ok": "賣點長度合規",
    "seo_length_ok": "SEO描述合規",
    "spec_full": "規格完整覆蓋",
    "banned_clean": "法規禁詞 0 命中",
}

# 每個指標是被哪一版的改動修好的 —— 用於標註歸因
FIXED_BY = {
    "title_length_ok": "v1",
    "bullet_length_ok": "v1",
    "seo_length_ok": "v1",
    "spec_full": "v1",
    "banned_clean": "v2",
    "schema_valid": "v3",
}


def _metric_values(r: RuleResult) -> dict[str, bool]:
    return {
        "schema_valid": r.schema_valid,
        "title_length_ok": r.title_length_ok,
        "bullet_length_ok": r.bullet_length_ok,
        "seo_length_ok": r.seo_length_ok,
        "spec_full": r.spec_coverage == 1.0,
        "banned_clean": r.banned_clean,
    }


def build_table(results: list[RuleResult]) -> dict[str, dict[str, float]]:
    """results 為所有 (商品 × 版本) 的規則結果，回傳 {版本: {指標: 通過率}}。"""
    by_version: dict[str, list[RuleResult]] = {}
    for r in results:
        by_version.setdefault(r.version, []).append(r)

    table: dict[str, dict[str, float]] = {}
    for version in sorted(by_version):
        rows = by_version[version]
        agg = {m: 0 for m in METRIC_LABELS}
        for r in rows:
            for m, ok in _metric_values(r).items():
                agg[m] += int(ok)
        table[version] = {m: round(100 * c / len(rows), 1) for m, c in agg.items()}
        table[version]["_全數通過"] = round(
            100 * sum(r.all_pass for r in rows) / len(rows), 1
        )
    return table


def to_dataframe(results: list[RuleResult]):
    """回傳 pandas DataFrame，notebook 裡直接顯示用。"""
    import pandas as pd

    table = build_table(results)
    ordered = [
        "title_length_ok",
        "bullet_length_ok",
        "seo_length_ok",
        "spec_full",
        "banned_clean",
        "schema_valid",
    ]
    df = pd.DataFrame(
        {
            METRIC_LABELS[m] + f"\n(v{FIXED_BY[m][1:]}修好)": [
                table[v][m] for v in sorted(table)
            ]
            for m in ordered
        },
        index=sorted(table),
    )
    df["★ 全數通過"] = [table[v]["_全數通過"] for v in sorted(table)]
    df.index.name = "Prompt 版本"
    return df


def render_text_table(results: list[RuleResult]) -> str:
    """純文字版對比表 —— 不依賴 pandas，離線也能看。"""
    table = build_table(results)
    ordered = [
        "title_length_ok",
        "bullet_length_ok",
        "seo_length_ok",
        "spec_full",
        "banned_clean",
        "schema_valid",
    ]
    versions = sorted(table)

    def pad_to(text: str, width: int) -> str:
        """CJK 字元在等寬終端佔兩格，用顯示寬度而非字元數對齊。"""
        display = sum(2 if ord(c) > 127 else 1 for c in text)
        return text + " " * max(width - display, 1)

    width = 22 + 12 + 8 * len(versions)
    lines = [
        pad_to("指標", 22) + pad_to("修好的版本", 12) + "".join(f"{v:>8}" for v in versions),
        "─" * width,
    ]

    for m in ordered:
        lines.append(
            pad_to(METRIC_LABELS[m], 22)
            + pad_to(FIXED_BY[m], 12)
            + "".join(f"{table[v][m]:>7.0f}%" for v in versions)
        )

    lines.append("─" * width)
    lines.append(
        pad_to("★ 全數通過", 22)
        + pad_to("", 12)
        + "".join(f"{table[v]['_全數通過']:>7.0f}%" for v in versions)
    )
    return "\n".join(lines)


def noise_floor(n_items: int, n_checks_each: int = 1) -> float:
    """這張表上「多少百分點以內的差距應該當成雜訊」。

    用最粗的估計：一次檢查翻轉所造成的百分點變化。12 個商品 × 7 條 rubric
    = 84 次檢查，翻一條就是 1.2 個百分點；所以 2 個百分點以內的差距
    不該當成改善。

    為什麼要放這個函式：demo 的樣本數很小（12 個商品），
    很容易看到 92.9% vs 95.2% 就宣稱「v2 比較好」，但那其實只差一次檢查。
    **把雜訊當成訊號，是評測工作最容易犯、也最傷的錯。**
    """
    total = max(n_items * n_checks_each, 1)
    return round(100.0 / total, 1)


def significance_note(n_items: int, n_checks_each: int = 1) -> str:
    floor = noise_floor(n_items, n_checks_each)
    return (
        f"⚠ 樣本數 {n_items} 筆 × 每筆 {n_checks_each} 項 = {n_items * n_checks_each} 次檢查。\n"
        f"  單次檢查翻轉 ≈ {floor} 個百分點。\n"
        f"  **差距在 {floor * 2:.0f} 個百分點以內時，請當成雜訊，不要宣稱是改善。**\n"
        f"  要做出可靠的小幅比較，需要更大的評測集（實務上 200 筆以上）。"
    )


def combined_table(rule_results: list[RuleResult], rubric_summary: dict):
    """規則層 + rubric 層的合併對比表。

    每一版只負責修好一件事，這張表要能讓那件事一眼看出來。
    """
    import pandas as pd

    table = build_table(rule_results)
    versions = sorted(table)
    rows = {
        "標題長度合規 (v1)": [table[v]["title_length_ok"] for v in versions],
        "規格完整覆蓋 (v1)": [table[v]["spec_full"] for v in versions],
        "法規禁詞 0 命中 (v1)": [table[v]["banned_clean"] for v in versions],
        "rubric 通過率 (v2)": [
            rubric_summary.get(v, {}).get("rubric通過率%", float("nan")) for v in versions
        ],
        "可直接上架 (v2)": [
            rubric_summary.get(v, {}).get("可直接上架%", float("nan")) for v in versions
        ],
        "可機器讀取 (v3)": [table[v]["schema_valid"] for v in versions],
    }
    df = pd.DataFrame(rows, index=versions)
    df.index.name = "Prompt 版本"
    return df


def violation_detail(results: list[RuleResult], version: str, limit: int = 5) -> str:
    """列出某一版的違規細節 —— demo 中用來證明『這不是假資料』。"""
    rows = [r for r in results if r.version == version and not r.banned_clean]
    if not rows:
        return f"{version}：無禁詞違規 ✓"
    out = [f"{version} 的禁詞命中（前 {limit} 筆）："]
    for r in rows[:limit]:
        out.append(f"  {r.sku}  →  {'、'.join(r.banned_hits)}")
    if len(rows) > limit:
        out.append(f"  ...另有 {len(rows) - limit} 筆")
    return "\n".join(out)
