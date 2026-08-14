"""投影片上的數字必須跟 eval_results.json 對得起來。

這條測試是被實際踩到才補的：`results.svg` 是手繪的，`eval_results.json` 是
跑出來的，兩者沒有任何機制綁在一起。有一次評測重跑之後結果檔沒更新，
投影片與資料檔就默默分岔了半天 —— 而這場演講的整個主張就是
「你怎麼知道它有沒有變好」，台上那張表跟資料對不起來是最糟的失分方式。

要重算結果檔：`uv run python poc/run_eval.py --replay --limit 50`
（重播錄好的 fixtures，零網路、零成本，數字跟錄製那一輪完全一致）。
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
RESULTS = json.loads(
    (ROOT / "poc" / "data" / "eval_results.json").read_text(encoding="utf-8")
)
SVG = (ROOT / "talk" / "assets" / "results.svg").read_text(encoding="utf-8")

# 投影片列名 → 結果檔裡的 (區塊, 欄位)
ROWS = {
    "法規禁詞 0 命中": ("規則層", "banned_clean"),
    "標題長度合規": ("規則層", "title_length_ok"),
    "規格完整覆蓋": ("規則層", "spec_full"),
    "可機器讀取": ("規則層", "schema_valid"),
    "rubric 通過率": ("評審層", "rubric通過率%"),
    "可直接上架": ("評審層", "可直接上架%"),
}

TEXT = re.compile(r'<text[^>]*\sx="([\d.]+)"[^>]*\sy="([\d.]+)"[^>]*>([^<]*)</text>')


def _table_from_svg() -> dict[str, list[float]]:
    """把 results.svg 讀成 {列名: [v0, v1, v2, v3]}。

    同一列的儲存格共用同一個 y，所以用 y 分組、再依 x 排序就是欄位順序。
    """
    by_y: dict[str, list[tuple[float, str]]] = {}
    for x, y, content in TEXT.findall(SVG):
        by_y.setdefault(y, []).append((float(x), content.strip()))

    table: dict[str, list[float]] = {}
    for cells in by_y.values():
        cells.sort()
        label = cells[0][1]
        if label not in ROWS:
            continue
        values = [c for _, c in cells[1:] if c.endswith("%")]
        table[label] = [float(v.rstrip("%")) for v in values]
    return table


def test_every_row_of_the_results_slide_is_in_the_data():
    table = _table_from_svg()
    missing = sorted(set(ROWS) - set(table))
    assert not missing, f"results.svg 裡找不到這幾列：{missing}"
    for label, values in table.items():
        assert len(values) == len(RESULTS["版本"]), (
            f"「{label}」有 {len(values)} 個數字，版本卻有 {len(RESULTS['版本'])} 個"
        )


def test_results_slide_numbers_match_eval_results():
    table = _table_from_svg()
    bad: list[str] = []
    for label, (section, field) in ROWS.items():
        for version, shown in zip(RESULTS["版本"], table[label], strict=True):
            actual = RESULTS[section][version][field]
            if abs(shown - actual) > 0.05:
                bad.append(f"{label} / {version}：投影片 {shown}，資料檔 {actual}")
    assert not bad, (
        "results.svg 跟 eval_results.json 對不起來：\n  " + "\n  ".join(bad)
        + "\n\n重算結果檔：uv run python poc/run_eval.py --replay --limit 50"
    )


def test_sample_size_on_the_slide_matches_the_data():
    n = RESULTS["商品數"]
    assert f"{n} 筆" in SVG, f"results.svg 沒寫出樣本數「{n} 筆」"
