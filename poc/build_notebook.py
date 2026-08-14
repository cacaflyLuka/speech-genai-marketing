"""從 src/ 模組與 data/ 資料組出自足的 Colab notebook。

為什麼要用產生的、而不是手寫 notebook：
- **單一真實來源**。程式碼只存在於 src/，有測試覆蓋。notebook 是產物。
  手寫 notebook 一定會跟測過的程式碼分岔，而分岔會在台上才被發現。
- **自足**。所有程式碼與資料都內嵌在 cell 裡，Colab 開了就能跑，
  不需要 clone repo、不需要掛 Drive、不需要 repo 是公開的。
- **看得見**。聽眾要看到 prompt 與規則的實際內容，不是 `from mylib import magic`。

用法：python3 poc/build_notebook.py
產出：poc/retail_genai_poc.ipynb（聽眾版）、poc/retail_genai_poc_speaker.ipynb（講者版）

## 參數化

**識別資訊不寫死在 repo 裡，在建構 notebook 的時候才注入。**

GCP 專案、BigQuery 位置、講者姓名、場次名稱這幾個值都是「換一個人用就要換」的，
留在原始碼裡別人 clone 下來就得四處找著改。所以：

    python3 poc/build_notebook.py --project-id my-gcp-project --speaker "你的名字"

`--project-id` 這類設定值會直接改寫進 notebook 內嵌的 CONFIG 那一格（成為字面值，
Colab 打開就是對的）；`--speaker` 這類展示資訊則寫進標題那一格。
每個參數都可以用環境變數代替（見 `--help`），沒給就沿用 `src/config.py` 的預設。

`src/config.py` 本身也讀同一組環境變數，所以 `run_eval.py`、`check_env.py`
這些不經過 notebook 的路徑會拿到同樣的值。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
DATA = ROOT / "data"

sys.path.insert(0, str(ROOT.parent))
from poc.src import config  # noqa: E402

# 兩種產出，同一份來源
#   audience  給聽眾帶回去的教材。乾淨、自足、沒有舞台指示。
#   speaker   給講者用的。內容完全相同，額外插入時間點、要說的話、風險提示。
OUTPUTS = {
    "audience": ROOT / "retail_genai_poc.ipynb",
    "speaker": ROOT / "retail_genai_poc_speaker.ipynb",
}

_MODE = "audience"  # 由 main() 設定


# ---------------------------------------------------------------- 參數化
#
# CONFIG_PARAMS  會被改寫進 notebook 內嵌的 CONFIG 那一格（config.py 裡的同名常數）
# BYLINE_PARAMS  只影響標題那一格的署名，不進程式碼
#
# 預設值直接取 config.py 的現值 —— 而 config.py 讀的是同一組環境變數，
# 所以「設環境變數」與「下參數」兩條路殊途同歸，不會有兩份預設值互相矛盾。
CONFIG_PARAMS = {
    "project_id": ("PROJECT_ID", "GCP 專案 ID"),
    "location": ("LOCATION", "Gemini 的 location（實測必須是 global）"),
    "bq_dataset": ("BQ_DATASET", "BigQuery dataset 名稱"),
    "bq_table": ("BQ_TABLE", "BigQuery table 名稱"),
    "bq_location": ("BQ_LOCATION", "BigQuery 的 region"),
}

# (環境變數, 標題上的標籤, --help 的說明)
BYLINE_PARAMS = {
    "speaker": ("SPEAKER_NAME", "講者", "講者姓名"),
    "event": ("EVENT_NAME", "場次", "場次或主辦單位"),
    "date": ("TALK_DATE", "日期", "日期"),
}

PROFILE: dict[str, str] = {
    **{key: getattr(config, const) for key, (const, _) in CONFIG_PARAMS.items()},
    **{key: os.environ.get(env, "") for key, (env, *_) in BYLINE_PARAMS.items()},
}


def _inject_config_values(text: str) -> str:
    """把 PROFILE 的值改寫成 config 原始碼裡的字面值。

    為什麼要改寫而不是讓 notebook 自己讀環境變數：notebook 會被上傳到 Colab
    單獨執行，那裡沒有你的 shell 環境。建構時就把值定下來，Colab 打開就是對的。

    改寫失敗（找不到該常數）一律報錯 —— 常數被改名而這裡沒跟上時，
    靜默不套用會讓人以為參數有生效，直到台上才發現連到別的專案。
    """
    for key, (const, _) in CONFIG_PARAMS.items():
        # 用 lambda 回傳固定字串，避免值裡的反斜線被當成 re 的替換語法
        new_line = f"{const} = {json.dumps(PROFILE[key], ensure_ascii=False)}"
        text, n = re.subn(
            rf"^{const} = .*$",
            lambda _m, line=new_line: line,
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise RuntimeError(
                f"config.py 裡找不到可改寫的 `{const} = ...`（--{key.replace('_', '-')} 無法生效）"
            )

    # 值都變成字面值之後 os 就沒人用了，順手拿掉，別讓聽眾看到無用的 import
    if not re.search(r"\bos\.", text):
        text = re.sub(r"^import os\n\n?", "", text, count=1, flags=re.MULTILINE)

    return text


def byline() -> str:
    """署名行。三個值都沒給就不產生這一行 —— 空白的『講者：』比沒有更難看。"""
    parts = [
        (label, PROFILE[key])
        for key, (_, label, _help) in BYLINE_PARAMS.items()
        if PROFILE[key].strip()
    ]
    return "　".join(f"**{label}**：{value}" for label, value in parts)


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip().splitlines(True)}


def cue(text: str) -> list[dict]:
    """講者提示 —— 只出現在 speaker 版。

    這些是舞台指示（幾分幾秒、要說什麼、哪裡會翻車），對聽眾沒有意義，
    放進帶回家的教材裡只會讓人困惑。所以兩版分開。
    """
    if _MODE != "speaker":
        return []
    body = "\n".join(f"> {line}" if line.strip() else ">" for line in text.strip().splitlines())
    return [md(f"<div style=\"border-left:6px solid #EF7622;padding-left:12px\">\n\n"
               f"**🎤 講者提示**\n\n{body}\n\n</div>")]


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.strip().splitlines(True),
    }


def module_source(name: str, *, strip_relative_imports: bool = True) -> str:
    """讀出模組原始碼，移除 notebook 裡不適用的部分。

    notebook 是單一命名空間，所以要拿掉 `from . import x` 這類相對匯入，
    以及 `if __name__ == "__main__"` 區塊。其餘一字不改 —— 聽眾看到的
    就是被測試覆蓋的那份程式碼。
    """
    text = (SRC / f"{name}.py").read_text(encoding="utf-8")

    # 拿掉 __main__ 區塊
    text = re.split(r'\nif __name__ == ["\']__main__["\']:', text)[0]

    if strip_relative_imports:
        # 相對匯入可能出現在模組頂層，也可能縮排在函式內（延遲匯入）。
        # 兩種都要處理 —— 只比對行首會漏掉縮排的那些，而那種錯誤只有
        # 執行時才會炸。test_notebook_offline.py 就是為了守住這件事。
        text = re.sub(
            r"^[ \t]*from \.[\w.]*\s+import\s+.*$\n?", "", text, flags=re.MULTILINE
        )
        # config.X → 直接用全域名稱（notebook 是扁平命名空間）
        text = re.sub(r"\bconfig\.([A-Z_]+)", r"\1", text)

    leftover = re.findall(r"^[ \t]*from \.", text, flags=re.MULTILINE)
    if leftover:
        raise RuntimeError(f"{name}.py 仍有未處理的相對匯入：{leftover}")
    if re.search(r"\bconfig\.", text):
        raise RuntimeError(f"{name}.py 仍有未改寫的 config. 參照")

    return text.rstrip() + "\n"


# notebook 與 run_eval.py 共用同一份資料的前 N 筆。
#
# 原本 notebook 用手寫的 12 筆、評測用另外 200 筆，結果台上要解釋
# 「這張表是 12 筆、但結論來自 50 筆」—— 多一層說明就多一分不被信任。
# 統一之後，台上那張表就是結論本身。
#
# 50 筆的理由：350 次 rubric 檢查、雜訊底線 0.29 個百分點，
# 足以分辨 3 個百分點以上的差距；再往上加樣本，換到的判斷力有限。
DEMO_N = 50


def build() -> list[dict]:
    products = json.loads((DATA / "eval_products.json").read_text(encoding="utf-8"))
    products["products"] = products["products"][:DEMO_N]
    banned = json.loads((DATA / "banned_terms.json").read_text(encoding="utf-8"))
    reviews = json.loads((DATA / "reviews.json").read_text(encoding="utf-8"))

    cells: list[dict] = []

    # ---------------------------------------------------------------- §0
    cells.append(md(f"""
