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

# 「這個指標是被哪一版修好的」**必須從資料算出來，不可以硬寫。**
#
# 這裡原本是一份手寫的對照表（title→v1、banned→v2⋯⋯），寫的時候看起來
# 理所當然。後來實跑 50 筆與 200 筆，六條裡有三條被資料推翻：
#
#     賣點長度   標成 v1，實際是 v3 修好的（+62pp）
#     SEO描述    標成 v1，實際是 v3 修好的（+88pp）—— v1 完全沒動
#     法規禁詞   標成 v2，實際 v1 就做掉大部分（+20pp），v2 只是收尾
#
# 一個硬寫的因果宣稱，就擺在真實數字旁邊，而且是錯的 —— 在一份講
# 「怎麼知道它有沒有變好」的材料裡，這是最不該犯的錯。
#
# 所以改成：看哪一版帶來最大的單步改善，就歸因給那一版。
# 資料換了，標註自動跟著換。


def attribution(table: dict[str, dict[str, float]]) -> dict[str, str]:
    """依實測資料判斷每個指標是被哪一版修好的。

    作法很簡單：比較相鄰版本的差距，取單步改善最大的那一版。
    改善幅度太小（<5pp）就標成「—」，不硬掰因果。
    """
    versions = sorted(table)
    out: dict[str, str] = {}
    for metric in METRIC_LABELS:
        gains = [
            (table[versions[i]][metric] - table[versions[i - 1]][metric], versions[i])
            for i in range(1, len(versions))
        ]
        if not gains:
            out[metric] = "—"
            continue
        best_gain, best_version = max(gains)
        out[metric] = best_version if best_gain >= 5 else "—"
    return out


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
    attr = attribution(table)
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
            METRIC_LABELS[m] + f"\n({attr[m]}修好)": [
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
    attr = attribution(table)
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
        pad_to("指標", 22) + pad_to("實測歸因", 12) + "".join(f"{v:>8}" for v in versions),
        "─" * width,
    ]

    for m in ordered:
        lines.append(
            pad_to(METRIC_LABELS[m], 22)
            + pad_to(attr[m] + ("※" if m in PARSER_DEPENDENT else ""), 12)
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


# 這兩個指標**只在結構化輸出上可靠**。
#
# 自由文字要靠 parse_freeform() 猜出哪幾句是賣點、哪一段是 SEO 描述，
# 而那個 parser 是脆弱的。實測 12 筆時它剛好都猜中，換到 200 筆就大量失效 ——
# 於是 v0～v2 的「賣點長度合規」掉到個位數。
#
# 但那個數字測到的是 **parser 的成功率**，不是模型的合規率。
# 把它當成 0% 呈現會誤導成「模型寫超長」，實際上是我們根本量不到。
# 所以非結構化的版本一律標成「不可測」（NaN），不填 0。
#
# 這件事本身就是 structured output 最有力的論據：
# 沒有 schema，連「有沒有做對」都無法誠實測量。
PARSER_DEPENDENT = ("bullet_length_ok", "seo_length_ok")


def combined_table(rule_results: list[RuleResult], rubric_summary: dict):
    """規則層 + rubric 層的合併對比表。

    每一版只負責修好一件事，這張表要能讓那件事一眼看出來。
    依賴 parser 的指標在非結構化版本上以「—」呈現，不假裝量得到。
    """
    import pandas as pd

    table = build_table(rule_results)
    versions = sorted(table)
    attr = attribution(table)  # 歸因一律由資料算出，欄名不硬寫版本

    # 某一版是否為結構化輸出：用該版 schema_valid 是否過半判定，
    # 不寫死版本名，這樣改了版本命名也不會壞。
    structured = {v: table[v]["schema_valid"] >= 50 for v in versions}

    def parser_dependent(metric: str) -> list:
        return [table[v][metric] if structured[v] else float("nan") for v in versions]

    def rubric_col(key: str) -> list:
        return [rubric_summary.get(v, {}).get(key, float("nan")) for v in versions]

    def rubric_attr(key: str) -> str:
        """rubric 欄位的歸因同樣用實測算，不預設是哪一版。"""
        vals = [rubric_summary.get(v, {}).get(key) for v in versions]
        gains = [
            (vals[i] - vals[i - 1], versions[i])
            for i in range(1, len(versions))
            if vals[i] is not None and vals[i - 1] is not None
        ]
        if not gains:
            return "—"
        best, ver = max(gains)
        return ver if best >= 5 else "—"

    rows = {
        f"標題長度合規 ({attr['title_length_ok']})": [
            table[v]["title_length_ok"] for v in versions
        ],
        f"規格完整覆蓋 ({attr['spec_full']})": [table[v]["spec_full"] for v in versions],
        f"法規禁詞 0 命中 ({attr['banned_clean']})": [
            table[v]["banned_clean"] for v in versions
        ],
        "賣點長度 ※": parser_dependent("bullet_length_ok"),
        "SEO描述長度 ※": parser_dependent("seo_length_ok"),
        f"rubric 通過率 ({rubric_attr('rubric通過率%')})": rubric_col("rubric通過率%"),
        f"可直接上架 ({rubric_attr('可直接上架%')})": rubric_col("可直接上架%"),
        f"可機器讀取 ({attr['schema_valid']})": [table[v]["schema_valid"] for v in versions],
    }
    df = pd.DataFrame(rows, index=versions)
    df.index.name = "Prompt 版本"
    return df


PARSER_CAVEAT = """※ 這兩欄只在結構化輸出上可靠。

自由文字要靠正則猜出哪幾句是賣點、哪一段是 SEO 描述，而那個 parser 很脆弱。
非結構化的版本標成「—」，代表**量不到**，不是「不合格」。

這正是 structured output 的核心價值：沒有 schema，
連「有沒有做對」都無法誠實測量 —— 而測不到的東西就管不了。"""


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
