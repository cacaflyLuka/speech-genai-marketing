---
id: section-07
type: section
title: live-demo
description: 實機跑一次 pipeline,把前六段的主張兌現成看得到的輸出
status: done
created: 2026-08-18
updated: 2026-08-18
parent-topic: topic
order: 7
est-minutes: 10
slides: 2
diagrams: [diagram-07-1]
depends-on: [section-03, section-04]
---

# Section 07:實機演示

## 段落定位

**存在理由**:前六段全部是主張與數字。這段讓聽眾**親眼看到那些數字是跑出來的**,
而不是投影片上寫的。它同時是主軸的最終兌現:「你怎麼知道它有沒有變好?」——
答案是畫面上那張當場算出來的對比表。並讓聽眾帶走一份可以改的 notebook。

**討論方向**:示範型。投影片只有兩頁,其餘 10 分鐘都在 notebook 裡。

## 內容要點

**沿用 repo 現有的 `poc/`,demo2 不另建 `demo/` 資料夾。**
演講當天在 Colab 開 `poc/retail_genai_poc_speaker.ipynb`。

1. **離線重播**(必須主動說明,不要道歉):
   會場 wifi 不可靠,現場打 API 是不能接受的風險。前一天在有網路的地方錄下真實輸出,當天零網路重播。
   所有 cell 一樣執行、表格一樣當場算出,只有 API 呼叫換成查表,而且**跑得更快**(沒有網路延遲)。
   > 「這些輸出是我昨天跑好存下來的,現在是重播 —— 因為會場網路我不敢賭。
   > 程式碼跟評測都是當場執行的,只有呼叫模型那一步是查表。」
   台下工程師會認同這個判斷;假裝是即時的、被問到才承認,才會扣分。
2. **操作流程**(六節,對應 notebook 的 §0–§6):
   §0 環境與 client(切 GEAP 或 AI Studio 只差建構參數)→ §1 商品資料(停在 `regulated_category`)
   → §2 v0 與 v3 prompt 全文 + **重跑 v0 與 v3 同一個商品** → §3 `parse_freeform()`(為了評 v0 要寫的正則猜測 parser,
   **v3 之後這段可以整個刪掉**)+ **重跑對比表**(全場高潮,停 5 秒不說話)
   → §4 場景 B 快速捲動(超時可砍)→ §5 實際花費與 judge 佔比 → §6 總覽儀表板與信賴區間。
3. **必須主動講的兩件事**:
   - 對比表上 **v3 rubric 通過率 85.4% 低於 v2 的 86.8%**,critical 違反從 9 升到 13。
     配對比較 v3−v2 = −1.43pp,95% CI [−5.15, +2.57] **跨過零** ——
     「我不會說 v3 比較差,也不會說 v2 比較好。我只能說:還沒有證據。」
     同理 v1−v0 也跨過零;v1 贏在規則層那幾欄(標題長度 74% → 100%、禁詞 80% → 98%),不需要檢定。
   - **每一版做對一件事**:v1 修格式與合規、v2 修語意、v3 修可機器讀取。
4. **帶走**:notebook 連結留在畫面上直到 QA 結束;repo 內含錄製腳本 ——
   有人問「是不是造假」→「`RECORD_FIXTURES=True` 你自己跑一次就會得到同樣的表」。

**待查證(講者事前必做)**:對照組 `talk/script.md` 的 demo 段寫著「v0 只有 8 筆受評,分母不同不能比」,
但目前 `poc/data/eval_results.json` 四個版本的 `受評筆數` 與 `分母` 都是 50。
**上台前要確認以哪一版為準,兩者不能同時講。** 這份設計文件採用 eval_results.json 的現值(50 筆)。

## 先備知識

- 聽眾:需要 section-03 的四個版本與 section-04 的評測框架,否則對比表看不懂(`depends-on: [section-03, section-04]`)。
- 講者:**離線重播與即時兩種模式都要演練過**。`OFFLINE_MODE = True` 與 `RECORD_FIXTURES = True`
  不能同時為 True;改過 prompt 或模型名之後 fixtures 全部失效,`ReplayClient` 會直接報錯 ——
  演練時就會炸,不會拖到台上。

## 頁面規劃

| 段內頁 | 一句話重點 | 內文內容與形式 | 圖形 | 圖形類型與構想 |
|---|---|---|---|---|
| 1 | 接下來的十分鐘,前面講的每個數字都會當場跑出來 | 圖為主,下方一行說明離線重播 | diagram-07-1 | 流程圖:六節橫向串接(環境 → 商品資料 → 生成 v0/v3 → 三層評測與對比表 → 成本 → 儀表板),對比表那一節標為重點 |
| 2 | 帶走:notebook、repo、三件事 | 條列三行:notebook 連結、repo 連結、一行「錄製腳本在 repo 裡,你自己跑一次會得到同樣的表」 | - | - |

## 備註要點

- **銜接**:接第六段的收尾 —— 「謝謝。接下來我實際跑給大家看。」
- 第 1 頁講完離線重播就切到 Colab,**不要在投影片上停留**。
- 重播模式每個 cell 秒回,空出來的時間留給講解與停頓,特別是對比表出現後那 5 秒。
- 風險處置:完全沒網路 / 網路時好時壞 → 不影響;筆電當機或 Colab 開不起來 → 切預錄影片
  (存本機,不要只放雲端);超時 → 砍 §4 場景 B,不影響主論點。
- 結束回到對比表:「所以:你怎麼知道它有沒有變好?看這張表。」—— 全場最後一句回扣主軸。
- **交棒**:進 QA,notebook 連結留在畫面上。

## Demo

**這一段就是 demo。**

- **目的**:讓聽眾看到前六段的主張真的跑得動,並帶走一份可以改的 Colab notebook
- **形式**:沿用 repo 現有的 `poc/`(uv + python + notebook),**不另建 `demo2/demo/`**
- **環境需求**:Colab + `poc/retail_genai_poc_speaker.ipynb`;`OFFLINE_MODE = True`;零網路;
  fixtures 為 `poc/data/demo_outputs.json`(對真實 API 錄製,非測試假 client 產生)
- **事前檢查**:`make all`(重建 notebook + 跑離線測試);`uv run python poc/check_env.py` 需要網路,
  只在錄 fixtures 那天跑