# 零售場景的生成式 AI：從 Prompt 到可上線的評測流程

**Google Cloud & Generative AI Applications**

{byline()}

---

這份 notebook 要證明一件事：

> **生成式 AI 的難處不在叫模型，而在你怎麼知道它有沒有變好。**

我們會用一個真實的零售任務（商品文案生成）走完整條路：

| 節 | 內容 | 重點 |
|---|---|---|
| §1 | 商品資料與法規禁詞 | 規則要跟著商品屬性走 |
| §2 | Prompt v0 → v3，每版只加一件事 | Prompt 是規格書，不是咒語 |
| §3 | 三層評測，產出版本 × 指標對比表 | 怎麼證明它變好了 |
| §4 | 場景 B：評論洞察 | 同一套流程，反方向用 |
| §5 | 成本：實際花了多少，外推到 10 萬 SKU | 教公式，不背數字 |

**§3 的對比表是整份 notebook 的重點。** 其他都是為了讓那張表可信。

---

### 執行前須知

- 需要一個啟用了 Vertex AI API 與計費的 GCP 專案。
- 全部跑完的成本很低（見 §5 實際印出的數字），但**不是零**。
- 若沒有 GCP 專案，可在 §0 的 CONFIG 把 `USE_VERTEX` 改成 `False`
  並填入 AI Studio API key。
"""))
    cells.extend(cue("""
**Demo 全長 12 分鐘（30:00–42:00）。開場前先 Run all 一次，讓輸出都在畫面上。**

先確認 CONFIG 的 `OFFLINE_MODE = True` —— 這是最容易忘的一項。

開場第一句（不要道歉，一句帶過）：
「我先說明，這些輸出是我昨天跑好存下來的，現在是重播 —— 因為會場網路我不敢賭。
程式碼跟評測都是當場執行的，只有呼叫模型那一步是查表。」
"""))

    cells.append(md("""
## §0 環境設定

### 相依套件

這一格**只在缺少套件時才安裝**，不是無條件 `pip install`。

| 環境 | 行為 |
|---|---|
| Colab | 預裝了 pandas / jinja2 / matplotlib，會補裝 `google-genai` |
| 本機 uv 環境 | 全部已在 `.venv`，直接跳過 |

會做這個判斷是因為：在 uv 管理的環境裡無條件 `pip install`，套件會裝進
`.venv` 卻不在 `uv.lock` 裡，環境就跟鎖定檔對不上了。與其寫註解叫人自己
判斷該不該跑，不如讓它自己偵測。
"""))
    cells.append(code("""
import sys

# 渲染用，任何模式都需要。§3 的對比表用 df.style.background_gradient() 上色：
# .style 需要 jinja2、background_gradient 需要 matplotlib，缺一就會 AttributeError。
CORE = {"pandas": "pandas", "jinja2": "jinja2", "matplotlib": "matplotlib"}

# 只有要「真的呼叫 API」才需要。離線重播完全用不到它 ——
# 這是刻意設計的：要裝它就得有網路，一旦需要網路，零網路重播的前提就破功了。
LIVE = {"google.genai": "google-genai"}


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


