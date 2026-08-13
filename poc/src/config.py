"""集中設定：模型、價格、通路限制。

所有環境相關設定集中在這裡。換專案、換模型、換價格都只改這個檔案。
價格必須到官方頁面現查後更新，不要沿用寫死的數字。
"""

# --- GCP ---
PROJECT_ID = "cacafly-poc"

# ⚠️ 必須是 "global"。實測 asia-east1 上沒有任何 Gemini publisher model，
#    所有呼叫都會 404。這是很容易踩的坑：compute 資源設在 asia-east1，
#    不代表 Gemini 模型在那裡可用。
LOCATION = "global"

# 使用 Vertex AI（走 GCP 專案計費、資料落地可控）
# 若現場 GCP 權限失效，把 USE_VERTEX 改成 False 並填入 AI Studio key 作為備援
USE_VERTEX = True
FALLBACK_API_KEY = ""  # 僅備援用，勿 commit 真實金鑰

# --- 離線重播（會場網路不穩時的主要策略）---
# 在網路不穩的場合（會議室、教室、展場）即時打 API 是不能接受的風險。
#
#   RECORD_FIXTURES = True   有網路時先跑一次，把真實輸出錄下來
#   OFFLINE_MODE    = True   之後零網路重播錄好的輸出
#
# 重播時所有 cell 一樣會執行、表格一樣是當場算出來的，只有 API 呼叫被換成
# 查表。畫面上看不出差別，但完全不依賴網路。
#
# ⚠ 兩個不能同時為 True。
OFFLINE_MODE = False
RECORD_FIXTURES = False
FIXTURES_FILE = "demo_outputs.json"

# --- 模型 ---
# 以下型號皆已在 cacafly-poc / global 實測可用（2026-08-13）。
# 換專案或換 region 前請重跑 poc/check_env.py 確認。
GEN_MODEL = "gemini-flash-latest"   # 生成用：吞吐量大、要便宜
JUDGE_MODEL = "gemini-2.5-pro"      # 評審用：刻意與生成模型不同，降低 self-preference bias
CHEAP_MODEL = "gemini-2.5-flash-lite"  # 成本段示範「降級」用

GEN_TEMPERATURE = 0.4  # 用低溫，降低失敗機率
JUDGE_TEMPERATURE = 0.0

# --- 價格（USD / 每百萬 token）---
# ⚠️ 這些是佔位值。使用前請到官方頁面現查更新：
#    https://cloud.google.com/vertex-ai/generative-ai/pricing
# 不要引用這裡的數字，要看 §5 實際跑出來的花費。
PRICING = {
    "gemini-flash-latest": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
}
PRICE_LAST_CHECKED = "尚未查證 — 上場前必須更新"

# --- BigQuery（場景 B）---
# 預設關閉：重播模式不涵蓋 BigQuery 呼叫。
# 錄製時可開啟一次，把「AI 當 ETL」這件事真的做完。
USE_BIGQUERY = False
BQ_DATASET = "retail_genai_demo"
BQ_TABLE = "review_insights"
BQ_LOCATION = "asia-east1"  # BigQuery 的 region 與 Gemini 無關，這裡可以用亞洲

USD_TO_TWD = 32.0

# --- 通路限制（來自 products.json 的 _meta.channel_limits）---
SHOPEE_TITLE_MAX = 60
SEO_DESC_MAX = 120
BULLET_MAX = 30
BULLET_COUNT = 4
