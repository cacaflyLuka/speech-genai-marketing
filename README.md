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
  assets/
    tool-map.svg             承：GCP 三層工具地圖
    eval-pyramid.svg         轉 2：三層評測金字塔
    cost-model.svg           合：成本公式與降本四招
    gcp-architecture.svg     demo 用到的 GCP vs 正式上線需要的

poc/
  retail_genai_poc.ipynb          ★ 聽眾版 —— 乾淨教材，會後發給大家
  retail_genai_poc_speaker.ipynb  ★ 講者版 —— 同樣內容 + 舞台指示
  build_notebook.py               從 src/ + data/ 產生上面兩份
  check_env.py                    上場前環境健檢
  data/
    products.json          12 筆假商品（food / cosmetic / general 三類）
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
  tests/                   42 項，全部離線、不呼叫 API、不花錢
```

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

```bash
gcloud config set project cacafly-poc
```

啟用需要的 API：

```bash
gcloud services enable aiplatform.googleapis.com bigquery.googleapis.com --project=cacafly-poc
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

### 1　日常開發循環

改任何程式碼都走這兩步，**不要手改 notebook**：

```bash
make all
```

等同於：

```bash
uv run python poc/build_notebook.py && uv run pytest
```

42 項測試全部離線、不呼叫 API、不花錢。全綠才算改完。

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

- 判斷模型 `gemini-2.5-pro` 每次約 15 秒，12 個商品完整跑完約數分鐘
- 跑完後執行 §6，會下載 `demo_outputs.json`

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
§6 應印出「本次共命中 N 筆錄製輸出，全程未連網」。

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
- [ ] 開場前先 Run all 一次，讓所有輸出都在畫面上
- [ ] Colab 字級調大（`Cmd/Ctrl` + `+`），確認投影後對比表看得清楚
- [ ] 關閉通知與其他分頁
- [ ] 預錄影片存在本機（筆電當機時的最後備援）

因為是離線重播，demo 時要重跑哪一格就重跑，秒回，不用等網路。

會後把 **`retail_genai_poc.ipynb`（聽眾版）** 發給聽眾。

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
| **Vertex AI** | Gemini 生成（flash）＋ 評審（2.5-pro）、structured output | ✅ 實際使用 |
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

| 版本 | 加了什麼 | 實測修好什麼 |
|---|---|---|
| v0 | — | 基準線：12 個商品有 3 個出現法規禁詞、4 個標題超長 |
| v1 | 角色／受眾／字數／必含規格 | 長度、規格覆蓋、禁詞全部歸零 |
| v2 | 法規禁詞 + 品牌語調 few-shot | rubric 通過率 74%→95%，critical 違反 4→0 |
| v3 | `responseSchema` | 可機器讀取 0%→100% |

**LLM-as-judge 用二元 rubric，不用 1–5 分**
Likert 分數擠在 3–4 分、不可重現、換模型就平移、而且「3.8 分」無法行動。
二元判準（「文案是否寫出 30mg？」）明確、可累積、能直接對應修改動作。
Vertex AI Gen AI Evaluation Service 的 adaptive rubrics 就是這個思路
（官方形容為「像單元測試」）。

rubric **只從商品資料生成，每個商品一組，v0～v3 共用** ——
若讓評審看著文案即興出題，等於每個版本考不同的考卷。

rubric 生成時必須知道**通路字數預算**，否則會產生「說明為何隨餐吃更好」
這種 30 字賣點塞不下的判準，讓冗長文案得高分、精簡文案被扣分。
這個錯誤實際發生過，修正前 v0 拿 100%、v3 只有 57%。

**禁詞用真實法規**
食安法 §28 宣稱醫療效能罰 NT$60 萬–500 萬。這讓評測從「工程潔癖」
變成「不做會收罰單」。

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

12 個商品 × 7 條 rubric = 84 次檢查。**翻轉一次就是 1.2 個百分點。**
所以兩三個百分點的差距是雜訊，不能宣稱是改善。

實測 v3 的 rubric 通過率略低於 v2，但差距在誤差內 —— 這是真實的工程取捨
（結構化輸出犧牲一點文字彈性），不是缺陷。v3 真正的勝負手是
「可機器讀取」那一欄從 0% 變成 100%。

**一張每格都完美遞增的表，通常代表有人在調數字。**

---

## 上場前必做

完整步驟見上方「操作流程」的 §2 錄製 fixtures 與 §3 演講當天；
演講本身的檢查清單見 `talk/script.md` 附錄 B。

一句話版本：**更新價格 → 錄製 → 拔網路驗證 → 當天開講者版且 `OFFLINE_MODE = True`。**

---

## 免責

`poc/data/banned_terms.json` 是依主管機關公開認定準則整理的**示範用簡化版**，
不構成法律意見。實際商用前應由法務或法規顧問審閱，並以主管機關最新公告為準。
