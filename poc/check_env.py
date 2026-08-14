"""上場前的環境健檢：確認 config 裡設定的東西真的存在且可用。

這個腳本存在的原因很實際 —— 開發時 config 寫的是
`LOCATION="asia-east1"` 與 `JUDGE_MODEL="gemini-pro-latest"`，
兩個都是**看起來完全合理但實際上會 404** 的設定：

  - asia-east1 上沒有任何 Gemini publisher model
  - GEAP 上沒有 gemini-pro-latest 這個型號

這種錯誤不會在單元測試裡出現（測試用假 client），只有真的打一次才知道。
換專案、換 region、換模型之後都要重跑這支。

執行：python3 poc/check_env.py
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from poc.src import config  # noqa: E402

OK, FAIL, WARN = "✓", "✗", "!"
problems: list[str] = []


def report(status: str, label: str, detail: str = "") -> None:
    print(f"  {status} {label:<42} {detail}")
    if status == FAIL:
        problems.append(label)


def check_auth() -> bool:
    print("\n[1] 認證")
    try:
        import google.auth

        creds, project = google.auth.default()
        report(OK, "Application Default Credentials", f"project={project}")
        if project and project != config.PROJECT_ID:
            report(
                WARN,
                "ADC 專案與 config 不同",
                f"ADC={project} / config={config.PROJECT_ID}",
            )
        return True
    except Exception as e:  # noqa: BLE001
        report(FAIL, "找不到認證", f"{type(e).__name__}: 請執行 gcloud auth login")
        return False


def check_models() -> None:
    print(f"\n[2] 模型可用性（location={config.LOCATION}）")
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(
            vertexai=True, project=config.PROJECT_ID, location=config.LOCATION
        )
    except Exception as e:  # noqa: BLE001
        report(FAIL, "建立 client 失敗", str(e)[:60])
        return

    wanted = {
        "GEN_MODEL": config.GEN_MODEL,
        "JUDGE_MODEL": config.JUDGE_MODEL,
        "CHEAP_MODEL": getattr(config, "CHEAP_MODEL", None),
    }
    for role, model in wanted.items():
        if not model:
            continue
        try:
            t0 = time.time()
            client.models.generate_content(
                model=model,
                contents="ok",
                config=types.GenerateContentConfig(temperature=0),
            )
            report(OK, f"{role} = {model}", f"{time.time() - t0:.1f}s")
        except Exception as e:  # noqa: BLE001
            hint = ""
            if "404" in str(e):
                hint = "→ 該 region 沒有這個型號。試試 LOCATION='global'"
            report(FAIL, f"{role} = {model}", f"{str(e)[:44]} {hint}")


def check_structured_output() -> None:
    print("\n[3] structured output（v3 與整個評測層都靠它）")
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(
            vertexai=True, project=config.PROJECT_ID, location=config.LOCATION
        )
        resp = client.models.generate_content(
            model=config.GEN_MODEL,
            contents="回傳 {\"ok\": true}",
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
            ),
        )
        import json

        json.loads(resp.text)
        report(OK, "responseSchema 可用", "")
    except Exception as e:  # noqa: BLE001
        report(FAIL, "responseSchema 失敗", str(e)[:60])


def check_pricing() -> None:
    print("\n[4] 價格常數")
    missing = [
        m
        for m in {config.GEN_MODEL, config.JUDGE_MODEL, getattr(config, "CHEAP_MODEL", None)}
        if m and m not in config.PRICING
    ]
    if missing:
        report(FAIL, "有模型缺少價格設定", f"{missing} → 成本會被算成 0")
    else:
        report(OK, "所有使用中的模型都有價格", "")

    if "尚未查證" in config.PRICE_LAST_CHECKED:
        report(WARN, "價格尚未查證", "上場前請到官方 pricing 頁更新")
    else:
        report(OK, "價格查證日期", config.PRICE_LAST_CHECKED)


def check_bigquery() -> None:
    print("\n[5] BigQuery（場景 B，選用）")
    if not config.USE_BIGQUERY:
        report(WARN, "USE_BIGQUERY = False", "只展示 schema 與 SQL，不實際寫入")
        return
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=config.PROJECT_ID)
        list(client.query("SELECT 1").result())
        report(OK, "BigQuery 可查詢", f"dataset={config.BQ_DATASET}")
    except Exception as e:  # noqa: BLE001
        report(FAIL, "BigQuery 不可用", str(e)[:60])


# 假 client 產生的內容才會出現的字串（見 tests/test_notebook_offline.py）。
# 假 fixtures 的結構完全正確、看起來就像真的錄製結果，只有內容能分辨。
_MOCK_MARKERS = ("模擬判準", "模擬依據", "模擬缺漏", "優選 ")


def check_replay_readiness() -> None:
    print("\n[6] 離線重播準備狀態")
    import json
    import pathlib

    f = pathlib.Path(__file__).parent / "data" / config.FIXTURES_FILE
    if config.OFFLINE_MODE and config.RECORD_FIXTURES:
        report(FAIL, "兩個旗標同時為 True", "OFFLINE_MODE 與 RECORD_FIXTURES 只能開一個")

    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        calls = data.get("calls", {})
        blob = "".join(row.get("text", "") for row in calls.values())
        hits = [m for m in _MOCK_MARKERS if m in blob]
        if hits:
            report(
                FAIL,
                "fixtures 是假資料！",
                f"含測試標記 {hits[:2]} → 請用真實 API 重新錄製",
            )
        else:
            report(OK, f"已錄製 fixtures（{len(calls)} 筆）", "未偵測到假資料標記")
    else:
        report(WARN, "尚未錄製 fixtures", "OFFLINE_MODE 目前不可用")
    report(
        OK if not config.OFFLINE_MODE or f.exists() else FAIL,
        f"OFFLINE_MODE = {config.OFFLINE_MODE}",
        "上場當天應為 True" if not config.OFFLINE_MODE else "",
    )


# config.py 在沒有 GCP_PROJECT_ID 環境變數時會退回這個佔位字串。
# 帶著它去打 API 會得到一個沒頭沒尾的 403/404，不如在這裡先講清楚。
PLACEHOLDER_PROJECT = "your-gcp-project-id"


def check_project() -> bool:
    print("\n[0] 專案設定")
    if config.PROJECT_ID == PLACEHOLDER_PROJECT:
        report(
            FAIL,
            "沒有指定 GCP 專案",
            "請設定環境變數 GCP_PROJECT_ID（見 README §0）",
        )
        return False
    report(OK, "GCP 專案", config.PROJECT_ID)
    return True


def main() -> int:
    print("=" * 68)
    print(f"環境健檢  project={config.PROJECT_ID}  location={config.LOCATION}")
    print("=" * 68)

    if check_project() and check_auth():
        check_models()
        check_structured_output()
        check_bigquery()
    check_pricing()
    check_replay_readiness()

    print("\n" + "=" * 68)
    if problems:
        print(f"✗ {len(problems)} 項有問題：")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("✓ 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
