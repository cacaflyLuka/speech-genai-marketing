# Google Cloud & Generative AI Applications — 演講與 POC

2026-08-21｜新創加速器｜45 分鐘（30 講 + 12 demo + 3 QA）

**主題**：生成式 AI 的難處不在叫模型，而在你怎麼知道它有沒有變好。

---

## 目錄

```
pyproject.toml           相依、pytest 與 ruff 設定（uv 管理）
uv.lock                  鎖定版本，確保換機器裝出同一套環境
.python-version          Python 3.12
Makefile                 常用指令捷徑（make help）

talk/
  abstract.md                主辦方提交用：短主題 + 條列式大綱
  script.md                  大綱 + 逐頁講稿 + demo 腳本 + QA + 上場前檢查清單
  build_slides.py            ★ 產生版面型投影片與播放器（版面規則只寫在這裡）
  slides.html                ★ 產物：29 張投影片的單一檔案播放器，可全螢幕
  assets/                    投影片（1280×720，右下角留給 logo）
    tool-map.svg             ☐ 手繪：GCP 三層工具地圖
    eval-pyramid.svg         ☐ 手繪：三層評測金字塔
    results.svg              ☐ 手繪：50 筆評測結果總表
    significance.svg         ☐ 手繪：配對比較的信賴區間
    cost-model.svg           ☐ 手繪：成本公式與降本四招
    gcp-architecture.svg     ☐ 手繪：demo 用到的 GCP vs 正式上線需要的
    其餘 23 張               由 build_slides.py 產生，檔頭有標記，不要手改

poc/
  retail_genai_poc.ipynb          ★ 聽眾版 —— 乾淨教材，會後發給大家
  retail_genai_poc_speaker.ipynb  ★ 講者版 —— 同樣內容 + 舞台指示
  build_notebook.py               從 src/ + data/ 產生上面兩份；識別資訊在這裡注入
  check_env.py                    上場前環境健檢
  data/
    products.json          12 筆手寫商品（會被併入 eval_products.json 前段）
    eval_products.json     ★ 200 筆評測集，notebook 取前 50 筆 —— demo 與評測同一份資料
    banned_terms.json      禁詞清單，依台灣廣告法規分類
    reviews.json           15 則假評論（含錯字與離題）
    demo_outputs.json      錄製的真實輸出（尚未產生，見下方 D-1 流程）
  src/
    config.py              ★ 模型、價格、旗標 —— 只改這裡
    prompts.py             v0 → v3 的 prompt 演進
    generation.py          Gemini 呼叫 + 用量記錄 + 離線重播
    rules.py               評測第一層：規則（無需 API）
    judge.py               評測第二層：二元 rubric（非 1–5 分）
    report.py              對比表 + 統計顯著性提醒
    insights.py            場景 B：評論洞察 + BigQuery
    costs.py               成本外推與降本槓桿
    dashboard.py           §6 總覽儀表板（matplotlib，不重算任何數字）
  tests/                   64 項，全部離線、不呼叫 API、不花錢
```

---

## 名詞：GEAP＝原 Vertex AI

Vertex AI 在 **2026 年 4 月的 Cloud Next 改名為 Gemini Enterprise Agent
Platform（GEAP）**，5 月底完成遷移，主控台搜尋 Vertex AI 會轉到 Agent Platform。
文件、講稿、投影片一律用新名。

**但程式碼裡的舊名是刻意保留的** —— 改名沒有動到介面：

| 位置 | 值 | 為什麼不改 |
|---|---|---|
| `genai.Client(vertexai=True)` | SDK 參數 | google-genai 的參數名沒改 |
| `USE_VERTEX` | 本專案旗標 | 直接對應上面那個 SDK 參數 |
| `aiplatform.googleapis.com` | 服務名 | 端點沒改 |
| `cloud.google.com/vertex-ai/...` | pricing 網址 | 官方網址仍是這個路徑 |

跟著產品名一起改這些，只會讓程式碼跟 SDK 對不起來。

---

## 操作流程

