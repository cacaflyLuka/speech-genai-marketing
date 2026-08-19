---
id: topic
type: topic
title: retail-genai-eval
description: 用零售文案 pipeline 講清楚生成式 AI 怎麼證明自己變好了
status: active
created: 2026-08-18
updated: 2026-08-18
duration-minutes: 45
event-type: intro
audience: 新創加速器場,創辦人／PM 與工程師各半,約 40–60 人
audience-level: mixed
speaker-background: 本場素材全為講者第一手實作(零售文案 POC:生成、三層評測、成本外推)
language: zh-TW
slide-style: 淺色資訊密集、單色強調
outputs: [html, pdf]
sections: [section-01, section-02, section-03, section-04, section-05, section-06, section-07]
demo: planned
---

# 從 Demo 到上線:零售生成式 AI 的 Prompt 與評測 主軸設計

## 主軸說明

**主題**:從 Demo 到上線 — 零售生成式 AI 的 Prompt 與評測
**副標**:Gemini × GEAP 實作

核心訊息(聽眾走出場只要記得這一件事):

> **生成式 AI 的難處不在叫模型,而在你怎麼知道它有沒有變好。**

這句話把四塊原本平行的題材串成一條因果鏈 —— 探索(GEAP Studio)→ 整合(API 選型)
→ 規格化(Prompt)→ 驗收(評測)。全場只有這一個主張,每段結束前回扣一次。

## 候選方案記錄

本場為**既有演講的重製**(對照組見 repo 根目錄的 `talk/`),主軸與時長沿用,
真正的選擇落在**段落切分方式**。訪談時提出三組:

| 方案 | 切法 | 未採用/採用的理由 |
|---|---|---|
| **A(採用)** | 依技術主題切,把原版 12 分鐘的「轉」拆成 Prompt / 評測 / build-vs-buy 三段 | 敘事順序與對照組一致,差異乾淨地收斂在「一段一目的」原則怎麼重新分配頁面與時間 —— 這正是這次要比對的東西 |
| B | 依聽眾心裡依序冒出的四個問題切(誰對?怎麼定義好?誰來判?多少錢?) | 敘事最順,但與對照組差太遠,比對會混入敘事變因;四個問句式標題也是 AI 感的高風險來源 |
| C | 依導入時間軸切(探索→整合→規格化→驗收→上線) | 對創辦人最好懂,但「你怎麼知道它變好了」這個主張要到第四段才上場,前 20 分鐘沒有軸心 |

## 聽眾輪廓

- **範圍規模**:新創加速器場,約 40–60 人;創辦人／PM 與工程師大約各半
- **技術能力**:mixed —— 不預設任何人有 ML 背景,但台下一定有工程師會抓細節
- **已知**:知道 LLM 會寫文案、多半玩過 ChatGPT;知道 GCP 是雲端供應商
- **未知**:不知道 GEAP(Vertex AI 2026-04 改名)與 Gemini API 的選型差異;
  不知道「評測」是可以工程化的東西;不知道評測本身會產生可觀成本;
  不知道台灣廣告法規禁詞會直接變成上線風險
- **兩種聽眾各自要帶走的**:
  - 創辦人／PM — 我怎麼知道這東西能不能上線、會不會出事;要花多少錢、多久、誰負責
  - 工程師 — 評測迴圈怎麼建、structured output 怎麼用、judge 準不準

## 講者先備知識

素材全部是講者自己跑出來的:四版 prompt、三層評測、200 筆評測集(demo 取前 50 筆)、
成本外推、離線重播 fixtures。強項是「有真實數字可以講」,需要事前補強的是
**GEAP 改名後的商務條款細節**(資料落地、計費歸屬)—— 台上被問到不確定的就說要查,不編。

**刻意避開**:模型內部原理、fine-tuning、RAG 架構深潛 —— 這場不談。

## 大綱與段落規劃

