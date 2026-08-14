"""總覽儀表板：把前面算出來的數字畫成一頁 BI 報告。

## 為什麼要有這一頁

前面每一節都印出各自的表格，適合邊做邊解釋，但**看完之後沒有一個地方能一眼
看完整體**。決策者要的是後者：四個版本誰能上線、差距是不是真的、這件事要花多少錢。

這一頁不產生任何新數字。**所有數值都來自前面已經算過的物件**
（`rule_results`、`rubric_reports`、`ledger`、`insights`），只是換一種呈現。
若這裡出現和前面表格對不上的數字，那是 bug，不是「圖表的呈現差異」。

## 圖表設計上的幾個決定

- **v0→v3 用同一個藍色由淺到深**，不是四個不同顏色。版本是有序的，
  用四個類別色會讓人以為它們是四個平行選項。
- **不用雙 Y 軸。** 兩個單位不同的量就分成兩張圖。
- **信賴區間那張圖是重點**：長條圖只能顯示「差多少」，顯示不了「這個差距可不可信」。
- 顏色不獨自承載意義：顯著與否除了顏色，旁邊一定有文字結論；
  對比較低的橘色一律標上數值。
- 色票沿用投影片（藍 #1B6FB8、橘 #EF7622、綠 #166534），
  台上在投影片與 notebook 之間切換時不會有色感斷裂。

## 中文字型

matplotlib 預設字型沒有中文字，直接畫會變成一格一格的豆腐。
所以這裡會先找系統上可用的中文字型；**找不到就整頁改用英文標籤**，
而不是印出一堆豆腐。數值完全不受影響。

Colab 預設環境通常沒有中文字型 —— 這裡刻意不自動安裝：
安裝要連網，而這份 notebook 的前提是零網路也能跑完。
真的要中文標籤，在有網路時先執行 `!apt-get install -y fonts-noto-cjk` 再重啟 runtime。
"""

from __future__ import annotations

from . import config
from .report import build_table, paired_compare

# --------------------------------------------------------------------------
# 色票 —— 與投影片同一組
# --------------------------------------------------------------------------
INK = "#1A1A1A"  # 主要文字
INK_SOFT = "#4A4A4A"  # 次要文字
MUTED = "#8A8A8A"  # 軸線、刻度、註解
GRID = "#E3E3E3"  # 格線，要比資料更不明顯
SURFACE = "#FFFFFF"  # 圖表底色。明確指定，才不會跟著 Colab 主題變

BLUE = "#1B6FB8"
ORANGE = "#EF7622"
GOOD = "#166534"  # 「有差異」
UNSURE = "#8A8A8A"  # 「分不出差別」
ZERO_LINE = "#C2510A"

# v0→v3 的有序藍色階（淺→深）。最淺的一階仍要與白底有足夠對比，不能淡到看不見。
VERSION_STEPS = ("#8CB8E2", "#5192CC", "#1B6FB8", "#12507F")

CJK_FONTS = (
    "PingFang TC",
    "Heiti TC",
    "Noto Sans CJK TC",
    "Noto Sans CJK JP",
    "Noto Sans TC",
    "Source Han Sans TW",
    "Microsoft JhengHei",
    "Hiragino Sans",
    "WenQuanYi Zen Hei",
    "Taipei Sans TC Beta",
    "Arial Unicode MS",
)


def find_cjk_font() -> str | None:
    """回傳系統上第一個可用的中文字型名稱，沒有就回傳 None。"""
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in CJK_FONTS:
        if name in available:
            return name
    return None


def make_label(font: str | None):
    """回傳一個 label(中文, 英文) 函式：有中文字型就用中文，沒有就退回英文。"""

    def label(zh: str, en: str) -> str:
        return zh if font else en

    return label