_missing = [pkg for mod, pkg in {**CORE, **LIVE}.items() if not _importable(mod)]

if _missing:
    print("缺少套件，嘗試安裝：", " ".join(_missing))
    import subprocess
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", *_missing], check=True
        )
        print("✓ 安裝完成（若 import 仍失敗，重啟 runtime 再跑一次）")
    except Exception as e:
        # 安裝失敗不一定是問題：離線重播根本不需要 google-genai。
        print(f"⚠ 安裝失敗：{e}")
        if not _importable("google.genai"):
            print("  google-genai 未安裝 —— 離線重播（OFFLINE_MODE=True）不需要它，可以繼續。")
            print("  但若要真的呼叫 API，就必須在有網路的環境先裝好。")
        _still = [p for m, p in CORE.items() if not _importable(m)]
        if _still:
            print(f"  ✗ 仍缺渲染必要套件 {_still} —— §3 的對比表會無法上色。")
else:
    print("✓ 相依套件齊全，跳過安裝")

# BigQuery 只有 §4 要用；[pandas] extra 才會帶入 to_dataframe() 需要的 pyarrow
if not _importable("google.cloud.bigquery"):
    print('  （§4 若要實際寫入 BigQuery：pip install "google-cloud-bigquery[pandas]"）')
"""))

    cells.append(md("""
### CONFIG — 只改這一格

價格常數**使用前必須到官方頁面現查更新**：
<https://cloud.google.com/vertex-ai/generative-ai/pricing>

模型與價格變動頻繁，任何寫死的數字都會很快過期。
要看實際花費，請以 §5 執行後印出來的金額為準。

> `PROJECT_ID`、`LOCATION` 與 BigQuery 那幾個值是**建構這份 notebook 時注入的**。
> 要換成你自己的環境，改這一格就好；若你是從原始 repo 重新產生，
> 用 `python3 poc/build_notebook.py --project-id 你的專案` 一次帶進來。
"""))
    cells.append(code(_inject_config_values(module_source("config"))))

    cells.append(md("""
### 呼叫層與離線重播

底下這段程式碼做兩件事。

**第一，切換 Vertex AI 與 AI Studio 只差 Client 的建構參數**，
其他程式碼一行都不用改。選哪一個是**部署決策**
（資料落地、計費歸屬、VPC-SC、合規），不是**程式碼決策**。
先用 AI Studio 做原型，要簽 DPA 時再切到 Vertex。

**第二，離線重播。** 在網路不穩的場合即時打 API 是不能接受的風險，
所以有兩個模式：

| 設定 | 何時用 | 行為 |
|---|---|---|
| `RECORD_FIXTURES=True` | 有網路時，先跑一次 | 正常呼叫，同時把輸出錄下來 |
| `OFFLINE_MODE=True` | 之後任何時候 | 零網路，重播錄好的輸出 |

重播時**所有 cell 一樣會執行、表格一樣是當場算出來的**，
只有 API 呼叫被換成查表。`ReplayClient` 找不到對應輸出時會明確報錯，
不會靜默拿到過期資料。
"""))
    cells.append(code(module_source("generation")))

    fixtures_path = DATA / "demo_outputs.json"
    if fixtures_path.exists():
        fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
        n_calls = len(fixtures.get("calls", {}))
        # 有 fixtures 就預設走離線重播。
        #
        # 理由：fixtures 存在的唯一目的就是離線重播，沒有別的用途。
        # 原本要靠人記得在上場前把旗標翻成 True，而那正是最容易忘的一步 ——
        # 忘了就會在沒網路的會場當場打 API。與其寫進檢查清單，不如讓它預設就對。
        #
        # 這個覆寫只作用在 notebook；src/config.py 的預設值維持 False，
        # 所以 run_eval.py 等本機腳本仍然走一般連線模式。
        cells.append(code(
            f"# 已錄製 {n_calls} 筆真實輸出，直接內嵌在這一格。\n"
            f"# 只要有這份資料，這個 notebook 單獨一個檔案就能零網路跑完。\n"
            f"OFFLINE_MODE = True   # ← 有 fixtures 就預設離線；要真的打 API 改成 False\n"
            f"FIXTURES = {json.dumps(fixtures, ensure_ascii=False)}\n"
            f"print(f'已載入 {{len(FIXTURES[\"calls\"]):,}} 筆錄製輸出'"
            f" + ('　模式：離線重播' if OFFLINE_MODE else '　模式：連線'))"
        ))
    else:
        cells.append(code(
            "# ⚠ 尚未錄製 fixtures，OFFLINE_MODE 目前不可用。\n"
            "#   請設定 RECORD_FIXTURES=True 在有網路時跑一次，\n"
            "#   下載產生的 demo_outputs.json 放到 poc/data/，再重新產生 notebook。\n"
            "FIXTURES = {'calls': {}, 'token_counts': {}}"
        ))

    cells.append(code("""
import json, time, re
from dataclasses import dataclass, field, asdict
import pandas as pd

client = make_client(FIXTURES)

if OFFLINE_MODE:
    print("✓ 離線重播模式 — 不會連網")
elif RECORD_FIXTURES:
    print("✓ 錄製模式 — 正常呼叫並記錄輸出")
    print(f"  {'Vertex AI' if USE_VERTEX else 'Gemini API'}")
else:
    print(f"✓ {'Vertex AI — project=' + PROJECT_ID if USE_VERTEX else 'Gemini API (AI Studio key)'}")

print(f"  生成模型：{GEN_MODEL}")
print(f"  評審模型：{JUDGE_MODEL}  ← 刻意與生成模型不同，降低 self-preference bias")
"""))
    cells.extend(cue("""
**30:00 — 捲動帶過，不要逐行讀。**

要說的一句：「注意這幾行 —— 切 Vertex 或 AI Studio 只差 client 的參數，
底下所有程式碼一行都不用改。這是部署決策，不是技術決策。」
"""))

    # ---------------------------------------------------------------- §1
    cells.append(md("""