| Section | 名稱 | 目的 | 分鐘 | 頁數(預估) |
|---|---|---|---|---|
| section-01 | open-vote | 用現場舉手投票製造分歧,把「你怎麼定義好」丟出來並點題 | 4 | 4 |
| section-02 | tool-map | 給一張依**階段**(而非產品線)劃分的 GCP 工具地圖,解決選型焦慮 | 7 | 5 |
| section-03 | prompt-as-spec | 用 v0→v3 四版演進說明 prompt 是規格書,每版只加一件事所以改善可歸因 | 6 | 6 |
| section-04 | eval-stack | 三層評測(規則/LLM judge/人工)與實測結果,含法規禁詞這張全場最重的頁 | 7 | 8 |
| section-05 | build-vs-buy | 給一條可帶走的判準:會不會出現在你的產品定價頁上;並說明方法論可遷移 | 3 | 2 |
| section-06 | cost-path | 成本公式、降本槓桿、評測自身的成本,收在 90 天導入路徑與收尾 | 5 | 5 |
| section-07 | live-demo | 實機跑一次 pipeline:生成 → 評測 → 版本對比表,聽眾帶走 notebook | 10 | 2 |

**實際頁數(2026-08-18 `/section-impl` 完成)**:4 + 5 + 6 + 8 + 2 + 5 + 2 = **32 頁**;section-04 因誤差棒圖需要整頁而由 7 頁拆成 8 頁,理由記在該段設計文件。build 產物在 `talk/dist/`。

**時間帳**:7 段合計 **42 分鐘**,總時長 45 分鐘,留 3 分鐘(6.7%)給 QA 與段落銜接。

> 2026-08-18 `/section-design` 調整:section-06 排下來裝不下 4 頁(90 天路徑與收尾不能擠同一頁),
> 改為 5 分鐘 5 頁,多出的 1 分鐘從 section-07 挪用(11 → 10 分;離線重播每個 cell 秒回,10 分鐘足夠)。總和不變。

## 投影片風格

視覺風格關鍵字:**淺色、資訊密集、單色強調、無裝飾**。色票直接沿用對照組的
`talk/build_slides.py` 與 `poc/src/dashboard.py`,兩套投影片與儀表板同一組顏色。

| token | 值 | 用途 |
|---|---|---|
| `--c-bg` | `#ffffff` | 頁面背景 |
| `--c-text` | `#1a1a1a` | 正文 |
| `--c-muted` | `#6a6a6a` | 來源標註、次要文字、頁碼 |
| `--c-primary` | `#1b6fb8` | 標題、重點框線、v0→v3 的序列色基底 |
| `--c-accent` | `#ef7622` | 強調,一頁最多一處 |
| `--c-surface` | `#f5f5f5` | 卡片與表頭底色 |
| `--c-ok` | `#166534` | 通過／統計成立(語意固定,圖形與表格共用) |
| `--c-warn` | `#b3261e` | 違規／失敗(法規禁詞、罰則) |
| `--c-hair` | `#d8d8d8` | 分隔線、卡片框線 |
| `--f-body` | PingFang TC → Noto Sans TC → Microsoft JhengHei → Hiragino Sans TC | 正文字體 |
| `--f-mono` | SF Mono → Menlo → Consolas → Noto Sans Mono CJK TC | prompt / JSON / schema |

改色只改 `talk/src/theme.css` 的 tokens 區,任何頁面與 SVG 都不寫死色值。
SVG 圖形沿用對照組的圖例語意:**實線 = 今天 demo 真的跑過,虛線 = 正式上線才需要**。

## 演講風格

- **論證型為主、示範型收尾**:前六段是一條論證鏈,第七段用實機演示兌現前面的主張
- **語氣**:直接、不客套、不推銷;數字保守,不確定就說要查
- **互動**:開場舉手投票是全場唯一一次互動,務必真的等聽眾舉手(那 30 秒的沉默最值錢)
- **備註密度**:每頁 1–5 行提醒,不寫逐字稿(對照組 `talk/script.md` 是逐字稿,這是兩套流程最大的差異之一)
- **數字紀律**:所有百分比與金額只來自 `poc/data/eval_results.json` 與 `demo_outputs.json`;
  價格數字只唸 demo 當場印出來的,不唸投影片上的

## Demo 規劃

- **目的**:讓聽眾看到前六段講的東西真的跑得動,並帶走一份可以改的 Colab notebook
- **形式**:**沿用 repo 現有的 `poc/`**(uv + python + notebook),demo2 不另建 `demo/` 資料夾。
  演講當天在 Colab 開 `poc/retail_genai_poc_speaker.ipynb`,`OFFLINE_MODE = True` 全程重播事先錄好的真實 API 輸出
- **掛在**:section-07-live-demo(11 分鐘),投影片只有 2 頁(切換頁與帶走頁),其餘時間在 notebook 裡
- **風險**:`OFFLINE_MODE` 與 `RECORD_FIXTURES` 不能同時為 True;改過 prompt 或模型名就要重錄 fixtures