def version_colors(n: int) -> list:
    """版本的有序色階。四版直接用驗證過的四階，其他數量就在兩端之間內插。"""
    if n == len(VERSION_STEPS):
        return list(VERSION_STEPS)

    from matplotlib.colors import LinearSegmentedColormap

    ramp = LinearSegmentedColormap.from_list("v", [VERSION_STEPS[0], VERSION_STEPS[-1]])
    return [ramp(i / max(n - 1, 1)) for i in range(n)]


def _style(ax, *, grid_axis: str | None = "y") -> None:
    """統一外觀：格線退到資料後面，只留必要的軸線。"""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=10.5, length=0)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=1, zorder=0)
        ax.set_axisbelow(True)
    else:
        ax.grid(False)


def _title(ax, text: str, note: str = "") -> None:
    ax.set_title(
        text, color=INK, fontsize=13.5, fontweight="bold", loc="left",
        pad=30 if note else 12,
    )
    if note:
        ax.text(0, 1.03, note, transform=ax.transAxes, color=MUTED, fontsize=10.5,
                va="bottom", ha="left")


# --------------------------------------------------------------------------
# 各面板
# --------------------------------------------------------------------------
def _tile(ax, value: str, caption: str, note: str = "", color: str = INK) -> None:
    """單一數字的看板。有些問題的答案就是一個數字，畫成長條圖只是稀釋它。"""
    ax.axis("off")
    ax.text(0, 0.70, value, color=color, fontsize=27, fontweight="bold", va="center")
    ax.text(0, 0.32, caption, color=INK_SOFT, fontsize=11.5, va="center")
    if note:
        ax.text(0, 0.10, note, color=MUTED, fontsize=9.5, va="center")


def _rule_metric_panel(ax, versions, values, title, colors) -> None:
    """單一規則層指標在各版本的通過率。四個指標並排成小倍數圖。"""
    bars = ax.bar(versions, values, color=colors, width=0.62, zorder=2)
    ax.bar_label(bars, fmt="%.0f%%", color=INK_SOFT, fontsize=10.5, padding=3)
    ax.set_ylim(0, 122)
    ax.set_yticks([])
    _style(ax, grid_axis=None)
    ax.set_title(title, color=INK, fontsize=12, fontweight="bold", loc="left", pad=8)


def _rubric_panel(ax, versions, pass_rates, publishable, label) -> None:
    """評審層兩個指標。兩個都是百分比、共用同一個軸，所以可以並排在同一張圖。"""
    x = list(range(len(versions)))
    w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], pass_rates, w, color=BLUE, zorder=2,
                label=label("rubric 通過率", "Rubric pass rate"))
    b2 = ax.bar([i + w / 2 for i in x], publishable, w, color=ORANGE, zorder=2,
                label=label("可直接上架", "Ready to publish"))

    # 橘色對白底的對比偏低 —— 一律標上數值，不讓顏色單獨承擔訊息
    for bars in (b1, b2):
        ax.bar_label(bars, fmt="%.0f%%", color=INK_SOFT, fontsize=10.5, padding=3)

    ax.set_xticks(x, versions)
    ax.set_ylim(0, 125)
    ax.set_yticks([])
    _style(ax, grid_axis=None)
    ax.legend(frameon=False, fontsize=11, labelcolor=INK_SOFT, ncols=2,
              loc="lower left", bbox_to_anchor=(0, 1.0))
    _title(ax, label("評審層：語意品質", "Judge layer: semantic quality"), note=" ")


