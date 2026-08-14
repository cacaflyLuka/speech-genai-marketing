---
name: speech-genai-marketing
description: 這個 repo（2026-08-21 新創加速器演講 + 零售文案 POC）的工作準則。動到 poc/src/、poc/data/、talk/script.md、talk/assets/*.svg、README.md，或被問到評測數字、prompt 版本、成本、離線重播、投影片時，先讀這份。
---

# 這個 repo 在做什麼

一場 45 分鐘演講（2026-08-21，新創加速器）＋ 撐住它的 POC。

**全場只有一個主張**：生成式 AI 的難處不在叫模型，而在你怎麼知道它有沒有變好。

POC 是一條零售商品文案 pipeline：Gemini 生成 → 三層評測（規則層 / LLM judge / 人工）→ 成本外推。
四個 prompt 版本 v0→v3，每版只加一件事，然後用實測數字證明各自加了什麼。

演講當天在 Colab 跑 notebook，**全程離線重播**事先錄好的真實 API 輸出。

---

# 鐵律

違反這幾條會直接毀掉台上的 demo 或這場演講的可信度。

**1　不要手改 notebook。**
`poc/*.ipynb` 是 `build_notebook.py` 從 `poc/src/` + `poc/data/` 產生的**產物**。
手改一定會跟測過的程式碼分岔，而分岔會在台上才被發現。
改完 src 一律 `make all`（＝重新產生 notebook + 跑 48 項離線測試）。

**2　不要美化數字。**
所有百分比、成本、信賴區間都必須來自實際跑出來的 `poc/data/eval_results.json`
或 `poc/data/demo_outputs.json`。
不准在 README、講稿、SVG 裡手寫一個「看起來合理」的數字。
一張每格都完美遞增的表，通常代表有人在調數字 —— 這句話寫在 README 裡，
所以自己更不能犯。**對比表沒呈現階梯，是 prompt 設計有問題，回頭改 prompt，不是改數字。**

**3　`config.LOCATION` 必須是 `"global"`。**
實測 `asia-east1` 上沒有任何 Gemini publisher model，所有呼叫都會 404。
compute 在 asia-east1 不代表 Gemini 在那裡可用。

**4　改了 prompt 或模型名 → 錄好的 fixtures 全部失效，必須重錄。**
`poc/data/demo_outputs.json` 的 key 含 prompt 與模型名。
改 `src/prompts.py`、`src/judge.py` 的 prompt、或 `config.GEN_MODEL`/`JUDGE_MODEL`
之後，離線重播會直接 `KeyError`。完整重錄流程見 README §2（需要網路，約 3.6 分鐘、US$1.50）。
改 `rules.py`、`report.py`、價格常數則不影響 fixtures。

**5　fixtures 必須是對真實 API 錄的。**
測試用的假 client 會產生**結構完全正確但數字捏造**的同名檔案。
`check_env.py` 靠偵測 `模擬判準`、`模擬依據` 這類字串抓假資料。
`.gitignore` 擋掉根目錄與 `poc/` 下的 `demo_outputs.json`，只有 `poc/data/demo_outputs.json` 被追蹤。
（工作目錄現在就有一份 gitignored 的根目錄 `demo_outputs.json` —— 那不是真實來源。）

**6　`OFFLINE_MODE` 與 `RECORD_FIXTURES` 不能同時為 True。**
演講當天必須 `OFFLINE_MODE = True`。這是 README 標記「最容易忘」的一項。

**7　產品名用 GEAP，程式碼裡的舊名不要動。**
Vertex AI 於 2026 年 4 月改名 Gemini Enterprise Agent Platform（GEAP），
但**端點與 SDK 介面完全沒改**。所以：文件／講稿／投影片一律 GEAP；
`genai.Client(vertexai=True)`、`USE_VERTEX`、`aiplatform.googleapis.com`、
pricing 網址的 `vertex-ai` 路徑**一律保留**。跟著改只會讓程式碼跟 SDK 對不起來。

**8　識別資訊不寫死在 repo 裡。**
GCP 專案、BigQuery 位置、講者姓名、場次名稱都走環境變數
（`GCP_PROJECT_ID`、`GCP_LOCATION`、`BQ_DATASET`、`BQ_TABLE`、`BQ_LOCATION`、
`SPEAKER_NAME`、`EVENT_NAME`、`TALK_DATE`），notebook 則由
`build_notebook.py` 在建構時注入成字面值（因為 Colab 上沒有你的 shell 環境）。
**不要為了方便把真實專案 ID 或人名寫回原始碼。**
要新增這類參數就加進 `build_notebook.py` 的 `CONFIG_PARAMS` / `BYLINE_PARAMS`，
兩者都會自動長出對應的 CLI 參數；`CONFIG_PARAMS` 的常數找不到時會直接拋錯，
不會靜默不套用。

---

# 地圖

```
poc/src/          唯一的程式碼來源，有測試覆蓋
  dashboard.py    §6 總覽儀表板（matplotlib）
  config.py       模型、價格、旗標 —— 環境相關設定只改這裡
  prompts.py      v0 → v3，每版只加一件事
  generation.py   Gemini 呼叫 + 用量記錄 + 離線重播（ReplayClient）
  rules.py        評測第一層：規則，本機、免費、毫秒級
  judge.py        評測第二層：二元 rubric（不是 1–5 分）
  report.py       對比表 + 統計顯著性
  insights.py     場景 B：評論洞察 + BigQuery（預設關閉）
  costs.py        成本外推與降本槓桿
poc/data/         eval_products.json 是 200 筆評測集，demo 與評測都取前 50 筆
poc/run_eval.py   離線跑完整評測，產出 eval_results.json
poc/check_env.py  上場前環境健檢（會呼叫真實 API）
talk/script.md    大綱 + 逐頁講稿 + demo 腳本 + QA + 檢查清單
talk/assets/      六張手刻 SVG 投影片
```

指令走 `make`（`make help` 看清單）：`make all` = build + test，`make lint`，`make check`（要網路）。
Python 環境用 uv，所有指令都是 `uv run ...`，不需要手動 activate。

---

# 這個專案的立場（改東西前先理解，不要「順手優化」掉）

- **二元 rubric，不用 1–5 分。** Likert 擠在 3–4 分、換模型就平移、「3.8 分」無法行動。
- **rubric 只從商品資料生成，v0～v3 共用同一份考卷。** 讓評審看著文案即興出題，
  等於每個版本考不同的卷子。rubric 生成時必須知道通路字數預算，否則會出現
  「30 字賣點塞不下」的判準 —— 這個錯誤實際發生過，修正前 v0 拿 100%、v3 只有 57%。
- **生成用 flash、評審用 2.5-pro，刻意不同模型**，降低 self-preference bias。不要為了省時間改成同一個。
- **禁詞用真實法規**（食安法 §28，罰 NT$60 萬–500 萬），不是工程潔癖。
- **成本不寫死**：公式放投影片、常數放 config、金額由執行結果印出。
- **兩份 notebook 同一份來源**：audience 是乾淨教材，speaker 多了舞台指示。

---

# 數字的說法要精確

README 與講稿在統計上是刻意保守的，改述時不要放寬：

- 50 筆 × 7 條 = 350 次檢查，單次翻轉 0.29pp —— **那是解析度，不是顯著性**。
  配對比較的 95% CI 寬達 ±5pp，差一個數量級。
- 四個版本裡，**只有 v1→v2 在 rubric 上統計成立**（+8.86pp，CI [+4.57, +13.15]）。
  v0→v1 與 v2→v3 的區間都跨過 0。
- 「分不出差別」**不等於**「一樣好」，是還沒有證據說誰比較好。
- v3 沒有讓文案變好（−1.43pp 在雜訊內），是讓文案**變得可用**（可機器讀取 0% → 100%）。

---

# §6 儀表板（`poc/src/dashboard.py`）

- **不重算任何數字。** 全部來自前面已經算好的物件。圖上的數字和上面的表格
  對不上就是 bug —— `test_dashboard_numbers_match_the_tables` 守著這條。
- **v0→v3 用同一個藍色由淺到深**，不是四個類別色：版本是有序的。
- **不用雙 Y 軸**，兩個單位不同的量就分兩張圖。
- 顏色不獨自承載意義：顯著與否旁邊一定有文字結論；對比偏低的橘色一律標數值。
- 色票沿用投影片（藍 `#1B6FB8`、橘 `#EF7622`、綠 `#166534`）。
- **中文字型**：matplotlib 預設字型沒有中文字。`find_cjk_font()` 找不到就整頁
  改用英文標籤，**不要改成自動安裝字型** —— 安裝要連網，會破壞零網路的前提。
- 金額字串裡的 `$` 必須跳脫成 `\$`，否則 matplotlib 會當成數學式渲染。
- 改完一定要**實際 render 出來看**，理由同下面的 SVG。

# 投影片與播放器

`talk/assets/` 底下有兩種檔案，**改之前先確認是哪一種**：

- **22 張由 `talk/build_slides.py` 產生**，檔頭有「由 talk/build_slides.py 產生，
  不要手改」的註解。要改就改那支檔案裡的資料或版型，再重跑 `build_slides.py`。
  手改單張會在下次 build 時被蓋掉。
- **6 張手繪示意圖**（`tool-map` / `eval-pyramid` / `results` / `significance` /
  `cost-model` / `gcp-architecture`）維持手寫 SVG，只被排進播放清單。

第 6 頁貼的是 GEAP 主控台截圖 `talk/assets/geap-overview.png`（手動放進來的素材）。
截圖**以 base64 內嵌**，不要改成外部連結 —— 理由同下面的離線原則。
標註座標用的是**截圖自己的像素座標**，換圖時直接在新圖上量即可，縮放由
`layout_screenshot()` 換算。

`talk/slides.html` 是產物：單一自足檔案、SVG 全部內嵌、不引用任何外部資源，
所以離線可用（`F` 全螢幕、`O` 總覽、方向鍵換頁）。
**不要為了方便改成從外部載入 SVG 或 CDN**，那會讓會場沒網路時開天窗。

`poc/tests/test_slides.py` 守著：XML 合法、畫布尺寸一致、座標沒有超出
1280×720、播放器包含每一頁且沒有外部引用。

投影片的視覺約定：

- viewBox `0 0 1280 720`，內容左邊界 x=76，右下角留給主辦方 logo
- 字型堆疊 `'PingFang TC','Noto Sans TC','Microsoft JhengHei','Hiragino Sans TC'`
- 圖例語意：**實線＝今天 demo 真的跑過，虛線＝正式上線才需要**。改線條樣式前先確認語意
- 投影片放結構與數字，論證用講的 —— 不要把講稿內容搬上投影片

**改完一定要在瀏覽器實際渲染確認**，不能只看 XML。
手刻 SVG 最常見的問題是文字與線條重疊，看原始碼看不出來。
做法：把 SVG 複製到暫存目錄、`python3 -m http.server`、用瀏覽器開起來截圖檢查。
（曾經就有一條箭頭穿過分區標題，只有截圖才看得出來。）

---

# 寫作與 commit 約定

- 全部繁體中文、台灣用語。語氣直接、不客套、不推銷。
- 文件裡的警告用 `⚠️`，並說明**為什麼**，不只說「不要這樣做」。
- commit 訊息：conventional commits + 繁中描述，例如
  `fix(assets): 架構圖 PIM→Vertex AI 箭頭改走左側，不再壓到第二排標題`
- 直接 commit 到 `main`（單人 repo，沒有 PR 流程）。

---

# 已知待處理

（目前沒有。）
