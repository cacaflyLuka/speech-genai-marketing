# Google Cloud & Generative AI Applications — 演講與 POC

2026-08-21｜新創加速器｜45 分鐘（30 講 + 12 demo + 3 QA）

**主題**：生成式 AI 的難處不在叫模型，而在你怎麼知道它有沒有變好。

---

## 目錄

```
talk/
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
  tests/                   33 項，全部離線、不花錢
```

---

## 快速開始

```bash
python3 poc/check_env.py
```

確認 config 裡的模型、region、權限真的可用。**換專案或換模型後一定要重跑。**

```bash
python3 poc/tests/test_rules.py && python3 poc/tests/test_insights.py && python3 poc/tests/test_notebook_offline.py
```

三組測試都不需要 GCP 認證、不花錢。改完 `src/` 後重新產生 notebook：

```bash
python3 poc/build_notebook.py
```

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

完整清單見 `talk/script.md` 附錄 B。最關鍵的五項：

1. `python3 poc/check_env.py` 全綠
2. 更新 `config.PRICING`，把 `PRICE_LAST_CHECKED` 改成當天日期
3. 錄製：`RECORD_FIXTURES=True` 跑一次 → 下載 `demo_outputs.json`
   → 放進 `poc/data/` → 重新 build
4. **拔網路驗證**：`OFFLINE_MODE=True`，關掉 wifi 後 Run all
5. 確認當天用的是**講者版** notebook，且 `OFFLINE_MODE = True`

---

## 免責

`poc/data/banned_terms.json` 是依主管機關公開認定準則整理的**示範用簡化版**，
不構成法律意見。實際商用前應由法務或法規顧問審閱，並以主管機關最新公告為準。
