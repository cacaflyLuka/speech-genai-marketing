"""從一份宣告式的投影片清單，產生 SVG 投影片與可全螢幕播放的單一 HTML。

## 為什麼是產生的，不是一張一張手畫

跟 notebook 同一個道理：**版面規則只寫一次**。
邊界、字級、色票、右下角留給 logo 的安全區，全部集中在這個檔案上方的常數。
手畫二十幾張的下場是每張都差一點點 —— 而那種差異投影出來看得非常清楚。

`talk/assets/` 裡原本那六張是**手繪的示意圖**（工具地圖、金字塔、架構圖⋯⋯），
那種圖本來就該一張一張畫，所以保留原檔、不由這裡產生，只是被排進同一份播放清單。

## 產出

    talk/assets/*.svg     版面型投影片（本檔產生，檔頭會標記）
    talk/slides.html      單一檔案的播放器，SVG 全部內嵌

`slides.html` 是**自足的**：雙擊就能開，不需要伺服器、不需要網路。
這跟 notebook 的離線重播是同一個理由 —— 會場網路不能賭。

用法：

    python3 talk/build_slides.py          # 產生全部
    python3 talk/build_slides.py --list   # 只印出播放順序
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import pathlib
import re
import struct
import xml.sax.saxutils as sx

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
OUT_HTML = ROOT / "slides.html"

# 投影片上的禁詞與替代寫法直接讀 POC 的資料檔，不在這裡另外抄一份。
# 抄一份的下場是：資料改了、投影片沒改，然後台上講的跟 demo 跑出來的不一樣。
BANNED_TERMS_FILE = ROOT.parent / "poc" / "data" / "banned_terms.json"

# 手動放進來的介面截圖（不是產生的）。要換圖就換這個檔，標註座標寫在對應的
# layout_screenshot 呼叫裡，用的是截圖自己的像素座標。
SCREENSHOT_GEAP = ASSETS / "geap-overview.png"

# --------------------------------------------------------------------------
# 版面常數 —— 所有投影片共用，只改這裡
# --------------------------------------------------------------------------
W, H = 1280, 720
FONT = (
    "'PingFang TC','Noto Sans TC','Microsoft JhengHei','Hiragino Sans TC',sans-serif"
)
MONO = "'SF Mono','Menlo','Consolas','Noto Sans Mono CJK TC',monospace"

M = 76  # 左右邊界
TITLE_Y = 97  # 標題基線
SUB_Y = 136  # 副標基線
BODY_TOP = 196  # 內容起始
BOTTOM = 648  # 內容下界；再往下是主辦方 logo 的安全區

INK = "#1A1A1A"
INK_SOFT = "#4A4A4A"
MUTED = "#8A8A8A"
FAINT = "#B8B8B8"
HAIR = "#D8D8D8"
PAPER = "#F5F5F5"

BLUE, BLUE_DARK, BLUE_BG = "#1B6FB8", "#12507F", "#E9F2FB"
ORANGE, ORANGE_DARK, ORANGE_BG = "#EF7622", "#A85110", "#FDF1E6"
GREEN, GREEN_DARK, GREEN_BG = "#166534", "#0F4A25", "#CDEBD4"
RED = "#B3261E"

GENERATED_MARK = "由 talk/build_slides.py 產生，不要手改"


# --------------------------------------------------------------------------
# SVG 基本元件
# --------------------------------------------------------------------------
def esc(s: str) -> str:
    return sx.escape(str(s))


def embed_png(path: pathlib.Path) -> tuple[str, int, int]:
    """讀 PNG，回傳 (data URI, 寬, 高)。

    尺寸直接從 IHDR 標頭讀（第 16–24 個位元組），不引入影像函式庫 ——
    這支檔案要能在任何只裝了標準庫的環境跑起來。
    """
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} 不是 PNG")
    w, h = struct.unpack(">II", raw[16:24])
    return "data:image/png;base64," + base64.b64encode(raw).decode(), w, h


def text(x, y, s, *, size=20, color=INK, weight=None, anchor=None, font=None,
         opacity=None) -> str:
    attrs = [f'x="{x}"', f'y="{y}"', f'font-size="{size}"', f'fill="{color}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if font:
        attrs.append(f'font-family="{font}"')
    if opacity:
        attrs.append(f'opacity="{opacity}"')
    return f"<text {' '.join(attrs)}>{esc(s)}</text>"


def rect(x, y, w, h, *, fill="none", stroke=None, sw=2, r=10, dash=None) -> str:
    attrs = [f'x="{x}"', f'y="{y}"', f'width="{w}"', f'height="{h}"',
             f'rx="{r}"', f'fill="{fill}"']
    if stroke:
        attrs.append(f'stroke="{stroke}"')
        attrs.append(f'stroke-width="{sw}"')
        if dash:
            attrs.append(f'stroke-dasharray="{dash}"')
    return f"<rect {' '.join(attrs)}/>"


def line(x1, y1, x2, y2, *, color=HAIR, sw=2, dash=None) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{sw}"{d}/>')


def header(title: str, subtitle: str = "") -> list[str]:
    out = [text(M, TITLE_Y, title, size=38, weight=700, color=INK)]
    if subtitle:
        out.append(text(M, SUB_Y, subtitle, size=20, color=MUTED))
    return out


def svg_document(title: str, desc: str, body: list[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" font-family="{FONT}">\n'
        f"  <title>{esc(title)}</title>\n"
        f"  <desc>{esc(desc)}</desc>\n"
        f"  <!-- {GENERATED_MARK} -->\n"
        f'  <rect width="{W}" height="{H}" fill="#ffffff"/>\n  '
        + "\n  ".join(body)
        + "\n</svg>\n"
    )


# --------------------------------------------------------------------------
# 版型
# --------------------------------------------------------------------------
def layout_statement(*, big, kicker=None, foot=None, accent=BLUE, size=None):
    """一句話佔滿整頁。

    這種頁面的功能是**讓觀眾停下來看**，所以除了那句話什麼都不要放。
    字級依行數自動調整，行數多就縮小，不讓它撞到邊界。
    """
    lines = big if isinstance(big, list) else [big]
    size = size or (72 if len(lines) == 1 else 58 if len(lines) == 2 else 46)
    gap = size * 1.35
    block_h = gap * (len(lines) - 1)
    top = (H - block_h) / 2 + size * 0.32

    body = []
    if kicker:
        body.append(text(M, 150, kicker, size=22, color=accent, weight=700))
    for i, ln in enumerate(lines):
        body.append(text(M, top + i * gap, ln, size=size, weight=700, color=INK))
    if foot:
        body.append(line(M, BOTTOM - 54, W - M, BOTTOM - 54, color=HAIR, sw=1.5))
        body.append(text(M, BOTTOM - 18, foot, size=22, color=MUTED))
    return body


def layout_bullets(*, title, subtitle="", items, note=None, accent=BLUE):
    """編號條列。items 是 (標題, 說明) 或 (標題, 說明, 右欄) 的序列。"""
    body = header(title, subtitle)
    top = BODY_TOP + 16
    row_h = min(92, (BOTTOM - 60 - top) / max(len(items), 1))

    for i, item in enumerate(items):
        name, detail = item[0], item[1]
        aside = item[2] if len(item) > 2 else None
        y = top + i * row_h
        body += [
            f'<circle cx="{M + 18}" cy="{y + 6}" r="18" fill="{accent}"/>',
            text(M + 18, y + 13, str(i + 1), size=18, color="#ffffff",
                 weight=700, anchor="middle"),
            text(M + 56, y + 2, name, size=26, weight=700, color=INK),
            text(M + 56, y + 34, detail, size=19, color=INK_SOFT),
        ]
        if aside:
            body.append(text(W - M, y + 8, aside, size=20, color=accent,
                             weight=700, anchor="end"))
    if note:
        body += [
            line(M, BOTTOM - 44, W - M, BOTTOM - 44, color=HAIR, sw=1.5),
            text(M, BOTTOM - 10, note, size=21, color=MUTED),
        ]
    return body


def layout_compare(*, title, subtitle="", left, right, verdict=None):
    """左右對照。left / right 是 dict：label、tone、lines、tag。

    tone 決定色系；兩邊刻意用不同色，投影出來遠遠就能分辨在講哪一邊。
    """
    body = header(title, subtitle)
    col_w = (W - M * 2 - 40) / 2
    top = BODY_TOP

    # 兩欄等高（並排就該等高），但高度取決於較長那一欄的內容，不是一律撐到底
    def _needed(col):
        h = 88
        for ln in col["lines"]:
            h += 14 if ln == "" else 34
        return h + 18

    avail = (BOTTOM if not verdict else BOTTOM - 76) - top
    box_h = max(_needed(left), _needed(right))
    if box_h > avail:
        raise ValueError(
            f"「{title}」的對照欄放不下：需要 {box_h:.0f}px，只有 {avail:.0f}px。"
        )

    for idx, col in enumerate((left, right)):
        x = M + idx * (col_w + 40)
        fill, stroke, ink = {
            "blue": (BLUE_BG, BLUE, BLUE_DARK),
            "orange": (ORANGE_BG, ORANGE, ORANGE_DARK),
            "green": (GREEN_BG, GREEN, GREEN_DARK),
            "gray": ("#ffffff", FAINT, MUTED),
        }[col.get("tone", "gray")]

        body += [
            rect(x, top, col_w, box_h, fill=fill, stroke=stroke, sw=2.5),
            text(x + 28, top + 46, col["label"], size=26, weight=700, color=ink),
        ]
        if col.get("tag"):
            body.append(text(x + col_w - 28, top + 44, col["tag"], size=17,
                             color=ink, weight=700, anchor="end"))
        y = top + 88
        for ln in col["lines"]:
            if ln == "":
                y += 14
                continue
            mark, s = ("", ln)
            if ln[0] in "✓✗·":
                mark, s = ln[0], ln[1:].strip()
            if mark:
                body.append(text(x + 28, y, mark, size=20,
                                 color=GREEN if mark == "✓" else
                                 RED if mark == "✗" else MUTED, weight=700))
            body.append(text(x + (52 if mark else 28), y, s, size=20, color=INK_SOFT))
            y += 34

    if verdict:
        vy = top + box_h + 24
        body += [
            rect(M, vy, W - M * 2, 56, fill=ORANGE_BG, stroke=ORANGE, sw=2),
            text(W / 2, vy + 36, verdict, size=23, weight=700,
                 color=ORANGE_DARK, anchor="middle"),
        ]
    return body


def layout_table(*, title, subtitle="", columns, rows, note=None, emphasise=0):
    """表格。columns 是 (欄名, 寬度比例, 對齊)；emphasise 指定要放大的欄。"""
    body = header(title, subtitle)
    total = sum(c[1] for c in columns)
    avail = W - M * 2
    xs, acc = [], M
    for _, ratio, _ in columns:
        xs.append(acc)
        acc += avail * ratio / total

    top = BODY_TOP + 20
    for i, (name, _, align) in enumerate(columns):
        x = xs[i] + (avail * columns[i][1] / total - 10 if align == "end" else 0)
        body.append(text(x, top, name, size=19, color=MUTED, weight=700,
                         anchor="end" if align == "end" else None))
    body.append(line(M, top + 16, W - M, top + 16, color=INK, sw=2))

    row_h = min(78, (BOTTOM - 70 - top) / max(len(rows), 1))
    for r, row in enumerate(rows):
        y = top + 56 + r * row_h
        if r:
            body.insert(len(body), line(M, y - 32, W - M, y - 32, color=HAIR, sw=1))
        for i, cell in enumerate(row):
            align = columns[i][2]
            x = xs[i] + (avail * columns[i][1] / total - 10 if align == "end" else 0)
            big = i == emphasise
            body.append(text(x, y, cell, size=26 if big else 21,
                             weight=700 if big else None,
                             color=INK if big else INK_SOFT,
                             anchor="end" if align == "end" else None))
    if note:
        body.append(text(M, BOTTOM - 6, note, size=19, color=MUTED))
    return body


def layout_code(*, title, subtitle="", panels, note=None):
    """程式碼／prompt 對照。panels 是 dict：label、tone、lines、highlight。

    highlight 是要標色的行索引 —— 「這一版多加了什麼」全靠它。
    """
    body = header(title, subtitle)
    n = len(panels)
    gap = 32
    col_w = (W - M * 2 - gap * (n - 1)) / n
    top = BODY_TOP

    # 框高跟著內容走，不要一律撐到底。
    # 撐到底的話，短的那一頁會是一個大半是空白的框 —— 投影出來很像忘了放東西。
    rows = max(len(p["lines"]) for p in panels)
    avail = BOTTOM - top - (70 if note else 0)
    box_h = 44 + 34 + rows * 24 + 26
    if box_h > avail:
        raise ValueError(
            f"「{title}」的程式碼框放不下：需要 {box_h:.0f}px，只有 {avail:.0f}px。"
        )
    # 內容短的時候整塊往下挪一點，不要讓下半頁完全空著
    top += max(0, avail - box_h) * 0.34

    for idx, panel in enumerate(panels):
        x = M + idx * (col_w + gap)
        stroke, ink, hl = {
            "blue": (BLUE, BLUE_DARK, BLUE_BG),
            "orange": (ORANGE, ORANGE_DARK, ORANGE_BG),
            "green": (GREEN, GREEN_DARK, GREEN_BG),
            "gray": (HAIR, MUTED, PAPER),
        }[panel.get("tone", "gray")]

        body += [
            rect(x, top, col_w, box_h, fill="#ffffff", stroke=stroke, sw=2.5),
            rect(x, top, col_w, 44, fill=hl, stroke="none", r=10),
            text(x + 20, top + 30, panel["label"], size=20, weight=700, color=ink),
        ]
        y = top + 78
        for i, ln in enumerate(panel["lines"]):
            if i in panel.get("highlight", ()):
                body.append(rect(x + 12, y - 16, col_w - 24, 24, fill=hl,
                                 stroke="none", r=4))
            body.append(text(x + 20, y, ln, size=15, color=INK_SOFT, font=MONO))
            y += 24
    if note:
        body += [
            line(M, top + box_h + 34, W - M, top + box_h + 34, color=HAIR, sw=1.5),
            text(M, top + box_h + 70, note, size=21, color=MUTED),
        ]
    return body


def layout_cards(*, title, subtitle="", cards, note=None, columns=3):
    """卡片牆。cards 是 dict：label、lines、tone。"""
    body = header(title, subtitle)
    rows_n = (len(cards) + columns - 1) // columns
    gap = 28
    card_w = (W - M * 2 - gap * (columns - 1)) / columns
    top = BODY_TOP + 10

    # 卡片高度由**最長的那張**決定。
    # 這裡原本寫死 210，結果六行的那張最後一行掉到框外面 ——
    # 而且座標仍在畫布內，所以自動檢查抓不到，是投影出來才看得見的那種錯。
    avail = (BOTTOM - (40 if note else 0)) - top - gap * (rows_n - 1)
    needed = max(82 + len(c["lines"]) * 28 + 18 for c in cards)
    if needed * rows_n > avail:
        raise ValueError(
            f"「{title}」的卡片放不下：需要 {needed * rows_n:.0f}px，只有 {avail:.0f}px。"
            f"刪幾行，或改成兩列排版。"
        )
    card_h = needed

    for i, card in enumerate(cards):
        cx = M + (i % columns) * (card_w + gap)
        cy = top + (i // columns) * (card_h + gap)
        fill, stroke, ink = {
            "blue": (BLUE_BG, BLUE, BLUE_DARK),
            "orange": (ORANGE_BG, ORANGE, ORANGE_DARK),
            "green": (GREEN_BG, GREEN, GREEN_DARK),
            "gray": ("#ffffff", FAINT, MUTED),
        }[card.get("tone", "gray")]
        body += [
            rect(cx, cy, card_w, card_h, fill=fill, stroke=stroke, sw=2.5),
            text(cx + 22, cy + 44, card["label"], size=23, weight=700, color=ink),
        ]
        y = cy + 82
        for ln in card["lines"]:
            body.append(text(cx + 22, y, ln, size=18, color=INK_SOFT))
            y += 28
    if note:
        body.append(text(M, BOTTOM + 6, note, size=20, color=MUTED))
    return body


def layout_fix_pairs(*, title, subtitle="", pairs, note=None):
    """禁詞 → 替代寫法的對照列表。

    刻意用「一列一組」而不是左右兩欄各自條列：兩欄各列各的話，
    看的人要自己數第幾行對第幾行，而這頁的重點正是「哪個詞換成哪句話」。
    """
    body = header(title, subtitle)
    left_w = 300
    arrow_x = M + left_w + 16
    right_x = arrow_x + 46

    top = BODY_TOP + 26
    avail = BOTTOM - 40 - top
    row_h = min(46, avail / max(len(pairs), 1))
    if row_h < 30:
        raise ValueError(f"「{title}」要放 {len(pairs)} 列，一列只剩 {row_h:.0f}px，放不下")

    for i, (bad, good) in enumerate(pairs):
        y = top + i * row_h
        if i:
            body.append(line(M, y - row_h + 14, W - M, y - row_h + 14, color="#EDEDED",
                             sw=1))
        body += [
            text(M, y, "✗", size=20, color=RED, weight=700),
            text(M + 30, y, bad, size=22, color=INK_SOFT),
            text(arrow_x, y, "→", size=20, color=FAINT),
            text(right_x, y, "✓", size=20, color=GREEN, weight=700),
            text(right_x + 30, y, good, size=22, color=GREEN_DARK, weight=700),
        ]
    if note:
        body += [
            line(M, BOTTOM - 34, W - M, BOTTOM - 34, color=HAIR, sw=1.5),
            text(M, BOTTOM, note, size=21, color=MUTED),
        ]
    return body


def layout_screenshot(*, title, subtitle="", image, top=186, callouts=()):
    """整頁寬的介面截圖，加上圈選標註。

    截圖**用 base64 內嵌**，不是外部檔案連結 —— 播放器要能離線雙擊開啟，
    引用外部圖檔就等於賭會場網路（理由同 notebook 的離線重播）。

    callouts 的座標寫的是**截圖本身的像素座標**，不是投影片座標。
    這樣標註位置可以直接從截圖上量，換一張圖只要重量一次，
    不必回頭換算縮放比例 —— 縮放由這裡算。
    """
    data, iw, ih = embed_png(image)
    box_w = W - M * 2
    scale = box_w / iw
    box_h = ih * scale

    body = header(title, subtitle)
    body += [
        f'<image href="{data}" x="{M}" y="{top}" '
        f'width="{box_w}" height="{box_h:.1f}" preserveAspectRatio="none"/>',
        rect(M, top, box_w, round(box_h, 1), fill="none", stroke=FAINT, sw=1.5, r=6),
    ]

    legend_y = top + box_h + 46
    if callouts and legend_y + 30 > BOTTOM:
        raise ValueError(
            f"「{title}」的截圖太高，標註列放不下：圖到 {top + box_h:.0f}px，"
            f"標註要到 {legend_y + 30:.0f}px，下界是 {BOTTOM}px。"
        )

    col_w = box_w / max(len(callouts), 1)
    for i, (px, py, label, detail) in enumerate(callouts):
        n = str(i + 1)
        # 圖上的圈選：座標由截圖像素換算，圈本身不隨圖縮放變形
        cx, cy = M + px * scale, top + py * scale
        body += [
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="15" fill="{ORANGE}" '
            f'stroke="#ffffff" stroke-width="2.5"/>',
            text(cx, cy + 6, n, size=17, color="#ffffff", weight=700, anchor="middle"),
        ]
        # 下方的圖例：同一個編號，把圈選講清楚
        lx = M + i * col_w
        body += [
            f'<circle cx="{lx + 14}" cy="{legend_y - 7}" r="14" fill="{ORANGE}"/>',
            text(lx + 14, legend_y - 1, n, size=16, color="#ffffff",
                 weight=700, anchor="middle"),
            text(lx + 40, legend_y - 1, label, size=21, weight=700, color=INK),
            text(lx + 40, legend_y + 27, detail, size=17, color=MUTED),
        ]
    return body


# --------------------------------------------------------------------------
# 投影片內容
# --------------------------------------------------------------------------
# 每一項：(檔名, 標題, desc, body)。順序就是播放順序。
# 手繪的那六張以字串形式列出，只排順序、不重新產生。
AB_A = [
    "【嚴選】金賺健康 葉黃素軟膠囊 ★熱銷第一★",
    "",
    "守護您的靈魂之窗！現代人３Ｃ不離身，",
    "眼睛乾澀疲勞好困擾？本產品採用頂級游離型",
    "葉黃素，有效改善視力模糊、預防眼部疾病，",
    "讓您重拾清晰視界，告別老花困擾！",
]
AB_B = [
    "青研 游離型葉黃素軟膠囊 30粒 每粒30mg",
    "",
    "· 游離型葉黃素 30mg，吸收不需再轉換",
    "· 添加玉米黃素與蝦紅素，每日一粒",
    "· 全素可食，無添加人工色素",
    "· 適合長時間使用螢幕的日常保養",
]


def build_slides() -> list[tuple[str, str, str]]:
    """回傳 [(檔名, 頁面標題, svg 內容或 None)]。None 代表是既有的手繪檔。"""
    S: list[tuple[str, str, str | None]] = []

    def gen(name, title, desc, body):
        S.append((name, title, svg_document(title, desc, body)))

    def existing(name, title):
        S.append((name, title, None))

    # ---------------------------------------------------------------- 起
    body = header("", "")
    col_w = (W - M * 2 - 40) / 2
    body = [
        text(M, 88, "A", size=26, weight=700, color=MUTED),
        text(M + col_w + 40, 88, "B", size=26, weight=700, color=MUTED),
    ]
    for idx, lines in enumerate((AB_A, AB_B)):
        x = M + idx * (col_w + 40)
        body.append(rect(x, 110, col_w, 500, fill="#ffffff", stroke=HAIR, sw=2))
        y = 160
        for i, ln in enumerate(lines):
            if not ln:
                y += 16
                continue
            body.append(text(x + 26, y, ln, size=22 if i == 0 else 19,
                             weight=700 if i == 0 else None,
                             color=INK if i == 0 else INK_SOFT))
            y += 34
    gen("open-ab.svg", "開場：兩段商品文案",
        "同一個商品的兩段文案並排，不給任何提示，讓聽眾自己判斷哪一段能上線。", body)

    gen("question.svg", "把問題丟出來", "開場提問：你要怎麼跟工程師說這版比較好。",
        layout_statement(big=["那你要怎麼跟工程師說：", "這版比較好，上線吧？"]))

    gen("thesis.svg", "全場主張", "整場演講的唯一主張。",
        layout_statement(
            kicker="今天只講一件事",
            big=["生成式 AI 的難處", "不在叫模型，", "而在你怎麼知道", "它有沒有變好。"],
            size=52,
        ))

    gen("agenda.svg", "議程", "四段議程，一條因果鏈。",
        layout_bullets(
            title="今天的四段",
            subtitle="一條因果鏈，不是四個平行主題",
            items=[
                ("GEAP Studio", "探索：這件事到底做不做得成"),
                ("API 串接", "整合：能不能貼進現有系統"),
                ("Prompt 設計", "規格化：把要求寫成可檢查的條件"),
                ("評測流程", "驗收：怎麼證明它變好了"),
            ],
        ))

    # ---------------------------------------------------------------- 承
    existing("tool-map.svg", "GCP 三層工具地圖")

    gen("studio.svg", "探索期：GEAP 主控台",
        "GEAP 主控台實際截圖：左側四塊、改名說明、兩種驗證方式。",
        layout_screenshot(
            title="探索期：瀏覽器打開就能用",
            subtitle="GEAP（原 Vertex AI）主控台　不寫一行程式，先確認這件事做不做得成",
            image=SCREENSHOT_GEAP,
            callouts=[
                (115, 156, "Studio 就在左邊",
                 "貼上 prompt 就能比模型，不用先寫程式"),
                (1090, 190, "改名的官方說法",
                 "Vertex AI is now Agent Platform"),
                (790, 383, "兩種驗證、兩種用途",
                 "ADC 給系統，API key 只給本機試水溫"),
            ],
        ))

    gen("api-vs-geap.svg", "Gemini API vs GEAP",
        "兩種接法的差別：這是部署決策，不是程式碼決策。",
        layout_compare(
            title="Gemini API 還是 GEAP？",
            subtitle="GEAP＝Gemini Enterprise Agent Platform，2026 年 4 月由 Vertex AI 改名",
            left={
                "label": "Gemini API（AI Studio）", "tone": "blue", "tag": "做原型",
                "lines": [
                    "✓ 一把 API key 就能開始",
                    "✓ 免費額度，適合試水溫",
                    "✗ 計費歸個人帳號",
                    "✗ 沒有 VPC-SC、資料落地不可控",
                    "",
                    "適合：一個人、一週內、還在確認可行性",
                ],
            },
            right={
                "label": "GEAP", "tone": "orange", "tag": "要上線",
                "lines": [
                    "✓ 走 GCP 專案計費，成本歸屬清楚",
                    "✓ IAM、VPC-SC、資料落地可控",
                    "✓ 可簽 DPA、過得了法遵",
                    "✗ 要先設定專案與權限",
                    "",
                    "適合：要簽約、要稽核、要對董事會報告",
                ],
            },
            verdict="切換只差 Client 的建構參數，其他程式碼一行都不用改",
        ))

    gen("layer3.svg", "上線期：評測與監控",
        "第三層是多數團隊跳過的一層，也是今天的重點。",
        layout_cards(
            title="上線期：多數團隊跳過的那一層",
            subtitle="前兩層做完只代表「跑得動」，不代表「敢上線」",
            cards=[
                {"label": "1　探索", "tone": "gray",
                 "lines": ["GEAP Studio", "做不做得成？", "", "多數團隊：做了"]},
                {"label": "2　整合", "tone": "gray",
                 "lines": ["Gemini API / GEAP", "能不能貼進系統？", "",
                           "多數團隊：做了"]},
                {"label": "3　上線", "tone": "orange",
                 "lines": ["評測 + 監控", "有沒有變好？", "",
                           "多數團隊：跳過 ←"]},
            ],
            note="跳過第三層的專案，通常上線後才發現沒有人能判斷好壞",
        ))

    # ------------------------------------------------------------- 轉 1
    gen("prompt-v0.svg", "v0：什麼都不給",
        "最常見的第一版 prompt，以及它產生的文案。",
        layout_code(
            title="v0　什麼都不給",
            subtitle="大多數人第一次寫的 prompt",
            panels=[
                {"label": "prompt", "tone": "gray",
                 "lines": ["請幫這個商品寫一段", "電商文案。", "",
                           "商品：游離型葉黃素", "　　　30mg／30粒"]},
                {"label": "產出", "tone": "gray",
                 "lines": ["守護您的靈魂之窗！", "現代人３Ｃ不離身⋯⋯",
                           "有效改善視力模糊、", "預防眼部疾病，", "重拾清晰視界！"]},
            ],
            note="文筆很好。但它不能用 —— 長度不知道、規格沒寫、而且踩了法規。",
        ))

    gen("prompt-v1.svg", "v1：加通路約束",
        "v1 加入角色、受眾、字數與必含規格。",
        layout_code(
            title="v1　加通路約束",
            subtitle="把通路的格式要求寫進去：受眾、字數上限、必含規格",
            panels=[
                {"label": "v1 新增（藍色部分）", "tone": "blue",
                 "lines": [
                     "你是電商文案編輯。",
                     "受眾：30-50 歲上班族。",
                     "",
                     "標題 ≤ 60 字",
                     "賣點 4 條，每條 ≤ 30 字",
                     "SEO 描述 ≤ 120 字",
                     "",
                     "必須寫出：游離型、30mg、30粒",
                 ],
                 "highlight": (3, 4, 5, 7)},
                {"label": "修好了什麼", "tone": "gray",
                 "lines": [
                     "標題長度合規　74% → 100%",
                     "規格完整覆蓋　82% →  98%",
                     "法規禁詞 0 命中　80% → 98%",
                     "",
                     "語意品質（rubric）：",
                     "沒有統計上的改善。",
                     "",
                     "合理 —— v1 加的是字數與規格，",
                     "不是語氣指引。",
                 ]},
            ],
            note="字數與規格是能自動檢查的條件 —— 這一版的改善，規則層就量得到。",
        ))

    gen("prompt-v2.svg", "v2：加法規與語調",
        "v2 加入法規禁詞清單與品牌語調 few-shot。",
        layout_code(
            title="v2　加法規與語調",
            subtitle="這一版是唯一在語意品質上統計成立的改善",
            panels=[
                {"label": "法規段落", "tone": "orange",
                 "lines": [
                     "不得使用下列字詞：",
                     "  治療、預防、改善視力、",
                     "  療效、根治⋯⋯",
                     "",
                     "依食安法 §28：",
                     "宣稱醫療效能",
                     "罰 60 萬 – 500 萬",
                 ],
                 "highlight": (1, 2, 5, 6)},
                {"label": "品牌語調 few-shot", "tone": "blue",
                 "lines": [
                     "範例一",
                     "  緩釋B群錠 90錠 全素可食",
                     "  8種B群一次補齊，緩釋設計",
                     "",
                     "範例二",
                     "  甘胺酸鎂錠 120錠 睡前補充",
                     "  選用好吸收的螯合形式",
                     "",
                     "→ rubric 通過率 +8.9pp",
                 ],
                 "highlight": (8,)},
            ],
            note="rubric 量的正是語調與賣點覆蓋 —— 加什麼、量什麼，要對得上。",
        ))

    gen("prompt-v3.svg", "v3：結構化輸出",
        "v3 用 responseSchema 約束輸出格式，而不是在 prompt 裡拜託模型。",
        layout_code(
            title="v3　結構化輸出",
            subtitle="唯一的差別是多了 responseSchema",
            panels=[
                {"label": "不要這樣做", "tone": "gray",
                 "lines": [
                     "prompt 裡寫：",
                     '  "請以 JSON 格式輸出"',
                     "",
                     "模型會照做九成的時間。",
                     "剩下那一成，",
                     "你的 parser 就掛了。",
                 ],
                 "highlight": (1,)},
                {"label": "要這樣做", "tone": "green",
                 "lines": [
                     "response_schema = {",
                     '  "title":   str,  # ≤60',
                     '  "bullets": [str] * 4,',
                     '  "seo_desc": str, # ≤120',
                     "}",
                     "",
                     "模型被解碼器約束在 schema 內。",
                     "那一成的失敗會消失。",
                 ],
                 "highlight": (0, 1, 2, 3, 4)},
            ],
            note="可機器讀取：0% → 100%。這不需要統計檢定。",
        ))

    # 四頁 prompt 走完之後的統整。這一頁只講「加了什麼、為了解什麼」，
    # 不放通過率 —— 數字留給後面的結果頁，同一組數字在兩個地方寫，遲早會分岔。
    gen("prompt-recap.svg", "四個版本，四件事",
        "v0 → v3 的統整：每一版新增了什麼、各自在解什麼問題。",
        layout_table(
            title="四個版本，四件事",
            subtitle="回頭看一次 v0 → v3：差別不在文筆，在你把什麼要求寫成了條件",
            columns=[("版本", 0.12, "start"), ("prompt 多了什麼", 0.46, "start"),
                     ("這一版在解什麼問題", 0.42, "start")],
            rows=[
                ["v0", "一句話：幫這個商品寫文案", "沒有 —— 這是基準線"],
                ["v1", "角色、受眾、字數上限、必含規格", "產出對不上通路的格式要求"],
                ["v2", "法規禁詞清單、品牌語調 few-shot", "會踩罰則、語氣不像自家品牌"],
                ["v3", "responseSchema", "輸出是散文，接不進系統"],
            ],
            note="每一版只加一件事 —— 這是刻意的：只有一個改動，改善才歸得了因。",
        ))

    gen("only-v3.svg", "關鍵訊息：只有 v3 能接進系統",
        "前三版都只是聊天，只有結構化輸出能進系統。",
        layout_statement(
            big=["只有 v3 能接進系統。", "前面三版都只是聊天。"],
            foot="v3 沒有讓文案變好，是讓文案變得可用 —— 這是兩件事，你兩個都需要",
        ))

    # ------------------------------------------------------------- 轉 2
    existing("eval-pyramid.svg", "三層評測")

    gen("penalties.svg", "法規禁詞的罰則",
        "台灣廣告法規的罰則級距，說明為什麼規則層要放第一層。",
        layout_table(
            title="這不是工程潔癖，是不做會收罰單",
            subtitle="依台灣廣告法規整理，罰則差異很大",
            columns=[("罰則上限", 0.24, "start"), ("類別", 0.3, "start"),
                     ("法源", 0.28, "start"), ("實測 v0 踩雷率", 0.18, "end")],
            rows=[
                ["500 萬", "宣稱醫療效能", "食安法 §28 第 2 項", "20%"],
                ["400 萬", "不實、誇張、易生誤解", "食安法 §28 第 1 項", "—"],
                ["20 萬", "化粧品虛偽誇大", "化粧品衛管法 §10", "—"],
            ],
            note="加了 prompt 約束後降到 2% —— 但 2% 不是 0%，所以規則層要擋在最前面。",
        ))

    # 這一頁的內容全部來自 poc/data/banned_terms.json —— 包括覆蓋率那句話。
    # 原本是照著概念手寫的四組，跟資料檔對不上；在一場講「數字要從資料來」的
    # 演講裡，投影片自己硬寫是最不該犯的錯。
    banned = json.loads(BANNED_TERMS_FILE.read_text(encoding="utf-8"))
    mapping = banned["safe_alternatives"]["mapping"]

    gen("suggest-fix.svg", "規則層能給方向",
        "規則層不只擋，還能給出合規的替代寫法；內容直接來自禁詞清單。",
        layout_fix_pairs(
            title="規則層不只是擋，還能給方向",
            subtitle="這讓它從惹人厭的 linter 變成文案人員願意用的工具",
            pairs=list(mapping.items()),
        ))

    gen("binary-rubric.svg", "不要用 1–5 分",
        "Likert 分數與二元 rubric 的對照。",
        layout_compare(
            title="LLM as judge：不要用 1–5 分",
            subtitle="把一個模糊的大問題，拆成一組可檢查的 yes/no 小問題",
            left={
                "label": "1–5 分", "tone": "gray", "tag": "不要",
                "lines": ["「這份文案的品質有幾分？」", "", "→ 3.8 / 5", "",
                          "✗ 分數擠在 3–4 分", "✗ 今天 4 分明天 3 分",
                          "✗ 換評審模型整組平移", "✗ 寫得長就拿高分",
                          "✗ 「3.8 分」無法行動"],
            },
            right={
                "label": "二元 rubric", "tone": "green", "tag": "要",
                "lines": ["「文案是否寫出游離型 30mg？」", "", "→ 否", "",
                          "✓ 明確、可重現", "✓ 可累積成一張表",
                          "✓ 直接對應修改動作", "✓ 像單元測試",
                          "✓ 知道要補什麼"],
            },
            verdict="GEAP 的 Gen AI Evaluation 的 adaptive rubrics 就是這個思路",
        ))

    gen("rubric-list.svg", "真實的 rubric 清單",
        "從商品資料生成的驗收清單，v0～v3 共用同一份。",
        layout_bullets(
            title="每個商品一份驗收清單",
            subtitle="只看商品資料生成，不看被評的文案 —— v0～v3 共用同一份考卷",
            items=[
                ("文案是否寫出「游離型」？", "規格", "★ 未過就不該上架"),
                ("是否寫出含量 30mg？", "規格", "★ 未過就不該上架"),
                ("是否提及全素可食？", "規格", ""),
                ("語氣是否克制、無誇大？", "語調", ""),
                ("四條賣點是否各自獨立？", "結構", ""),
            ],
            note="若讓評審看著文案即興出題，等於每個版本考不同的考卷 —— 那張表就沒有意義了。",
        ))

    gen("judge-bias.svg", "judge 的偏誤",
        "LLM 評審的三種已知偏誤與各自的緩解方式。",
        layout_cards(
            title="評審不是中立的",
            subtitle="三種已知偏誤，各自有緩解方式 —— 但沒有一種能完全消除",
            cards=[
                {"label": "self-preference", "tone": "orange",
                 "lines": ["模型偏好自己", "生成的文字", "", "緩解：",
                           "生成用 flash", "評審用 2.5-pro"]},
                {"label": "verbosity", "tone": "orange",
                 "lines": ["寫得長、寫得華麗", "容易拿高分", "", "緩解：",
                           "二元判準", "不給分數"]},
                {"label": "position", "tone": "orange",
                 "lines": ["先看到的選項", "比較容易被選", "", "緩解：",
                           "不做兩兩對比", "各自獨立評分"]},
            ],
            note="所以評審層的數字要配信賴區間看 —— 有偏誤的量尺，更不能只看單點。",
        ))

    existing("results.svg", "50 筆評測結果")
    existing("significance.svg", "版本差距的信賴區間")

    gen("build-vs-buy.svg", "自己做還是買現成的",
        "用「會不會出現在你的產品定價頁上」當分界線。",
        layout_compare(
            title="自己做，還是買現成的？",
            subtitle="分界線只有一條",
            left={
                "label": "會出現在定價頁上 → 自己做", "tone": "blue",
                "lines": ["· 商品文案生成（電商平台）",
                          "· 病歷摘要（醫療系統）",
                          "· 契約風險標註（法律科技）", "",
                          "這是你的產品本身。",
                          "評測要自己建，因為只有你知道", "什麼叫做好。"],
            },
            right={
                "label": "不會出現在定價頁上 → 買現成", "tone": "gray",
                "lines": ["· 客服工單分類",
                          "· 會議記錄整理",
                          "· 內部文件搜尋", "",
                          "這是你的內部效率。",
                          "買現成的，把時間留給前面那欄。"],
            },
            verdict="這個 AI 功能會不會出現在你的產品定價頁上？",
        ))

    gen("two-directions.svg", "方法論可遷移",
        "生成與抽取是同一套流程的兩個方向。",
        layout_compare(
            title="同一套方法，兩個方向",
            subtitle="你剛學的是一套流程，不是一個文案技巧",
            left={
                "label": "場景 A　生成", "tone": "orange",
                "lines": ["結構化資料 → 非結構化文字", "",
                          "商品規格 → 商品文案", "",
                          "· 要 schema", "· 要評測", "· 要算成本"],
            },
            right={
                "label": "場景 B　抽取", "tone": "blue",
                "lines": ["非結構化文字 → 結構化資料", "",
                          "使用者評論 → 洞察欄位", "",
                          "· 要 schema", "· 要評測", "· 要算成本"],
            },
            verdict="方向相反，流程完全相同",
        ))

    # ---------------------------------------------------------------- 合
    existing("cost-model.svg", "成本估算公式與降本四招")

    gen("eval-costs-money.svg", "評測本身要花錢",
        "最常被漏算的一筆成本。",
        layout_statement(
            big=["評測本身要花錢。"],
            foot="大家算成本只算生成 —— 這次實測，評審佔總成本的大部分",
            accent=ORANGE,
        ))

    existing("gcp-architecture.svg", "GCP 架構：demo 用到的 vs 正式上線需要的")

    gen("ninety-days.svg", "90 天導入路徑",
        "三個階段各自的產出與時間。",
        layout_bullets(
            title="90 天導入路徑",
            subtitle="順序不能反過來 —— 先解決「怎麼知道它變好了」",
            items=[
                ("GEAP Studio 驗證可行性", "這件事到底做不做得成", "2 週"),
                ("建 golden set + API 串接", "30–50 筆就足以開始", "4 週"),
                ("小流量上線 + 監控", "有數字可以對董事會報告", "6 週"),
            ],
            note="golden set 不用大。50 筆 × 7 條判準，就足以分辨 3 個百分點以上的差距。",
        ))

    body = [
        text(M, 88, "A", size=26, weight=700, color=MUTED),
        text(M + col_w + 40, 88, "B", size=26, weight=700, color=GREEN_DARK),
    ]
    for idx, lines in enumerate((AB_A, AB_B)):
        x = M + idx * (col_w + 40)
        picked = idx == 1
        body.append(rect(x, 110, col_w, 300,
                         fill=GREEN_BG if picked else "#ffffff",
                         stroke=GREEN if picked else HAIR, sw=2.5 if picked else 2))
        y = 160
        for i, ln in enumerate(lines):
            if not ln:
                y += 16
                continue
            body.append(text(x + 26, y, ln, size=22 if i == 0 else 19,
                             weight=700 if i == 0 else None,
                             color=INK if i == 0 else INK_SOFT))
            y += 34
    body += [
        text(M + col_w + 40 + 26, 448, "✓ 規則層全過　rubric 通過　可機器讀取",
             size=20, color=GREEN_DARK, weight=700),
        line(M, 500, W - M, 500, color=HAIR, sw=1.5),
        text(M, 546, "你怎麼知道它有沒有變好？", size=30, weight=700, color=INK),
        text(M, 590, "現在你有一張表可以回答 —— 而且下次改 prompt，重跑一次就知道有沒有退步。",
             size=22, color=INK_SOFT),
    ]
    gen("closing.svg", "收尾：回到開場那兩段文案",
        "回到開場的 A/B 文案，這次有評測結果可以說明為什麼選 B。", body)

    return S


# --------------------------------------------------------------------------
# 播放器
# --------------------------------------------------------------------------
def _inline_svg(svg_text: str) -> str:
    """把 SVG 調整成可以直接內嵌進 HTML 的形式。

    拿掉固定的 width/height，只留 viewBox，讓它跟著容器縮放；
    投影機解析度五花八門，寫死尺寸只會在別人的機器上出事。
    """
    svg_text = re.sub(r"<\?xml[^>]*\?>\s*", "", svg_text)
    svg_text = re.sub(r'\s(width|height)="\d+"', "", svg_text, count=2)
    return svg_text.strip()


PLAYER_CSS = """
:root { --bg:#0d0d0d; --ui:#8A8A8A; }
* { box-sizing:border-box; }
html,body { margin:0; height:100%; background:var(--bg); overflow:hidden;
  font-family:'PingFang TC','Noto Sans TC','Microsoft JhengHei',sans-serif; }
#stage { position:fixed; inset:0; display:grid; place-items:center; }
.slide { display:none; width:100vw; height:100vh; }
.slide.on { display:grid; place-items:center; }
.slide svg { width:min(100vw, calc(100vh * 16 / 9));
  height:min(100vh, calc(100vw * 9 / 16)); display:block; }
#bar { position:fixed; left:0; bottom:0; height:3px; background:#EF7622;
  transition:width .18s ease; z-index:5; }