## §1 商品資料

50 筆模擬台灣電商 PIM 匯出的商品資料 —— **這也是評測集本身**。
前 12 筆是手寫的（規格較完整，等一下看文案時用它們），後面是組合生成的，
用來補足統計需要的樣本量。

50 筆 × 7 條 rubric = 350 次檢查，雜訊底線 0.29 個百分點 ——
足以分辨 3 個百分點以上的差距。

刻意涵蓋三種法規類別：

- `food` — 保健食品／食品，受《食品安全衛生管理法》第 28 條規範
- `cosmetic` — 美妝保養，受《化粧品衛生安全管理法》第 10 條規範
- `general` — 3C／家電，無特殊廣告限制

**這個欄位是後面所有事情的關鍵。** 「護眼」用在葉黃素上是違規，
用在螢幕護目鏡上不是。規則必須跟著商品屬性走。
"""))
    cells.append(code(
        f"PRODUCTS_RAW = {json.dumps(products, ensure_ascii=False, indent=1)}\n\n"
        "PRODUCTS = PRODUCTS_RAW['products']\n"
        "CHANNEL_LIMITS = PRODUCTS_RAW['_meta']['channel_limits']\n\n"
        "import pandas as pd\n"
        "from collections import Counter\n"
        "print(f'共 {len(PRODUCTS)} 筆　法規類別分佈：'\n"
        "      + '　'.join(f'{k} {v}' for k, v in "
        "sorted(Counter(p['regulated_category'] for p in PRODUCTS).items())))\n"
        "print('（下表只顯示前 12 筆手寫商品，等一下的文案示範會用它們）')\n"
        "pd.DataFrame([{\n"
        "    'SKU': p['sku'], '商品': p['name'][:24],\n"
        "    '法規類別': p['regulated_category'], '售價': p['price'],\n"
        "} for p in PRODUCTS[:12]])"
    ))

    cells.append(md("""
### 禁詞清單

依台灣廣告法規整理，分成四組。**罰則差異很大**：

| 類別 | 法源 | 罰則 |
|---|---|---|
| 醫療效能 | 食安法 §28 第2項 | NT$60萬 – 500萬 |
| 不實誇張 | 食安法 §28 第1項 | NT$4萬 – 400萬 |
| 化粧品虛偽誇大 | 化粧品衛管法 §10 | NT$4萬 – 20萬 |

> 這不是工程潔癖，是不做會收罰單。這也是為什麼規則層要放在第一層。

⚠️ 本清單為示範用的簡化版，不構成法律意見；實際商用前應由法務或法規顧問審閱。
"""))
    cells.append(code(
        f"BANNED_DATA = {json.dumps(banned, ensure_ascii=False, indent=1)}\n\n"
        "for k, v in BANNED_DATA.items():\n"
        "    if isinstance(v, dict) and 'terms' in v:\n"
        "        print(f\"{k:24s} {len(v['terms']):>3} 詞  適用：{'/'.join(v['applies_to'])}\")"
    ))

    # ---------------------------------------------------------------- §2
    cells.append(md("""
## §2 Prompt v0 → v3

**設計原則：每一版只加一件事。**

這樣評測表上每一欄的改善都能歸因到單一改動。若一次加三件事，
表格會一次全綠，就失去「哪個改動帶來哪個改善」的教學價值。

| 版本 | 加了什麼 | 預期修好 |
|---|---|---|
| v0 | 什麼都不給 | — （基準線）|
| v1 | 角色／受眾／字數／必含規格 | 長度、規格覆蓋 |
| v2 | 法規禁詞 + 品牌語調 few-shot | 禁詞、語調 |
| v3 | `responseSchema` 結構化輸出 | 可機器讀取 |
"""))
    cells.append(code(module_source("prompts")))

    cells.append(md("### 看一下四個版本的實際差異"))
    cells.append(code("""
p = PRODUCTS[0]   # 葉黃素 — 保健食品，法規風險最高的類別
terms = get_banned_terms_for(p, BANNED_DATA)

for name, fn in PROMPT_VERSIONS.items():
    text = fn(p, banned_terms=terms, tone_examples=TONE_EXAMPLES[p['brand']])
    print(f"{name}: {len(text):>5,} 字元")

print("\\n" + "=" * 72)
print("v0 全文（這就是大多數人第一次寫的 prompt）")
print("=" * 72)
print(PROMPT_VERSIONS['v0'](p))
"""))
    cells.append(code("""
print("=" * 72)
print("v3 全文 — 注意法規段落與 few-shot 是怎麼寫的")
print("=" * 72)
print(PROMPT_VERSIONS['v3'](p, banned_terms=terms, tone_examples=TONE_EXAMPLES[p['brand']]))
"""))

    cells.append(md("""
### 生成

`generate(..., structured=True)` 時啟用 API 原生的 `responseSchema` ——
**這是 v3 與 v2 的唯一差別**（呼叫層的程式碼在 §0）。

**重點：不要用 prompt 硬凹 JSON 格式，要用 API 參數約束。**
prompt 裡寫「請輸出 JSON」模型會照做九成的時間；用 `responseSchema`
模型是被解碼器約束在 schema 內，那一成的失敗才會消失。
"""))
    cells.append(code("""
ledger = UsageLedger()

# 12 商品 × 4 版 = 48 次呼叫，彼此獨立，所以並行跑。
jobs = [(p, v) for p in PRODUCTS for v in PROMPT_VERSIONS]


def _generate_one(job):
    product, version = job
    prompt = PROMPT_VERSIONS[version](
        product,
        banned_terms=get_banned_terms_for(product, BANNED_DATA),
        tone_examples=TONE_EXAMPLES.get(product['brand']),
    )
    res = generate(client, prompt, structured=(version in STRUCTURED_VERSIONS))
    ledger.record(f"gen:{version}", res.usage)
    return (product['sku'], version), res


