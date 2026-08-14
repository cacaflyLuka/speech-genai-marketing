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

---

# 地圖

```
poc/src/          唯一的程式碼來源，有測試覆蓋
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

# 投影片 SVG

`talk/assets/*.svg` 是手刻的，不是工具產生的。約定：

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

- `poc/run_eval.py` 的 module docstring 還寫著「notebook（12 筆）」與「200 筆」的分工，
  但 demo 與評測早已統一成同一份 50 筆資料（commit 82fbd2d）。改到那支檔案時順手更新。