#hud { position:fixed; right:14px; bottom:12px; color:var(--ui); font-size:13px;
  letter-spacing:.04em; z-index:5; user-select:none; }
#hud b { color:#fff; font-weight:600; }
#help { position:fixed; left:14px; bottom:12px; color:var(--ui); font-size:12px;
  z-index:5; opacity:.55; }
#grid { position:fixed; inset:0; background:var(--bg); overflow:auto; padding:28px;
  display:none; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:18px;
  z-index:10; align-content:start; }
#grid.on { display:grid; }
#grid figure { margin:0; cursor:pointer; border:2px solid transparent; border-radius:8px;
  overflow:hidden; background:#fff; }
#grid figure:hover, #grid figure.cur { border-color:#EF7622; }
#grid svg { width:100%; height:auto; display:block; pointer-events:none; }
#grid figcaption { color:#c9c9c9; font-size:12px; padding:6px 8px; background:#161616; }
@media print {
  html,body { background:#fff; overflow:visible; }
  #bar,#hud,#help,#grid { display:none !important; }
  .slide { display:block !important; width:100%; height:auto;
    page-break-after:always; break-after:page; }
  .slide svg { width:100%; height:auto; }
}
"""

PLAYER_JS = """
const slides = [...document.querySelectorAll('.slide')];
const grid = document.getElementById('grid');
const bar = document.getElementById('bar');
const hud = document.getElementById('hud');
let i = 0;

function show(n) {
  i = Math.max(0, Math.min(slides.length - 1, n));
  slides.forEach((s, k) => s.classList.toggle('on', k === i));
  bar.style.width = ((i + 1) / slides.length * 100) + '%';
  hud.innerHTML = '<b>' + (i + 1) + '</b> / ' + slides.length;
  [...grid.children].forEach((f, k) => f.classList.toggle('cur', k === i));
  if (location.hash !== '#' + (i + 1)) history.replaceState(null, '', '#' + (i + 1));
}
function toggleGrid(force) {
  const on = force ?? !grid.classList.contains('on');
  grid.classList.toggle('on', on);
  if (on) [...grid.children][i]?.scrollIntoView({block: 'center'});
}
function fullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.();
}

