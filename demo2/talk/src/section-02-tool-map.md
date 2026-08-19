---
id: deck-02
type: deck
title: tool-map
description: GCP 生成式 AI 工具依專案階段分成三層
status: done
created: 2026-08-18
updated: 2026-08-18
section: section-02
slides: 5
---

## GCP 的 AI 工具，用「你在哪個階段」分

<div class="cols-2-1">
<div>

![h:430](../assets/diagram-02-1-tool-map.svg)

</div>
<div>

不用產品線分。

同一批模型，三個階段的問題完全不同。

多數人只停在最底下那一層。

</div>
</div>

<!--
銜接：接第一段的因果鏈 —— 先講工具，選錯工具後面全部白做。
不逐一介紹產品。每一層都會用一句「對創辦人而言這代表什麼」收尾。
這頁 60 秒帶過，重點在後面三頁。
-->

---

<!-- _class: center -->

## 探索期：不寫程式，五分鐘知道做不做得成

![w:1100](../assets/geap-overview.png)

Vertex AI 於 2026-04 更名 GEAP —— 端點與 SDK 沒動，程式碼一行都不用改。

<!--
第一次講到 GEAP 就交代改名：指著截圖上那句 "Vertex AI is now Agent Platform" 講，比自己說有說服力。
強調程式碼一行都不用改 —— demo 裡 vertexai=True 還在。
對創辦人：這一層你或 PM 自己做，不要先排工程資源。對工程師：prompt 可匯出。
口述鋪下一頁：截圖裡的 Authenticate 卡片，ADC 是 Recommended、API key 標的是 local testing。
-->

---

## 整合期：兩邊是同一批模型，差別在周邊

| | Gemini API（AI Studio key） | GEAP |
|---|---|---|
| 拿到 key | 五秒，網頁點一點 | 要 GCP 專案 + IAM |
| 認證 | API key | 服務帳號 / ADC |
| 計費歸屬 | 個人帳號 | GCP 專案，可進公司帳 |
| 資料落地 / VPC-SC | 較難指定 / ✗ | 可指定 region / ✓ |
| 適合 | 原型、side project | 要跟客戶簽約的正式系統 |

<!--
全段最慢的一頁，給足 3 分鐘。這是最多人搞混的一件事。
關鍵句：切換只差 client 的建構參數，程式碼一行都不用改 —— demo 會看到那三行。
對創辦人：這是部署決策不是技術決策。客戶問「我的資料存在哪」、法務要簽 DPA 時，你要能切到 GEAP。
稽核日誌（Cloud Audit Logs）用講的，沒放表上。不確定的商務條款就說要查，不要編。
-->

---

## 上線期：大部分人跳過的那一層

<div class="cols-2-1">
<div>

![h:430](../assets/diagram-02-2-tool-map-layer3.svg)

</div>
<div>

工具其次。

重點是你有沒有**一組固定的題目**和**一套固定的評分方式**。

</div>
</div>

<!--
這一層跳過的人，三個月後付出代價。
對創辦人：這是你唯一能拿來對董事會證明「有進步」的東西；不然被問「AI 做得怎麼樣了」只能說「感覺不錯」。
刻意留白 —— 不要在這裡開始講評測方法，那是第四段。
-->

---

<!-- _class: center -->

# 同樣的工具，<br>為什麼有人做得起來、有人做不起來？

<!--
交棒：差別在你把哪些要求寫成了條件 —— 下一段講 prompt。
唸完直接翻頁，不要停留解釋。
-->