t0 = time.time()
outputs = {}   # (sku, version) -> 文案原文
for key, res in run_parallel(_generate_one, jobs, label="生成"):
    outputs[key] = res.text
    if res.error:
        print(f"  ⚠ {key}: {res.error}")

print(f"\\n共 {len(outputs)} 筆，耗時 {time.time() - t0:.1f} 秒")
"""))

    cells.append(md("### 肉眼比對：同一個商品，v0 vs v3"))
    cells.append(code("""
sku = PRODUCTS[0]['sku']
print("=" * 72); print(f"{sku}  v0"); print("=" * 72)
print(outputs[(sku, 'v0')])
print("\\n" + "=" * 72); print(f"{sku}  v3"); print("=" * 72)
print(outputs[(sku, 'v3')])
"""))
    cells.extend(cue("""
**33:30 — ▶ 重跑 v0。**「看起來不錯對吧？文筆很好。」（停頓）「但它不能用。」

**35:00 — ▶ 重跑 v3。**「同一個商品。」

先不要解釋為什麼 v3 比較好 —— 讓他們自己看。解釋留到對比表。
"""))

    # ---------------------------------------------------------------- §3
    cells.append(md("""
## §3 評測 — 這一節是重點

三層評測，由便宜到貴：

1. **規則層** — 免費、毫秒級、確定性，可以進 CI
2. **LLM judge** — 有成本、有偏誤，只評規則層評不了的東西
3. **人工抽樣** — 最貴，只看前兩層有分歧的

**順序很重要。** 多數團隊一上來就做 LLM judge，又貴又不穩。
先建規則層：它擋掉大部分明確錯誤，而且結果可重現。
"""))

    cells.append(md("""
### 第一層：規則

注意 `parse_freeform()` —— 為了評測 v0～v2 的自由文字輸出，
我們被迫寫一個靠正則猜測的 parser。**模型換個排版它就壞掉。**

這段脆弱的程式碼本身就是「為什麼要用 structured output」最好的論據。
v3 之後這整段可以刪掉。
"""))
    cells.extend(cue("""
**36:30 — 秀 `parse_freeform()`，這段工程師最有共鳴。**

「為了評 v0，我得寫這種靠正則猜測的 parser。模型換個排版它就壞掉。
**v3 之後這段可以整個刪掉。**」
"""))
    cells.append(code(module_source("rules")))
    cells.append(code(module_source("report")))

    cells.append(md("### ★ 規則層對比表"))
    cells.append(code("""
rule_results = []
for product in PRODUCTS:
    terms = get_banned_terms_for(product, BANNED_DATA)
    for version in PROMPT_VERSIONS:
        rule_results.append(
            evaluate_rules(outputs[(product['sku'], version)], product, version, terms)
        )

print(render_text_table(rule_results))
"""))
    cells.append(code("""
# 同一張表的 DataFrame 版本（投影用，數字大一點好讀）
to_dataframe(rule_results).style.format("{:.0f}%").background_gradient(cmap="RdYlGn", vmin=0, vmax=100)
"""))

    cells.append(md("""
### 違規細節 — 證明這不是假資料

規則層不只能擋，還能給修改方向。這讓它從一個惹人厭的 linter
變成文案人員真的願意用的工具。
"""))
    cells.append(code("""
for version in ['v0', 'v1', 'v2', 'v3']:
    print(violation_detail(rule_results, version))
    print()

# 對命中的禁詞給出合規替代寫法
worst = max((r for r in rule_results if r.version == 'v0'),
            key=lambda r: len(r.banned_hits), default=None)
if worst and worst.banned_hits:
    print("=" * 60)
    print(f"{worst.sku} 的修改建議：")
    for bad, good in suggest_fix(worst.banned_hits, BANNED_DATA).items():
        print(f"  ✗ {bad}  →  ✓ {good}")
"""))

    cells.append(md("""
### 第二層：LLM-as-judge —— 用二元 rubric，不用 1–5 分

只評規則層評不了的：語調、賣點覆蓋。

#### 為什麼不用 1–5 分？

早期的 LLM-as-judge 幾乎都用 Likert 量表。實務上它有幾個難以修復的問題：

| 問題 | 後果 |
|---|---|
| 分數擠在 3–4 分 | 鑑別度低，看不出差異 |
| 同一份文案今天 4 分明天 3 分 | 不可重現，無法判斷是模型變差還是評審漂移 |
| 換評審模型整組分數平移 | 歷史數據作廢 |
| 寫得長、寫得華麗容易拿高分 | verbosity bias |
| **「3.8 分」無法行動** | 你不知道要改什麼 |

二元 rubric 把一個模糊的大問題，拆成一組**具體、可檢查的 yes/no 小問題**：

```
✗  「這份文案的品質有幾分？」          → 3.8 / 5，然後呢？
✓  「文案是否寫出游離型葉黃素 30mg？」  → 否 → 知道要補什麼
```

這也是 Vertex AI Gen AI Evaluation Service 把 adaptive rubrics
形容成**「像單元測試」**的原因。

#### 公平性：rubric 只從商品資料生成，不看被評的文案

**每個商品產生一次，v0～v3 共用同一組。**
如果讓評審看著文案即興出題，每個版本會被問不同的問題 ——
那等於每個考生考不同的考卷，對比表就沒有意義了。
"""))
    cells.append(code(module_source("judge")))
    cells.append(code("""
for name, info in JUDGE_BIASES.items():
    print(f"● {name}")
    print(f"    問題：{info['說明']}")
    print(f"    緩解：{info['緩解']}\\n")
"""))

    cells.append(md("""
#### 步驟一：為每個商品產生驗收清單

這一步和被評的文案無關，只看商品資料。
"""))
    cells.append(code("""
t0 = time.time()
rubric_sets = dict(
    run_parallel(
        lambda p: (p['sku'], generate_rubrics(client, p, ledger)),
        PRODUCTS,
        label="產生 rubric",
    )
)
print(f"  耗時 {time.time() - t0:.1f} 秒")