def _significance_panel(ax, comparisons, label) -> None:
    """相鄰版本的差距與 95% 信賴區間。

    這一格是整頁最重要的：長條圖只能顯示「差多少」，顯示不了「這個差距可不可信」。
    區間跨過 0 就不能宣稱誰比較好 —— 所以 0 那條線一定要畫出來。
    """
    _title(
        ax,
        label("差距是真的還是雜訊？", "Real difference, or noise?"),
        label("配對比較 · bootstrap 95% 信賴區間 · 區間跨過 0 就不能宣稱",
              "paired comparison · bootstrap 95% CI · crossing 0 means no claim"),
    )

    if not comparisons:
        ax.set_xticks([])
        ax.set_yticks([])
        _style(ax, grid_axis=None)
        ax.spines["bottom"].set_visible(False)
        ax.text(0.5, 0.5, label("配對樣本不足", "not enough paired samples"),
                transform=ax.transAxes, ha="center", color=MUTED, fontsize=11)
        return

    ax.axvline(0, color=ZERO_LINE, linewidth=1.5, linestyle=(0, (4, 3)), zorder=1)

    for y, c in enumerate(comparisons):
        lo, hi = c["95%CI"]
        mean = c["平均差(pp)"]
        color = GOOD if c["顯著"] else UNSURE
        ax.errorbar(mean, y, xerr=[[mean - lo], [hi - mean]], fmt="o", markersize=9,
                    color=color, ecolor=color, elinewidth=2, capsize=6, capthick=2,
                    zorder=3)
        verdict = (label("有差異", "significant") if c["顯著"]
                   else label("分不出差別", "inconclusive"))
        # 結論一律靠右對齊成一欄，不跟著區間端點跑 —— 區間長度會變，欄位不會，
        # 貼著端點放會在區間短的時候壓到 y 軸標籤上
        ax.text(0.99, y, f"{mean:+.1f} pp　{verdict}", transform=ax.get_yaxis_transform(),
                va="center", ha="right", color=INK_SOFT, fontsize=11)

    los = [c["95%CI"][0] for c in comparisons]
    his = [c["95%CI"][1] for c in comparisons]
    span = (max(his) - min(los)) or 1.0
    # 右側留白是給上面那一欄結論用的，不是美觀而已
    ax.set_xlim(min(los) - span * 0.10, max(his) + span * 0.85)
    ax.set_yticks(range(len(comparisons)), [c["比較"] for c in comparisons])
    ax.set_ylim(-0.5, len(comparisons) - 0.35)
    ax.set_xlabel(label("rubric 通過率的差距（百分點）",
                        "difference in rubric pass rate (pp)"),
                  color=MUTED, fontsize=10.5)
    _style(ax, grid_axis="x")


def _cost_panel(ax, gen_cost, judge_cost, label) -> None:
    """成本組成。一個整體被拆成兩塊，用堆疊橫條 —— 不要用圓餅圖。"""
    total = gen_cost + judge_cost
    # matplotlib 會把一對 $ 之間的字當數學式渲染 —— 金額一定要跳脫，
    # 否則 "US$0.07　約 NT$2.2" 中間那段會變成義大利體的亂碼
    usd = f"US\\${total:.4f}"
    _title(
        ax,
        label("這次執行的成本組成", "Cost breakdown of this run"),
        label(f"合計 {usd}　約 NT\\${total * config.USD_TO_TWD:.2f}", f"total {usd}"),
    )
    ax.set_yticks([])
    ax.set_xticks([])
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.set_facecolor(SURFACE)

    if total <= 0:
        ax.text(0.5, 0.5, label("這次執行沒有用量資料", "no usage recorded"),
                transform=ax.transAxes, ha="center", color=MUTED, fontsize=11)
        return

    for left, width, color, zh, en in (
        (0, gen_cost, BLUE, "生成", "Generation"),
        (gen_cost, judge_cost, ORANGE, "評審", "Judging"),
    ):
        # 兩段之間留一條白縫，邊界才不會糊在一起
        ax.barh([0], [width], left=[left], height=0.42, color=color,
                edgecolor=SURFACE, linewidth=2, zorder=2, label=label(zh, en))
        ax.text(left + width / 2, 0, f"{width / total * 100:.0f}%", ha="center",
                va="center", color=SURFACE, fontsize=14, fontweight="bold")

    ax.set_ylim(-1.0, 0.6)
    ax.legend(frameon=False, fontsize=11, labelcolor=INK_SOFT, ncols=2,
              loc="upper left", bbox_to_anchor=(0, 0.28))