addEventListener('keydown', e => {
  const k = e.key;
  if (k === 'ArrowRight' || k === 'PageDown' || k === ' ' || k === 'Enter') {
    show(i + 1); toggleGrid(false); e.preventDefault();
  } else if (k === 'ArrowLeft' || k === 'PageUp' || k === 'Backspace') {
    show(i - 1); toggleGrid(false); e.preventDefault();
  } else if (k === 'Home') { show(0); }
  else if (k === 'End') { show(slides.length - 1); }
  else if (k === 'f' || k === 'F') { fullscreen(); }
  else if (k === 'o' || k === 'O' || k === 'Escape') { toggleGrid(); }
});

// 點右半邊下一頁、左半邊上一頁 —— 沒有簡報筆的時候用得到
addEventListener('click', e => {
  if (grid.classList.contains('on')) return;
  show(e.clientX > innerWidth / 2 ? i + 1 : i - 1);
});
[...grid.children].forEach((f, k) => f.addEventListener('click', ev => {
  ev.stopPropagation(); show(k); toggleGrid(false);
}));

// 觸控滑動
let x0 = null;
addEventListener('touchstart', e => { x0 = e.changedTouches[0].clientX; }, {passive: true});
addEventListener('touchend', e => {
  if (x0 === null) return;
  const dx = e.changedTouches[0].clientX - x0;
  if (Math.abs(dx) > 48) show(dx < 0 ? i + 1 : i - 1);
  x0 = null;
}, {passive: true});