demo = rubric_sets[PRODUCTS[0]['sku']]
print(f"{PRODUCTS[0]['name']} 的驗收清單（{len(demo.rubrics)} 條）\\n")
for r in demo.rubrics:
    mark = "★" if r.critical else " "
    print(f"  {mark} {r.id}  [{r.dimension}] {r.criterion}")
print("\\n★ = critical，未通過就不該上架")
"""))

    cells.append(md("""
#### 步驟二：逐條檢查

只送規則層過關的文案去評審 —— **這是省錢的關鍵**。
對一份已經違反法規的文案做語意檢查沒有意義，而 judge 用的是比生成更貴的模型。
"""))
    cells.append(code("""
by_key = {(r.sku, r.version): r for r in rule_results}

# 評測時全部送審 —— 分母一致才能比較。
to_judge = [(p, v) for p in PRODUCTS for v in PROMPT_VERSIONS]

# 生產環境會怎麼做：規則層擋下的不送審。這裡只統計、不實際跳過，
# 用來對照「同一個機制在不同目的下取捨相反」。
would_skip = sum(
    1 for p in PRODUCTS for v in PROMPT_VERSIONS
    if not should_judge(by_key[(p['sku'], v)])
)
total = len(PRODUCTS) * len(PROMPT_VERSIONS)
print(f"送審 {len(to_judge)}/{total} 筆 —— 評測全送，四個版本的分母才一致")
print(f"生產環境會擋下其中 {would_skip} 筆，省 {would_skip/total*100:.0f}% 評審成本。")
print("但評測時不值得：省下的是零頭，換掉的是「版本之間能不能比較」。")

# 這是整份 notebook 最慢的一段：評審模型單次十幾秒。
# 序列跑約 9 分鐘，並行後約 1 分鐘。
t0 = time.time()
rubric_reports = run_parallel(
    lambda job: check_against_rubrics(
        client, outputs[(job[0]['sku'], job[1])],
        rubric_sets[job[0]['sku']], job[1], ledger
    ),
    to_judge,
    label="評審",
)
print(f"  耗時 {time.time() - t0:.1f} 秒\\n")
pd.DataFrame(summarize_rubrics(rubric_reports, total_items=len(PRODUCTS))).T
"""))

    cells.append(md("""
#### 最常沒過的判準 —— 這才是能拿去改 prompt 的東西

這正是二元 rubric 勝過分數的地方：「3.8 分」不能行動，
「有 9 個商品沒寫出含量」可以。
"""))
    cells.append(code("""
for criterion, n in most_common_failures(rubric_reports, rubric_sets):
    print(f"  {n:>2} 次未通過 — {criterion}")

worst = [r for r in rubric_reports if r.version == 'v0' and r.failed]
if worst:
    r = worst[0]
    print(f"\\n{r.sku} v0 未通過的細節（{r.pass_rate}% 通過）：")
    for rid, reason, crit in r.failed[:4]:
        print(f"  {'★' if crit else ' '} {rid}: {reason}")
"""))

    cells.append(md("""
### ★★ 合併對比表 —— 每一版修好一件事

這張表是整份 notebook 的結論。左邊三欄由 v1 修好、中間兩欄由 v2 修好、
最後一欄由 v3 修好 —— **每一版的貢獻都能單獨看見**。
"""))
    cells.append(code("""
print(render_paired(rubric_reports, list(PROMPT_VERSIONS)))
print()
print(significance_note(len(PRODUCTS), 7))

combined = combined_table(
    rule_results, summarize_rubrics(rubric_reports, total_items=len(PRODUCTS))
)
print(PARSER_CAVEAT)
combined.style.format("{:.1f}%", na_rep="—").background_gradient(
    cmap="RdYlGn", vmin=0, vmax=100)
"""))
    cells.extend(cue("""
**38:00 — ★ 全場高潮。表格出來後停 5 秒不要說話，讓大家看。**

然後：「每一版修好一件事。左邊三欄是 v1、中間兩欄是 v2、最後一欄是 v3。」

**接著一定要講這兩句，這是誠信也是專業度：**

1.「台上這張是 12 個商品，樣本太小。**真正的結論來自另外跑的 50 筆評測集**
   —— 就是投影片 S17c 那組數字。demo 給你看流程，結論要看評測集。」
2.「50 筆的結果：v0→v1、v1→v2 是真的改善；**v2→v3 只差 0.3 個百分點，
   那是雜訊。** v3 贏的不是文案品質，是可機器讀取從 0 變成 100%。」

**不要**說「你看全部都變好了」。台下有工程師，會扣分。
"""))

    cells.append(md("""
#### 讀這張表的時候要小心兩件事

**⚠️ 先看這個：rubric 那一列不是遞增的，v0（78.5%）比 v1（74.0%）高。**

台上一定會有人注意到。**先講，不要等被問。** 台詞：

> 「注意 rubric 這一列 —— v0 竟然比 v1 高。是 v0 比較好嗎？
> 看旁邊那欄『受評筆數』：v0 只有 8 筆，v1 有 11 筆。
> **v0 最爛的 4 筆被規則層擋下來，根本沒進評分。**
> 分母不同，這兩個數字不能比。
>
> 這就是為什麼我把受評筆數印在表上 —— 不然這格看起來就像 v1 讓事情變糟了。」

這是全場最好的評測方法論教材：**倖存者偏差，而且是活生生出現在自己的表上。**
「可直接上架%」那一列就沒有這個問題，因為它用固定分母（12）計算，
被擋下的一律算不通過。**那才是能拿來做決策的數字。**

---

**一、這裡的樣本太小，只能看趨勢，不能下結論。**
12 個商品、rubric 每個 7 條，共 84 次檢查，翻轉一次就是 1.2 個百分點。
把雜訊當成訊號，是評測工作最容易犯、也最傷的錯。

真正的結論來自另外跑的 **50 筆評測集**（`poc/run_eval.py`）——
350 次檢查、雜訊底線 0.29 個百分點。實測結果：