def _insight_panel(ax, insights, label) -> None:
    """場景 B：負評歸屬。

    `is_about_product` 把「商品不好」與「服務不好」分開 —— 混在一起統計，
    採購會以為商品有問題，實際上是物流慢。這一格就是在證明那個欄位有用。
    """
    ok = [r for r in insights if not r.error]
    rows = [
        (label("商品相關負評", "Product complaints"),
         label("採購／研發要看", "→ sourcing / R&D"),
         sum(1 for r in ok if r.is_about_product and r.sentiment == "negative")),
        (label("服務相關負評", "Service complaints"),
         label("物流／客服要看", "→ logistics / CS"),
         sum(1 for r in ok if not r.is_about_product and r.sentiment == "negative")),
    ]

    y = list(range(len(rows)))[::-1]  # 第一列畫在最上面
    bars = ax.barh(y, [n for *_, n in rows], color=BLUE, height=0.4, zorder=2)
    ax.bar_label(bars, fmt=" %d", color=INK_SOFT, fontsize=14, fontweight="bold",
                 padding=2)

    # 名稱與負責單位放進 y 軸標籤（兩行），不要自己疊 text —— 手動排版在
    # 這種只有兩列的圖上很容易撞在一起
    ax.set_yticks(y, [f"{name}\n{owner}" for name, owner, _ in rows])
    ax.tick_params(axis="y", labelsize=11.5)
    ax.set_xticks([])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.margins(x=0.22)
    _style(ax, grid_axis=None)
    ax.spines["bottom"].set_visible(False)
    for tick in ax.get_yticklabels():
        tick.set_color(INK_SOFT)
    _title(
        ax,
        label("場景 B：負評該給誰處理", "Scenario B: who owns the complaint"),
        label(f"共 {len(ok)} 則有效評論", f"{len(ok)} valid reviews"),
    )


