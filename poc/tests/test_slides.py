"""投影片與播放器的產出檢查。

這裡守的不是「好不好看」—— 版面好不好看只有實際 render 出來看才知道，
那一步靠人（或瀏覽器截圖），不是靠測試。

這裡守的是**會讓演講當場出事的三件事**：

1. SVG 不是合法 XML → 瀏覽器直接不顯示那一頁
2. 內容超出 1280×720 的畫布 → 投影出來被切掉，台下看不到
3. slides.html 不是自足的（少了某一頁、或引用了外部資源）→ 沒網路就開天窗
"""

from __future__ import annotations

import pathlib
import re
import sys
import xml.dom.minidom

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from talk import build_slides as bs  # noqa: E402

DECK = bs.build_slides()


def _svg_of(name: str, svg_text: str | None) -> str:
    """產生的頁面直接用回傳值；手繪的頁面讀檔。"""
    if svg_text is not None:
        return svg_text
    return (bs.ASSETS / name).read_text(encoding="utf-8")


def test_every_slide_is_valid_xml():
    for name, _title, svg_text in DECK:
        try:
            xml.dom.minidom.parseString(_svg_of(name, svg_text))
        except Exception as e:  # noqa: BLE001
            raise AssertionError(f"{name} 不是合法 XML：{e}") from e


def test_every_slide_uses_the_same_canvas():
    """尺寸不一致的話，播放器縮放時會有一頁忽大忽小。"""
    for name, _title, svg_text in DECK:
        head = _svg_of(name, svg_text)[:400]
        assert 'viewBox="0 0 1280 720"' in head, f"{name} 的 viewBox 不是 1280×720"


def test_nothing_overflows_the_canvas():
    """座標超出畫布 = 投影出來被切掉。

    只檢查明確寫出來的座標（text 的 x/y、rect 的 x+width / y+height），
    這已經足以抓到「文字排到畫面外」這種最常見、也最致命的錯誤。
    """
    bad: list[str] = []
    for name, _title, svg_text in DECK:
        svg = _svg_of(name, svg_text)

        for m in re.finditer(r'<text[^>]*\sx="(-?[\d.]+)"[^>]*\sy="(-?[\d.]+)"', svg):
            x, y = float(m.group(1)), float(m.group(2))
            if not (0 <= x <= bs.W and 0 <= y <= bs.H):
                bad.append(f"{name} 有文字落在畫布外：({x}, {y})")

        for m in re.finditer(
            r'<rect[^>]*\sx="(-?[\d.]+)"[^>]*\sy="(-?[\d.]+)"[^>]*'
            r'\swidth="([\d.]+)"[^>]*\sheight="([\d.]+)"',
            svg,
        ):
            x, y, w, h = (float(g) for g in m.groups())
            if x + w > bs.W + 1 or y + h > bs.H + 1:
                bad.append(f"{name} 有方框超出畫布：右下角 ({x + w}, {y + h})")

    assert not bad, "\n".join(bad)


def test_generated_slides_are_marked_as_generated():
    """產生的檔案要標記清楚，才不會有人手改完被下次 build 蓋掉。"""
    for name, _title, svg_text in DECK:
        if svg_text is None:
            continue
        assert bs.GENERATED_MARK in svg_text, f"{name} 少了『由程式產生』的標記"


def test_player_is_self_contained_and_complete():
    """播放器必須是單一自足檔案：所有頁面都內嵌，且不引用任何外部資源。

    會場網路不能賭 —— 這跟 notebook 走離線重播是同一個理由。
    """
    html = bs.build_html([(n, t, _svg_of(n, s)) for n, t, s in DECK])

    assert html.count('<section class="slide"') == len(DECK), "有頁面沒有被放進播放器"
    for _name, title, _svg in DECK:
        assert title in html, f"總覽頁少了「{title}」"

    external = re.findall(r'(?:src|href)="(?!#)([^"]+)"', html)
    assert not external, f"播放器引用了外部資源，離線就會開天窗：{external}"


def test_player_scales_to_the_projector_not_a_fixed_size():
    """投影機解析度五花八門，寫死 width/height 會在別人的機器上出事。"""
    html = bs.build_html([(n, t, _svg_of(n, s)) for n, t, s in DECK])
    inline = html[html.index("<section"):]
    assert not re.search(r'<svg[^>]*\swidth="\d+"', inline), (
        "內嵌的 SVG 還留著固定 width，應該只留 viewBox"
    )