> Python 環境由 [uv](https://docs.astral.sh/uv/) 管理。所有指令都用 `uv run`，
> 不需要手動建立或啟用虛擬環境。常用指令另有 `make` 捷徑（`make help` 看清單）。

### 0　初次設定（一次就好）

安裝 uv（若尚未安裝）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

建立環境並安裝相依（含 dev 工具）：

```bash
uv sync
```

會依 `pyproject.toml` 與 `uv.lock` 建出 `.venv`，Python 版本由 `.python-version` 決定。

登入並指定專案：

```bash
gcloud auth login && gcloud auth application-default login
```

**專案 ID 不寫死在 repo 裡**，走環境變數（見下方「參數化」）：

```bash
export GCP_PROJECT_ID=你的專案
gcloud config set project "$GCP_PROJECT_ID"
```

啟用需要的 API：

```bash
gcloud services enable aiplatform.googleapis.com bigquery.googleapis.com --project="$GCP_PROJECT_ID"
```

驗證環境（**最重要的一步**）：

```bash
uv run python poc/check_env.py
```

（或 `make check`）會逐項檢查認證、模型可用性、structured output、價格常數、重播狀態。
**換專案、換 region、換模型之後都要重跑。**

> ⚠️ `LOCATION` 必須是 `"global"`。`asia-east1` 上沒有任何 Gemini publisher
> model，所有呼叫都會 404。這正是 `check_env.py` 存在的原因。

---

### 0-1　參數化：換一個人用要改什麼

**識別資訊不寫死在 repo 裡。** 換人、換公司、換 GCP 專案就要換的值全部走
環境變數，notebook 則在**建構時注入**成字面值 —— 因為 notebook 會被單獨上傳到
Colab，那裡沒有你的 shell 環境。

| 環境變數 | 預設 | 用途 |
|---|---|---|
| `GCP_PROJECT_ID` | `your-gcp-project-id`（佔位） | GCP 專案 ID |
| `GCP_LOCATION` | `global` | Gemini 的 location，**實測必須是 global** |
| `BQ_DATASET` | `retail_genai_demo` | 場景 B 的 dataset |
| `BQ_TABLE` | `review_insights` | 場景 B 的 table |
| `BQ_LOCATION` | `asia-east1` | BigQuery 的 region（與 Gemini 無關）|
| `SPEAKER_NAME` | 空 | 講者姓名，寫進 notebook 標題 |
| `EVENT_NAME` | 空 | 場次／主辦單位 |
| `TALK_DATE` | 空 | 日期 |

`src/config.py` 與 `build_notebook.py` 讀的是同一組變數，所以
`run_eval.py`、`check_env.py` 這些不經過 notebook 的路徑也會拿到同樣的值。

建構 notebook 時也可以直接下參數（**參數優先於環境變數**）：

```bash
uv run python poc/build_notebook.py \
    --project-id 你的專案 --speaker "你的名字" --event "場次名稱" --date 2026-08-21
```

`make build ARGS="--project-id 你的專案"` 也可以。完整清單見
`uv run python poc/build_notebook.py --help`。

沒設 `GCP_PROJECT_ID` 不影響離線重播（重播根本不打 API），
但 `check_env.py` 會直接擋下來，`build_notebook.py` 也會印出提醒。

---

### 1　日常開發循環

改任何程式碼都走這兩步，**不要手改 notebook**：

```bash
make all
```

等同於：

```bash
uv run python poc/build_notebook.py && uv run pytest
```

64 項測試全部離線、不呼叫 API、不花錢。全綠才算改完。

送出前順手跑靜態檢查：

```bash
make lint
```

| 你改了什麼 | 會影響什麼 |
|---|---|
| `src/prompts.py` | **錄好的 fixtures 全部失效**，必須重錄（見 §2）|
| `src/judge.py` 的 prompt | 同上 |
| `src/rules.py`、`report.py` | 只影響評測邏輯，fixtures 仍可用 |
| `src/config.py` 的模型名 | fixtures 失效（key 含模型名）|
| `src/config.py` 的價格 | 只影響金額計算，fixtures 仍可用 |

---

### 2　錄製 fixtures（演講前一天，需要穩定網路）

會場 wifi 不可靠，所以演講當天走離線重播。這一步是保命步驟，**不能跳過**。

**2-1** 先更新價格。到 [官方 pricing 頁](https://cloud.google.com/vertex-ai/generative-ai/pricing)
現查，改 `poc/src/config.py` 的 `PRICING`，並把 `PRICE_LAST_CHECKED` 改成當天日期。

**2-2** 打開錄製模式。編輯 `poc/src/config.py`：

```python
OFFLINE_MODE = False
RECORD_FIXTURES = True
```

**2-3** 重新產生 notebook 並確認測試通過：

```bash
make all
```

**2-4** 在 Colab 開啟 `poc/retail_genai_poc_speaker.ipynb`，**Run all**。

**實測耗時 3.6 分鐘、成本 US$1.50**（50 筆商品、`MAX_WORKERS=64`）。
所有 API 呼叫都用 `run_parallel()` 並行。

| 階段 | 呼叫數 | 備註 |
|---|---|---|
| §2 生成 | 200 | `gemini-flash-latest`，50 商品 × 4 版 |
| §3 rubric 生成 | 50 | `gemini-2.5-pro`，每商品一份考卷 |
| §3 逐條檢查 | 200 | 同上，**全部送審**，分母才一致 |
| §4 評論抽取 | 15 | flash，很快 |

並行度實測（`gemini-2.5-pro`，零失敗）：8→10.3、16→26.1、32→46.5、64→80.7 次/分。
預設 `MAX_WORKERS = 32`，想更快就調到 64。

> 遇到 429（配額不足）就把它調小 —— 生成與評審都有指數退避重試，
> 會自動降速而不是整批失敗。
> 評審模型是主要瓶頸；換成更快的模型會犧牲 self-preference 的緩解效果，
> 除非你確定生成與評審用的是不同模型，否則不建議動。

- 跑完後執行 §7，會下載 `demo_outputs.json`

**2-5** 把下載的檔案放到 `poc/data/`：

```bash
mv ~/Downloads/demo_outputs.json poc/data/demo_outputs.json
```

**2-6** 切換成重播模式。編輯 `poc/src/config.py`：

```python
OFFLINE_MODE = True
RECORD_FIXTURES = False
```

**2-7** 重新產生 notebook（fixtures 會被內嵌進去）：

```bash
make build
```

**2-8** **拔網路驗證** —— 關掉 wifi，在 Colab 重新 Run all。
§7 應印出「本次共命中 N 筆錄製輸出，全程未連網」。

> 💡 **產生出來的 notebook 是自足的單一檔案。**
> fixtures 會被內嵌成 cell 裡的 Python dict，所以**只要上傳這一個 .ipynb 到
> Colab 就能完整跑完，不需要任何額外檔案、不需要網路**。
>
> 重播模式連 `google-genai` 都不需要 —— `gen_config()` 在 SDK 缺席時會退回
> 等效的簡單物件（只有 OFFLINE_MODE 才容許降級；連線模式缺 SDK 會直接報錯）。
> 這點很重要：要裝 SDK 就得有網路，一旦需要網路，「零網路」的前提就破功了。
>
> 檔案大小約 400–700 KB（視真實輸出長度），Colab 單檔上傳沒問題。

**2-9** 記下 §5 印出的「評審佔總成本 __%」。講稿 S18 要唸這個真實數字，
投影片上刻意沒寫死。

> ⚠️ **`demo_outputs.json` 一定要是對真實 API 錄製的。**
> 測試用的假 client 也會產生結構完全正確的同名檔案，數字卻是捏造的。
>
> `check_env.py` 會自動偵測 —— 假資料含有 `模擬判準`、`模擬依據` 這類
> 只有假 client 才會產生的字串，偵測到會直接報 `fixtures 是假資料！`。
> `.gitignore` 也擋掉了根目錄與 `poc/` 下的同名檔，只有
> `poc/data/demo_outputs.json` 會被追蹤。錄製完務必再跑一次 `check_env.py`。

---

### 3　演講當天

- [ ] 開的是 **`retail_genai_poc_speaker.ipynb`（講者版）**，不是聽眾版
- [ ] `config.py` 是 `OFFLINE_MODE = True`（**最容易忘的一項**）
- [ ] 投影片開的是 `talk/slides.html`，按 F 全螢幕確認過
- [ ] 開場前先 Run all 一次，讓所有輸出都在畫面上
- [ ] Colab 字級調大（`Cmd/Ctrl` + `+`），確認投影後對比表看得清楚
- [ ] 關閉通知與其他分頁
- [ ] 預錄影片存在本機（筆電當機時的最後備援）

因為是離線重播，demo 時要重跑哪一格就重跑，秒回，不用等網路。

會後把 **`retail_genai_poc.ipynb`（聽眾版）** 發給聽眾。

---

### 3-0　投影片：`talk/slides.html`

29 張投影片做成**單一自足的 HTML 播放器**。雙擊 `talk/slides.html` 就能開，
不需要伺服器、不需要網路 —— 跟 notebook 走離線重播是同一個理由。

| 操作 | 鍵 |
|---|---|
| 換頁 | `←` `→`、空白鍵、`PageUp/PageDown`、點畫面左右半邊、手機滑動 |
| 全螢幕 | `F` |
| 總覽（縮圖牆，點縮圖跳頁） | `O` 或 `Esc` |
| 第一頁／最後一頁 | `Home` / `End` |

網址列的 `#12` 會直接跳到第 12 頁，換頁時也會同步 —— 中斷後可以接回原處。
用瀏覽器「列印 → 存成 PDF」會一頁一張輸出，可以當備援檔。

重新產生：

```bash
uv run python talk/build_slides.py          # 產生 SVG 與 slides.html
uv run python talk/build_slides.py --list   # 只印出播放順序
```

**版面型投影片（23 張）由 `build_slides.py` 產生，不要手改** ——
版面規則（邊界、字級、色票、logo 安全區）只寫在那支檔案上方，
手改單張的下場是每張都差一點點，投影出來看得很清楚。
`talk/assets/` 裡那六張**手繪示意圖**（工具地圖、金字塔、架構圖⋯⋯）維持手繪，
只被排進播放清單。

> 第 6 頁（`studio.svg`）貼的是 GEAP 主控台的實際截圖
> `talk/assets/geap-overview.png` —— 那是**手動放進來的素材**，不是產生的。
> 截圖以 base64 內嵌進 SVG，所以 `slides.html` 仍然是離線可用的單一檔案。
> 要換圖就換那個 PNG，標註位置寫在 `build_slides.py` 對應的
> `layout_screenshot(...)` 呼叫裡，用的是**截圖自己的像素座標**（不必換算縮放）。

---

### 3-1　§6 總覽儀表板

notebook 最後一節把前面的結果畫成一頁 BI 報告：四個看板數字、規則層小倍數圖、
評審層對比、**配對比較的信賴區間**、成本組成，以及場景 B 的負評歸屬。
跑完會存成 `evaluation_overview.png`（工作目錄，已列入 `.gitignore`），
可以直接貼進報告或簡報。

**這一節不產生任何新數字**，全部來自前面已經算過的物件。若它和上面的表格
對不上，那是 bug —— `test_dashboard_numbers_match_the_tables` 就是在守這件事。

成本那一格是**環圈圖**，拆成生成／產生 rubric／逐條檢查三段 ——
分開之後才看得出來貴的是「改考卷」，也就是加大評測集時會線性膨脹的那一段。
整頁只有這一格用圓餅類的圖：它只擅長「一個整體被拆成幾塊」，
其他格都是跨版本比較，換成圓餅就失去比較能力。環圈右邊一定附上金額與佔比，
不要求任何人用眼睛去比扇形角度。

> ⚠️ **Colab 預設環境沒有中文字型**，圖表標籤會自動改用英文（數值不受影響），
> 不會出現豆腐方塊。要中文標籤，在**有網路時**先執行
> `!apt-get install -y fonts-noto-cjk` 再重啟 runtime ——
> 但這需要連網，與「零網路重播」的前提衝突，**演講當天不要做這件事**。
> 本機（macOS）有系統中文字型，所以在本機重跑會是中文。

---

### 4　選用：BigQuery（場景 B）

預設關閉。要真的把評論洞察寫進 BigQuery：

```python
USE_BIGQUERY = True   # poc/src/config.py
```

需要 `bigquery.dataEditor` 權限。**離線重播不涵蓋 BigQuery 呼叫**，
所以現場若無網路請保持關閉 —— notebook 仍會展示 schema 與 SQL。

---

### 5　疑難排解

| 症狀 | 原因與處理 |
|---|---|
| 呼叫全部 404 | `LOCATION` 不是 `global`。跑 `check_env.py` 確認 |
| `Reauthentication failed` | 重跑 `gcloud auth application-default login` |
| 重播時 `KeyError: 離線重播找不到對應輸出` | prompt 或模型在錄製後被改過。回到 §2 重錄 |
| `OFFLINE_MODE=True 但沒有可用的 fixtures` | `poc/data/demo_outputs.json` 不存在。回到 §2 |
| 成本顯示為 0 | 該模型不在 `config.PRICING` 裡。`check_env.py` 會抓到 |
| 測試在 repo 留下 `demo_outputs.json` | 已修掉；若仍發生，該檔是假資料，直接刪除 |
| 對比表沒有呈現階梯 | **不要美化數字**。代表 prompt 演進設計有問題，回頭改 prompt |

---

## 這套系統實際用到哪些 GCP 服務

**誠實地說：只有兩個。** 其餘都是正式上線才需要，今天沒做。
`talk/assets/gcp-architecture.svg` 就是在講這件事。

| 服務 | 用途 | 狀態 |
|---|---|---|
| **GEAP** | Gemini 生成（flash）＋ 評審（2.5-pro）、structured output | ✅ 實際使用 |
| **BigQuery** | 場景 B 的評論洞察落地、分區與叢集 | ✅ 需開 `USE_BIGQUERY` |
| Cloud Run | 把 pipeline 包成服務供 PIM 後台呼叫 | ⬜ 今天用 notebook 代替 |
| Batch Prediction | 全站商品初次匯入，約 5 折 | ⬜ 成本段有講，沒有跑 |
| Cloud Storage | 商品圖、原始匯出檔 | ⬜ |
| Cloud Scheduler / Logging / Monitoring | 定期重跑評測、留存紀錄、成本告警 | ⬜ |
| Secret Manager / IAM / VPC-SC | 金鑰、權限、資料落地 | ⬜ |

這是刻意的取捨：**先把「怎麼知道它變好了」解決掉，再談怎麼部署。**
順序反過來的專案，通常上線後才發現沒人能判斷好壞。

> ⚠️ **`LOCATION` 必須是 `"global"`。** 實測 `asia-east1` 上沒有任何 Gemini
> publisher model，所有呼叫都會 404。compute 資源在 asia-east1，不代表
> Gemini 在那裡可用 —— 這是很容易踩的坑，`check_env.py` 會抓到。

---

## 設計決策

**notebook 是產物，不是手寫的**
程式碼只存在於 `src/`，有測試覆蓋；notebook 由 `build_notebook.py` 產生。
手寫 notebook 一定會跟測過的程式碼分岔，而分岔會在台上才被發現。

**兩份 notebook，同一份來源**
`audience` 是乾淨教材，`speaker` 額外插入時間點與要說的話。
舞台指示放進帶回家的教材只會讓人困惑，所以分開產生。

**每版 prompt 只加一件事**

以下全部是**實測數字**（50 筆商品 × 4 版，notebook 與 `run_eval.py` 共用同一份資料）。

規則層（免費、確定性）：

| 指標 | v0 | v1 | v2 | v3 | 實測歸因 |
|---|---|---|---|---|---|
| 標題長度合規 | 74% | **100%** | 100% | 100% | v1 |
| 規格完整覆蓋 | 82% | **98%** | 100% | 100% | v1 |
| 法規禁詞 0 命中 | 80% | **98%** | 100% | 100% | v1 |
| 賣點長度 ※ | — | — | — | 98% | v3 |
| SEO描述長度 ※ | — | — | — | 100% | v3 |
| 可機器讀取 | 0% | 0% | 0% | **100%** | v3 |

※ 依賴 parser，非結構化版本量不到（見下方「測不到就管不了」）。

評審層（rubric 通過率，配對比較 + bootstrap 95% CI）：

| 比較 | 平均差 | 95% CI | 結論 |
|---|---|---|---|
| v1 − v0 | +4.86 pp | [−0.85, +10.58] | 跨過 0，**不能宣稱** |
| v2 − v1 | **+8.86 pp** | [+4.57, +13.15] | **有差異** |
| v3 − v2 | −1.43 pp | [−5.15, +2.57] | 跨過 0，**不能宣稱** |

**所以每一版的貢獻是分開的，而且各自有證據：**

- **v1 —— 格式與合規。** 規則層三欄大幅改善（74→100、82→98、80→98）。
  但語意品質沒有統計上的改善，這合理：v1 加的是字數與必含規格，不是語氣指引。
- **v2 —— 語意品質。** 唯一在 rubric 上統計成立的改善（+8.86pp）。
  加的是品牌語調 few-shot，而 rubric 量的正是語調與賣點覆蓋。
- **v3 —— 可機器讀取。** 0% → 100%，不需要統計檢定。
  **v3 沒有讓文案變好（−1.43pp 在雜訊內），是讓文案變得可用。**

> ⚠️ **解析度不等於顯著性。** 50 筆 × 7 條 = 350 次檢查，單次翻轉 0.29pp，
> 但配對比較的 95% 區間寬達 ±5pp —— 差了一個數量級。
> 只看「翻一次等於多少」會嚴重高估精度，那是最容易把雜訊講成訊號的地方。

**LLM-as-judge 用二元 rubric，不用 1–5 分**
Likert 分數擠在 3–4 分、不可重現、換模型就平移、而且「3.8 分」無法行動。
二元判準（「文案是否寫出 30mg？」）明確、可累積、能直接對應修改動作。
GEAP 的 Gen AI Evaluation Service 的 adaptive rubrics 就是這個思路
（官方形容為「像單元測試」）。

rubric **只從商品資料生成，每個商品一組，v0～v3 共用** ——
若讓評審看著文案即興出題，等於每個版本考不同的考卷。

rubric 生成時必須知道**通路字數預算**，否則會產生「說明為何隨餐吃更好」
這種 30 字賣點塞不下的判準，讓冗長文案得高分、精簡文案被扣分。
這個錯誤實際發生過，修正前 v0 拿 100%、v3 只有 57%。

**禁詞用真實法規**
食安法 §28 宣稱醫療效能罰 NT$60 萬–500 萬。這讓評測從「工程潔癖」
變成「不做會收罰單」。
實測 naive prompt 有 20% 踩雷，加了 prompt 約束降到 2% —— 但 2% 不是 0%。

**成本不寫死數字**
公式放投影片、常數放 `config.py`、實際金額由執行結果印出。

**離線重播**

| 設定 | 何時用 | 行為 |
|---|---|---|
| `RECORD_FIXTURES=True` | 有網路時先跑一次 | 正常呼叫並錄下所有輸出 |
| `OFFLINE_MODE=True` | 之後任何時候 | 零網路重播，且更快 |

重播時所有 cell 一樣執行、表格一樣當場算出來，只有 API 呼叫換成查表。
`ReplayClient` 找不到對應輸出會明確報錯，不會靜默給出過期資料。

---

## 樣本數的誠實聲明

50 筆 × 7 條 rubric = 350 次檢查，單次翻轉 0.29 個百分點。
**但那是解析度，不是顯著性。**

實際做配對比較（同一批商品、bootstrap 95% CI）後，區間寬達 ±5pp ——
比解析度大了一個數量級。只看「翻一次等於多少」會嚴重高估精度。

結果是：四個版本之間，**只有 v1→v2 在語意品質上的改善是統計成立的**。
v0→v1 和 v2→v3 的區間都跨過 0，在這個樣本量下分不出差別。

「分不出差別」不等於「一樣好」，是**還沒有證據說誰比較好**。
要下更細的結論就要加大評測集（`run_eval.py` 支援到 200 筆）。

**一張每格都完美遞增的表，通常代表有人在調數字。**

上面所有數字都在 `poc/data/eval_results.json` 裡。要重新產生：

```bash
uv run python poc/run_eval.py --replay --limit 50   # 零網路、零成本
```

`--replay` 讀 `poc/data/demo_outputs.json` 裡錄好的真實輸出，**不打 API**，
所以算出來的就是錄製那一輪的數字，跟台上 demo 會跑出來的完全一致。
（要真的重打 API 就拿掉 `--replay` —— 那需要網路，約 3.6 分鐘、US$1.50。）

> ⚠️ `eval_results.json` 是**輸出，不是真相**。它可能比投影片舊。
> `poc/tests/test_slide_numbers.py` 會比對 `results.svg` 上每一格與這個檔案，
> 對不上就讓測試紅掉 —— 手繪投影片和跑出來的數字之間，只有這條線綁著。

---

## 上場前必做

完整步驟見上方「操作流程」的 §2 錄製 fixtures 與 §3 演講當天；
演講本身的檢查清單見 `talk/script.md` 附錄 B。

一句話版本：**更新價格 → 錄製 → 拔網路驗證 → 當天開講者版且 `OFFLINE_MODE = True`。**

---

## 免責

`poc/data/banned_terms.json` 是依主管機關公開認定準則整理的**示範用簡化版**，
不構成法律意見。實際商用前應由法務或法規顧問審閱，並以主管機關最新公告為準。