# --------------------------------------------------------------------------
# 組裝
# --------------------------------------------------------------------------
def render_dashboard(rule_results, rubric_summary, rubric_reports, ledger, insights=None):
    """把前面所有結果組成一頁儀表板，回傳 matplotlib Figure。

    參數全部是前面各節已經算好的物件 —— 這裡不重算任何東西。
    """
    import matplotlib.pyplot as plt

    font = find_cjk_font()
    label = make_label(font)
    if font:
        plt.rcParams["font.sans-serif"] = [font, *plt.rcParams["font.sans-serif"]]
        # 多數中文字型（例如 Heiti TC）沒有獨立的粗體字面，matplotlib 會為
        # 每一段粗體文字印一行 findfont 警告。字型會自動退回一般字重，
        # 圖是好的，只有訊息很吵 —— 台上不需要看到那幾十行。
        import logging

        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    plt.rcParams["axes.unicode_minus"] = False  # 負號用 ASCII，避免又一種缺字

    table = build_table(rule_results)
    versions = sorted(table)
    colors = version_colors(len(versions))
    first, last = versions[0], versions[-1]
    n_products = len({r.sku for r in rule_results})

    comparisons = [
        c
        for a, b in zip(versions, versions[1:], strict=False)
        if (c := paired_compare(rubric_reports, a, b))
    ]

    gen_cost = ledger.total_cost_usd("gen")
    judge_cost = ledger.total_cost_usd("judge")
    total_cost = gen_cost + judge_cost
    judge_share = (judge_cost / total_cost * 100) if total_cost else 0.0

    publishable = {v: rubric_summary.get(v, {}).get("可直接上架%", 0.0) for v in versions}
    machine_readable = {v: table[v]["schema_valid"] for v in versions}
    n_real = sum(1 for c in comparisons if c["顯著"])

    fig = plt.figure(figsize=(15, 15), facecolor=SURFACE)
    gs = fig.add_gridspec(
        4, 4, hspace=0.75, wspace=0.32,
        left=0.055, right=0.975, top=0.885, bottom=0.055,
        height_ratios=[0.5, 0.72, 1.0, 0.62],
    )

    fig.suptitle(label("評測總覽", "Evaluation overview"), x=0.055, y=0.965,
                 ha="left", color=INK, fontsize=23, fontweight="bold")
    fig.text(
        0.055, 0.932,
        label(f"{n_products} 筆商品 × {len(versions)} 個 prompt 版本"
              f"　所有數字皆為本次執行實測",
              f"{n_products} products × {len(versions)} prompt versions"
              f" — every figure measured in this run"),
        color=MUTED, fontsize=12.5, ha="left",
    )

    # --- 第一列：四個看板數字 ---
    _tile(fig.add_subplot(gs[0, 0]),
          f"{publishable[first]:.0f}% → {publishable[last]:.0f}%",
          label("可直接上架", "Ready to publish"), f"{first} → {last}", color=BLUE)
    _tile(fig.add_subplot(gs[0, 1]),
          f"{machine_readable[first]:.0f}% → {machine_readable[last]:.0f}%",
          label("可機器讀取", "Machine readable"),
          label("結構化輸出，不需統計檢定", "structured output — no test needed"),
          color=BLUE)
    _tile(fig.add_subplot(gs[0, 2]), f"{n_real} / {len(comparisons)}",
          label("統計上成立的版本差距", "Statistically real version gaps"),
          label("其餘落在雜訊內", "the rest sit inside the noise"),
          color=GOOD if n_real else MUTED)
    _tile(fig.add_subplot(gs[0, 3]), f"{judge_share:.0f}%",
          label("評審佔總成本", "Judging share of cost"),
          label("最常被漏算的一筆", "the line item most often forgotten"),
          color=ORANGE)

    # --- 第二列：規則層四個指標的小倍數圖 ---
    rule_metrics = (
        ("title_length_ok", "標題長度合規", "Title length"),
        ("spec_full", "規格完整覆蓋", "Spec coverage"),
        ("banned_clean", "法規禁詞 0 命中", "No banned terms"),
        ("schema_valid", "可機器讀取", "Machine readable"),
    )
    section_axes = []
    for i, (key, zh, en) in enumerate(rule_metrics):
        ax = fig.add_subplot(gs[1, i])
        section_axes.append(ax)
        _rule_metric_panel(ax, versions, [table[v][key] for v in versions],
                           label(zh, en), colors)

    # 小倍數圖的群組標題。位置從實際的 axes 算出來，不寫死座標。
    top = max(ax.get_position().y1 for ax in section_axes)
    fig.text(0.055, top + 0.038,
             label("規則層：免費、確定性、可以進 CI",
                   "Rule layer — free, deterministic, CI-ready"),
             color=INK, fontsize=13.5, fontweight="bold", ha="left")

    # --- 第三列：評審層 vs 顯著性 ---
    _rubric_panel(fig.add_subplot(gs[2, :2]), versions,
                  [rubric_summary.get(v, {}).get("rubric通過率%", 0.0) for v in versions],
                  [publishable[v] for v in versions], label)
    _significance_panel(fig.add_subplot(gs[2, 2:]), comparisons, label)

    # --- 第四列：成本 +（有跑場景 B 的話）評論洞察 ---
    # 沒跑場景 B（§4 是超時第一個被砍的一節）時，成本圖就佔滿整列
    if insights:
        _cost_panel(fig.add_subplot(gs[3, :2]), gen_cost, judge_cost, label)
        _insight_panel(fig.add_subplot(gs[3, 2:]), insights, label)
    else:
        _cost_panel(fig.add_subplot(gs[3, :]), gen_cost, judge_cost, label)

    if not font:
        print(
            "! 沒有找到中文字型，圖表標籤改用英文（數值不受影響）。\n"
            "  要中文標籤：在有網路時執行 !apt-get install -y fonts-noto-cjk 再重啟 runtime。"
        )

    return fig