| | rubric 通過率 | 可直接上架 | 可機器讀取 |
|---|---|---|---|
| v0 | 68.4% | 14% | 0% |
| v1 | 79.1% | 42% | 0% |
| v2 | 86.3% | 72% | 0% |
| v3 | 86.6% | 68% | **100%** |

**二、v2 → v3 只差 0.3 個百分點 —— 那是雜訊，不能說 v3 讓文案變好。**

v3 真正的價值在最後一欄。**v3 不是讓文案變好，是讓文案變得可用。**
這是兩件不同的事，而你兩個都需要。

一張每格都完美遞增的表，通常代表有人在調數字。

**三、上面那一欄「實測歸因」是算出來的，不是寫死的。**
它比較相鄰版本的差距、取單步改善最大的那一版。這件事本身有教訓：
最早這裡是一份手寫對照表，後來實跑 50 筆，六條裡有三條被資料推翻
（例如「SEO描述」原本標成 v1 修好，實際上 v1 完全沒動，是 v3 修的）。
**在講評測的材料裡放一個硬寫的因果宣稱，是最不該犯的錯。**
"""))

    # ---------------------------------------------------------------- §4
    cells.append(md("""
## §4 場景 B：評論洞察

方法論完全相同，方向相反：

    場景 A   結構化資料 → 非結構化文字   （生成）
    場景 B   非結構化文字 → 結構化資料   （抽取）

**這一節的目的不是教評論分析**，而是證明你剛學的是一套流程，不是一個文案技巧。
同樣要 schema、同樣要評測、同樣要算成本。
"""))
    cells.append(code(module_source("insights")))
    cells.append(code(
        f"REVIEWS = {json.dumps(reviews, ensure_ascii=False, indent=1)}['reviews']\n\n"
        "name_by_sku = {p['sku']: p['name'] for p in PRODUCTS}\n"
        "insights = run_parallel(\n"
        "    lambda r: extract_one(client, r, name_by_sku.get(r['sku'], '未知商品'), ledger),\n"
        "    REVIEWS,\n"
        "    label='抽取評論',\n"
        ")\n\n"
        "to_dataframe(insights)[['review_id','rating','sentiment','aspects',\n"
        "                        'is_about_product','urgency']]"
    ))

    cells.append(md("""
### 抽取任務也要評測

沒有「好文案」這種主觀標準，但仍有可自動檢查的規則：
星等與情緒矛盾、enum 值非法、5 星卻標高急迫。

這些抓到的不是「模型寫得不好」，而是**「模型理解錯了」—— 更嚴重**。
"""))
    cells.append(code("""
check = validate_insights(insights)
print(f"通過率 {check['通過率']}%  （{check['總筆數'] - check['問題筆數']}/{check['總筆數']}）")
for rid, msg in check['明細']:
    print(f"  ⚠ {rid}: {msg}")

print("\\n" + "=" * 60)
print(business_summary(insights))
"""))

    cells.append(md("""
#### 落地到 BigQuery — 讓「變成結構化資料」不只是說說

到這裡為止，結構化資料還只存在於記憶體裡。真正的價值要等它**進到資料倉儲、
能被 SQL 查詢、能接上既有的 BI 報表**才會發生。

注意 schema 的設計重點：`is_about_product` 這個欄位把「商品不好」與
「服務不好」分開儲存。混在一起統計，採購會以為商品品質有問題，
實際上是物流慢。

> 預設 `USE_BIGQUERY = False`。要真的寫入請在 CONFIG 打開，
> 並確認專案已啟用 BigQuery API 且帳號有 `bigquery.dataEditor` 權限。
> 離線重播模式不涵蓋 BigQuery 呼叫。
"""))
    cells.append(code("""
print("建表 SQL：")
print(BQ_SCHEMA_SQL.format(project=PROJECT_ID, dataset=BQ_DATASET, table=BQ_TABLE))
print("\\n分析 SQL —— 這句就是整個場景 B 的商業價值：")
print(BQ_INSIGHT_SQL.format(project=PROJECT_ID, dataset=BQ_DATASET, table=BQ_TABLE))
"""))
    cells.append(code("""
if USE_BIGQUERY:
    load_to_bigquery(insights)
    bq_df = query_bigquery_insights()
    display(bq_df)
else:
    print("USE_BIGQUERY = False — 只展示 schema 與 SQL，未實際寫入。")
    print("要真的跑，請在 CONFIG 把 USE_BIGQUERY 設為 True。")
"""))

    # ---------------------------------------------------------------- §5
    cells.append(md("""
## §5 成本

**教公式，不背數字。**

    單次成本 = (input_tokens × 單價_in + output_tokens × 單價_out) / 1,000,000
    月成本  = 單次 × SKU數 × 每SKU重生成次數 × (1 + judge 開銷比)

下面印出來的是**這次執行的真實花費**，比任何通用估算都準 ——
因為 prompt 長度、輸出長度、中文 token 密度全是這個專案的實際值。
"""))
    cells.append(code(module_source("costs")))
    cells.append(code("""
print(price_check_reminder())
print("\\n" + "=" * 60)
print("這次 demo 的實際用量")
print("=" * 60)
print(ledger.summary())
"""))
    cells.extend(cue("""
**41:00 — 唸出實際的「評審佔總成本 __%」。**

這個數字每次跑都會變，**唸畫面上的，不要唸背下來的**。
（前一天錄製時先看過一次，心裡有個底。）

「評審佔了這麼多。這是最常被漏算的一筆 —— 大家算成本只算生成。」
"""))

    cells.append(md("### 實測中文 token 密度 — 不要背經驗法則"))
    cells.append(code("""
samples = [
    PRODUCTS[0]['name'],
    "游離型葉黃素30mg，吸收更直接",
    PROMPT_VERSIONS['v3'](PRODUCTS[0],
                          banned_terms=get_banned_terms_for(PRODUCTS[0], BANNED_DATA),
                          tone_examples=TONE_EXAMPLES[PRODUCTS[0]['brand']])[:500],
    "Volta 240W USB-C 編織線 2M 支援40Gbps傳輸",   # 中英數混雜
]
density = measure_chinese_token_density(client, samples)
pd.DataFrame(density['明細'])
"""))
    cells.append(code("""