show(Math.max(0, (parseInt(location.hash.slice(1), 10) || 1) - 1));
"""


def build_html(slides: list[tuple[str, str, str]]) -> str:
    stage, thumbs = [], []
    for idx, (name, title, svg_text) in enumerate(slides):
        inline = _inline_svg(svg_text)
        stage.append(
            f'<section class="slide" data-name="{html.escape(name)}">{inline}</section>'
        )
        thumbs.append(
            f"<figure>{inline}"
            f"<figcaption>{idx + 1}. {html.escape(title)}</figcaption></figure>"
        )

    return (
        "<!doctype html>\n<html lang=\"zh-Hant\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>零售場景的生成式 AI — 投影片</title>\n"
        f"<style>{PLAYER_CSS}</style>\n</head>\n<body>\n"
        f'<div id="stage">{"".join(stage)}</div>\n'
        f'<div id="grid">{"".join(thumbs)}</div>\n'
        '<div id="bar"></div>\n<div id="hud"></div>\n'
        '<div id="help">← → 換頁　F 全螢幕　O 總覽</div>\n'
        f"<script>{PLAYER_JS}</script>\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="只印出播放順序，不寫檔")
    args = ap.parse_args(argv)

    spec = build_slides()
    written = 0
    deck: list[tuple[str, str, str]] = []

    for name, title, svg_text in spec:
        path = ASSETS / name
        if svg_text is None:  # 手繪的既有檔案，只排順序
            if not path.exists():
                raise SystemExit(f"找不到手繪投影片 {path}")
            svg_text = path.read_text(encoding="utf-8")
        elif not args.list:
            path.write_text(svg_text, encoding="utf-8")
            written += 1
        deck.append((name, title, svg_text))

    if args.list:
        for i, (name, title, _) in enumerate(deck, 1):
            print(f"  {i:>2}. {title:<28} {name}")
        return

    OUT_HTML.write_text(build_html(deck), encoding="utf-8")
    hand = sum(1 for _, _, s in spec if s is None)
    print(
        f"✓ {len(deck)} 張投影片（產生 {written} 張，手繪 {hand} 張）\n"
        f"✓ {OUT_HTML.relative_to(ROOT.parent)}"
        f"　{OUT_HTML.stat().st_size / 1024:.0f} KB —— 雙擊開啟，按 F 全螢幕"
    )


if __name__ == "__main__":
    main()