print(f"平均每字 {density['平均每字token']} tokens"
      f"（範圍 {density['最低']} – {density['最高']}）")
print("\\n↑ 注意範圍有多寬。中英數混雜的文字密度和純中文差很多，")
print("  所以『中文一個字約 X 個 token』這種經驗法則不可靠，要自己量。")
"""))

    cells.append(md("### 外推到正式規模"))
    cells.append(code("""
est = estimate_from_ledger(ledger, sku_count=100_000, regen_per_sku=1.5, judge_ratio=0.7)
print(est.render())
"""))

    cells.append(md("### 降本四招"))
    cells.append(code("print(render_levers())"))

    # ------------------------------------------------------------ 錄製
    cells.append(md("""
---

## §6 錄製 fixtures（需要離線重播時才執行）

這一格把剛剛所有真實 API 輸出存成檔案，之後就能零網路重播。

**流程：**

1. 在**有網路**的環境把 `RECORD_FIXTURES` 設為 `True`，Run all
2. 執行下面這格，下載 `demo_outputs.json`
3. 把檔案放到 `poc/data/`，執行 `python3 poc/build_notebook.py` 重新產生 notebook
4. 把 `OFFLINE_MODE` 設為 `True`，再 Run all 驗證一次 —— **這次應該完全不連網**
5. 之後在任何沒有網路的環境都能完整重跑
"""))
    cells.append(code("""
if RECORD_FIXTURES:
    dump = client.dump()
    with open(FIXTURES_FILE, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False)
    print(f"✓ 已錄製 {len(dump['calls']):,} 筆呼叫、"
          f"{len(dump['token_counts']):,} 筆 token 計數 → {FIXTURES_FILE}")
    try:
        from google.colab import files
        files.download(FIXTURES_FILE)
    except ImportError:
        print("  （本機執行，檔案已寫在當前目錄）")
elif OFFLINE_MODE:
    print(f"離線重播模式：本次共命中 {client.models.hits:,} 筆錄製輸出，全程未連網。")
else:
    print("目前是一般連線模式。若要錄製以供離線重播，請把 RECORD_FIXTURES 設為 True。")
"""))

    cells.append(md("""
---

## 收尾

回到一開始的問題：**你怎麼知道它有沒有變好？**

現在你有一張表可以回答。而且那張表是自動產生的，
下次改 prompt、換模型、降級省錢的時候，重跑一次就知道有沒有退步。

**這才是能上線的東西。**

---

### 帶回去的三件事

1. **先建規則層。** 免費、確定性、可以進 CI。不要一開始就做 LLM judge。
2. **用 API 原生的 structured output**，不要用 prompt 硬凹 JSON。
3. **評測本身要花錢**，記得算進去 —— 這是最常被漏掉的一筆。

### 90 天導入路徑

| 階段 | 時間 | 產出 |
|---|---|---|
| Vertex AI Studio 驗證可行性 | 2 週 | 這件事到底做不做得成 |
| 建 golden set + API 串接 | 4 週 | 30–50 筆就足以開始 |
| 小流量上線 + 監控 | 6 週 | 有數字可以對董事會報告 |
"""))
    cells.extend(cue("""
**41:45 — 捲回對比表收尾。**

「所以：你怎麼知道它有沒有變好？看這張表。」

然後切回投影片，講最後三件事帶回去。

---

⏱ **超時的話砍 §4（場景 B）**，不影響主論點。
"""))

    return cells


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="從 src/ 與 data/ 產生兩份自足的 Colab notebook。",
        epilog=(
            "識別資訊不寫死在 repo 裡，在這裡注入。"
            "每個參數都可以改用環境變數；兩者都沒給就用 src/config.py 的預設值。"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    for key, (const, help_text) in CONFIG_PARAMS.items():
        env = {"project_id": "GCP_PROJECT_ID", "location": "GCP_LOCATION"}.get(key, const)
        p.add_argument(
            f"--{key.replace('_', '-')}",
            default=PROFILE[key],
            metavar=const,
            help=f"{help_text}（環境變數 {env}）",
        )
    for key, (env, _label, help_text) in BYLINE_PARAMS.items():
        p.add_argument(
            f"--{key}",
            default=PROFILE[key],
            metavar=env,
            help=f"{help_text}，寫進標題（環境變數 {env}）",
        )
    p.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=ROOT,
        help="notebook 的輸出目錄",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    global _MODE

    args = parse_args(argv)
    PROFILE.update({key: getattr(args, key) for key in (*CONFIG_PARAMS, *BYLINE_PARAMS)})

    outputs = {mode: args.out_dir / path.name for mode, path in OUTPUTS.items()}
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if PROFILE["project_id"] == "your-gcp-project-id":
        print(
            "! 未指定 GCP 專案 —— notebook 裡會留著佔位字串 your-gcp-project-id。\n"
            "  離線重播不受影響；要真的呼叫 API 請加 --project-id 或設 GCP_PROJECT_ID。"
        )

    for mode, out in outputs.items():
        _MODE = mode
        nb = {
            "cells": build(),
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                },
                "language_info": {"name": "python", "version": "3.12"},
                "colab": {"provenance": [], "toc_visible": True},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")

        n_code = sum(c["cell_type"] == "code" for c in nb["cells"])
        n_md = sum(c["cell_type"] == "markdown" for c in nb["cells"])
        label = "聽眾版" if mode == "audience" else "講者版"
        print(
            f"✓ {label}  {out.name}\n"
            f"    {len(nb['cells'])} cells（code {n_code} / markdown {n_md}）"
            f"，{out.stat().st_size / 1024:.0f} KB"
        )

    _MODE = "audience"


if __name__ == "__main__":
    main()
