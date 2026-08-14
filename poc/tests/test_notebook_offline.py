"""離線執行整份 notebook，用假的 genai client。

這是上台前最有價值的一道保險。它驗證的是：

1. `build_notebook.py` 把模組攤平成 notebook 的轉換沒有弄壞任何東西
   （它會刪掉 `from . import config`、把 `config.GEN_MODEL` 改寫成 `GEN_MODEL`
   —— 這種字串層級的改寫很容易出錯，而且只有執行時才會發現）。
2. cell 的順序是對的，沒有用到還沒定義的名稱。
3. 對比表的階梯真的會出現。

真正無法離線驗證的只剩「模型實際會回什麼」。其餘全部在這裡跑過。

執行：python3 poc/tests/test_notebook_offline.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import types as pytypes

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
NB = ROOT / "poc" / "retail_genai_poc.ipynb"


# --------------------------------------------------------------------------
# 假的 google.genai
# --------------------------------------------------------------------------
class FakeUsage:
    def __init__(self, pin: int, pout: int):
        self.prompt_token_count = pin
        self.candidates_token_count = pout


class FakeResponse:
    def __init__(self, text: str, pin: int = 800, pout: int = 200):
        self.text = text
        self.usage_metadata = FakeUsage(pin, pout)


class FakeTokenCount:
    def __init__(self, n: int):
        self.total_tokens = n


_MUST_PAT = re.compile(r"不可省略或改寫：(.+)")


def _must_keywords(prompt: str) -> list[str]:
    m = _MUST_PAT.search(prompt)
    return m.group(1).strip().split("、") if m else []


def _detect_version(prompt: str) -> str:
    if "【輸出格式】" in prompt:
        return "v3"
    if "【法規限制" in prompt:
        return "v2"
    if "【格式要求】" in prompt:
        return "v1"
    return "v0"


def _fake_copy(prompt: str) -> str:
    """依 prompt 版本回傳「模型大概會產出什麼」。

    刻意讓 v0/v1 帶違規詞、v2 合規但非結構化、v3 完全乾淨 ——
    模擬真實的階梯。這不是在假造結果，而是在驗證評測管線能不能
    正確地把這些差異辨識出來。
    """
    version = _detect_version(prompt)
    kws = _must_keywords(prompt)
    kw_text = "、".join(kws)

    if version == "v0":
        return (
            "## ✨【護眼首選・熱銷回購】給你的靈魂之窗最溫柔的守護，"
            "長效呵護每一天的清晰視界，現在下單再享優惠！\n\n"
            "我們採用頂級原料，能夠有效改善視力，長期補充還能增強免疫力，讓你告別疲勞。\n\n"
            "現在就開始吧！"
        )

    if version == "v1":
        return (
            f"標題：優選 {kws[0] if kws else '商品'} {kws[1] if len(kws) > 1 else ''} 每日一份\n\n"
            "賣點：\n"
            f"- {kw_text[:20]}，紮實有感\n"
            "- 每日一份，方便持續\n"
            "- 台灣製造，品質穩定\n"
            "- 長期補充護眼有感\n\n"
            f"SEO描述：本產品含{kw_text}，能有效改善視力疲勞，適合長時間用眼的族群，"
            "建議每日一份持續補充。\n\n"
            "#保健 #護眼"
        )

    if version == "v2":
        return (
            f"標題：優選 {kws[0] if kws else '商品'} {kws[1] if len(kws) > 1 else ''} 每日一份\n\n"
            "賣點：\n"
            f"- {kw_text[:20]}，成分紮實\n"
            "- 每日一份，方便持續\n"
            "- 台灣製造，品質穩定\n"
            "- 適合日常規律補充\n\n"
            f"SEO描述：本產品含{kw_text}，適合長時間面對螢幕的日常補充，"
            "建議每日一份，搭配均衡飲食。\n\n"
            "#日常補充 #台灣製造"
        )

    return json.dumps(
        {
            "title": f"優選 {kws[0] if kws else '商品'} {kws[1] if len(kws) > 1 else ''} 每日一份",
            "bullets": [
                f"{kw_text[:18]}，成分紮實",
                "每日一份，方便持續",
                "台灣製造，品質穩定",
                "適合日常規律補充",
            ],
            "seo_description": (
                f"本產品含{kw_text}，適合長時間面對螢幕的日常補充，建議每日一份。"
            ),
            "hashtags": ["日常補充", "台灣製造"],
        },
        ensure_ascii=False,
    )


_RUBRIC_IDS = ["R1", "R2", "R3", "R4", "R5", "R6"]


def _fake_rubric_gen(prompt: str) -> str:
    """模擬「從商品資料產生驗收清單」。"""
    return json.dumps(
        {
            "rubrics": [
                {
                    "id": rid,
                    "criterion": f"模擬判準 {rid}",
                    "dimension": ["賣點覆蓋", "品牌語調", "消費者可讀性"][i % 3],
                    "critical": i < 2,
                }
                for i, rid in enumerate(_RUBRIC_IDS)
            ]
        },
        ensure_ascii=False,
    )


def _fake_rubric_check(prompt: str) -> str:
    """模擬逐條檢查。

    結構化輸出全過；合規但非結構化過大部分；帶違規詞的過很少 ——
    讓 rubric 通過率也呈現階梯，用來驗證彙整邏輯。
    """
    structured = '"title"' in prompt
    compliant = "改善視力" not in prompt and "增強免疫力" not in prompt
    n_pass = 6 if structured else (5 if compliant else 2)
    return json.dumps(
        {
            "results": [
                {
                    "id": rid,
                    "passed": i < n_pass,
                    "evidence": "模擬依據" if i < n_pass else "模擬缺漏",
                }
                for i, rid in enumerate(_RUBRIC_IDS)
            ]
        },
        ensure_ascii=False,
    )


def _fake_insight(prompt: str) -> str:
    rating = int(re.search(r"評分：(\d) 星", prompt).group(1))
    negative_service = any(k in prompt for k in ["物流", "出貨", "客服", "壓扁", "包裝"])
    return json.dumps(
        {
            "sentiment": "positive" if rating >= 4 else ("neutral" if rating == 3 else "negative"),
            "aspects": ["物流配送"] if negative_service else ["產品品質"],
            "is_about_product": not negative_service,
            "actionable_suggestion": "加強外箱緩衝材" if negative_service else "",
            "urgency": "medium" if rating <= 2 else "low",
        },
        ensure_ascii=False,
    )


class FakeModels:
    def __init__(self):
        self.call_log: list[str] = []

    def generate_content(self, *, model, contents, config=None):
        prompt = contents if isinstance(contents, str) else str(contents)
        if "訂出「文案驗收清單」" in prompt:
            self.call_log.append("rubric_gen")
            return FakeResponse(_fake_rubric_gen(prompt), 900, 260)
        if "你是電商文案審核員" in prompt:
            self.call_log.append("rubric_check")
            return FakeResponse(_fake_rubric_check(prompt), 1400, 200)
        if "你是電商營運分析師" in prompt:
            self.call_log.append("insight")
            return FakeResponse(_fake_insight(prompt), 400, 80)
        self.call_log.append("gen")
        return FakeResponse(_fake_copy(prompt), len(prompt) // 2, 220)

    def count_tokens(self, *, model, contents):
        # 粗略模擬中文比英文密的行為
        cjk = sum(1 for c in contents if ord(c) > 0x2E80)
        other = len(contents) - cjk
        return FakeTokenCount(int(cjk * 0.9 + other * 0.3) or 1)


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.models = FakeModels()


def install_fake_genai() -> None:
    """把假的 google.genai 塞進 sys.modules，notebook 就不會真的打 API。"""
    genai_mod = pytypes.ModuleType("google.genai")
    genai_mod.Client = FakeClient

    types_mod = pytypes.ModuleType("google.genai.types")

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    types_mod.GenerateContentConfig = GenerateContentConfig
    genai_mod.types = types_mod

    google_mod = sys.modules.get("google") or pytypes.ModuleType("google")
    google_mod.genai = genai_mod

    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod


# --------------------------------------------------------------------------
# 執行 notebook
# --------------------------------------------------------------------------
def run_notebook(
    verbose: bool = False,
    overrides: dict | None = None,
    install_fake: bool = True,
) -> dict:
    """執行 notebook 的所有 code cell。

    overrides 會在建立 client 的那一格「之前」注入，用來測試錄製／重播模式 ——
    這是演講當天真正會走的路徑，必須驗證過，不能只是假設它會動。

    install_fake=False 時**不塞**假的 google.genai，用來驗證「這台機器根本
    沒裝 SDK」的情境。注意：install_fake_genai() 是直接寫 sys.modules，
    會蓋過 meta_path 攔截器 —— 想測「沒裝 SDK」就一定要把它關掉，
    否則測試會假通過。
    """
    if install_fake:
        install_fake_genai()
    nb = json.loads(NB.read_text(encoding="utf-8"))
    # 必須用 "__main__"：@dataclass 會查 sys.modules[cls.__module__]，
    # 用一個不存在的模組名會讓 dataclass 在建立時炸掉。Colab 本身也是 __main__。
    ns: dict = {"__name__": "__main__"}

    printed: list[str] = []
    real_print = print

    def capture(*args, **kwargs):
        printed.append(" ".join(str(a) for a in args))
        if verbose:
            real_print(*args, **kwargs)

    ns["print"] = capture

    # §0 的相依偵測格會實際執行（它本來就該是安全的：偵測到齊全就跳過安裝）。
    # 但測試絕不容許真的去 pip install —— 那會污染 uv 管理的 .venv。
    # 所以把 subprocess.run 換成會炸的版本：只要那一格試圖安裝，測試就失敗。
    import subprocess

    original_run = subprocess.run

    def _no_install(*args, **kwargs):
        raise AssertionError(f"notebook 在測試環境嘗試安裝套件：{args[:1]}")

    subprocess.run = _no_install

    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    for idx, cell in enumerate(code_cells):
        src = "".join(cell["source"])
        if "client = make_client(" in src:
            # 一定要先重置這兩個旗標再套用測試的 overrides。
            #
            # 錄好 fixtures 之後，notebook 會在內嵌 fixtures 的那一格把
            # OFFLINE_MODE 設成 True（那是刻意的，見 build_notebook.py）。
            # 若不重置，預設的 run_notebook() 就會改成重播「真實錄製資料」，
            # 測試等於在斷言模型的實際輸出 —— 那會隨每次錄製而變動。
            #
            # 這些測試要驗的是管線本身（攤平轉換、cell 順序、階梯邏輯、
            # 錄製↔重播一致性），所以固定走可預期的假 client。
            ns["OFFLINE_MODE"] = False
            ns["RECORD_FIXTURES"] = False
            if overrides:
                ns.update(overrides)
        try:
            exec(compile(src, f"<cell {idx}>", "exec"), ns)
        except Exception as e:
            subprocess.run = original_run
            raise AssertionError(
                f"cell {idx} 執行失敗：{type(e).__name__}: {e}\n"
                f"--- cell 內容（前 400 字）---\n{src[:400]}"
            ) from e

    subprocess.run = original_run
    ns["_printed"] = "\n".join(printed)
    return ns


# --------------------------------------------------------------------------
# 測試
# --------------------------------------------------------------------------
def test_notebook_runs_end_to_end():
    ns = run_notebook()
    assert "rule_results" in ns, "沒有產生規則層結果"
    expected = len(ns["PRODUCTS"]) * len(ns["PROMPT_VERSIONS"])
    assert len(ns["rule_results"]) == expected, (
        f"應有 {len(ns['PRODUCTS'])} 商品 × {len(ns['PROMPT_VERSIONS'])} 版 = {expected} 筆，"
        f"實際 {len(ns['rule_results'])}"
    )


def test_flattening_preserved_config_constants():
    """驗證 config.X → X 的字串改寫沒有漏掉任何常數。"""
    ns = run_notebook()
    for name in ["GEN_MODEL", "JUDGE_MODEL", "PRICING", "SHOPEE_TITLE_MAX", "USD_TO_TWD"]:
        assert name in ns, f"常數 {name} 在攤平後遺失"
    assert ns["PRICING"], "PRICING 是空的"


def test_staircase_appears_in_table():
    """對比表必須呈現單調遞增 —— 這是整場演講的主張。"""
    ns = run_notebook()
    table = ns["build_table"](ns["rule_results"])
    passes = [table[v]["_全數通過"] for v in ["v0", "v1", "v2", "v3"]]
    assert passes == sorted(passes), f"階梯不是單調遞增：{passes}"
    assert passes[0] == 0.0, f"v0 不該有任何一筆全數通過，實際 {passes[0]}%"
    assert passes[-1] == 100.0, f"v3 應全數通過，實際 {passes[-1]}%"


def test_regulation_column_fixed_at_v2():
    """禁詞欄位必須在 v2 才修好，不能更早 —— 否則歸因就錯了。"""
    ns = run_notebook()
    table = ns["build_table"](ns["rule_results"])
    assert table["v1"]["banned_clean"] < 100.0, "v1 不該通過禁詞檢查"
    assert table["v2"]["banned_clean"] == 100.0, "v2 應修好禁詞"


def test_schema_column_fixed_only_at_v3():
    ns = run_notebook()
    table = ns["build_table"](ns["rule_results"])
    for v in ["v0", "v1", "v2"]:
        assert table[v]["schema_valid"] == 0.0, f"{v} 不該被判定為結構化"
    assert table["v3"]["schema_valid"] == 100.0


def test_eval_judges_every_item_so_denominators_match():
    """評測時必須全部送審，四個版本的分母才會一致。

    生產環境會把規則層擋下的濾掉（省錢），但評測沿用那個過濾會出事：
    被擋下的正是最爛的幾筆，於是 v0 的分母比 v1 小，平均分被倖存者偏差
    灌水，反而看起來比 v1 高。實測 12 筆時就發生了（v0 78.5% > v1 74.0%）。

    而過濾實際只省 7–10% 的評審成本（US$0.08）。用這個換掉「版本之間
    能不能比較」是很差的交換。
    """
    ns = run_notebook()
    n_expected = len(ns["PRODUCTS"]) * len(ns["PROMPT_VERSIONS"])
    assert len(ns["rubric_reports"]) == n_expected, (
        f"評測應全部送審，預期 {n_expected} 筆，實際 {len(ns['rubric_reports'])}"
    )

    summary = ns["summarize_rubrics"](ns["rubric_reports"], total_items=len(ns["PRODUCTS"]))
    denoms = {v: s["受評筆數"] for v, s in summary.items()}
    assert len(set(denoms.values())) == 1, f"各版本受評筆數不一致：{denoms}"


def test_production_filter_is_still_reported():
    """生產環境的過濾邏輯要保留並顯示出來 —— 那是真實可用的省錢手段。

    評測不採用它，但要讓人看到「同一個機制在不同目的下取捨相反」。
    """
    ns = run_notebook()
    assert "would_skip" in ns, "應統計生產環境會擋下幾筆"
    assert "生產環境會擋下" in ns["_printed"]


def test_rubrics_generated_once_per_product_not_per_version():
    """rubric 必須每個商品一組，v0~v3 共用。

    若每個版本各自生成，等於每個考生考不同的考卷，對比表就沒有意義。
    """
    ns = run_notebook()
    n_products = len(ns["PRODUCTS"])
    assert len(ns["rubric_sets"]) == n_products, (
        f"應為 {n_products} 個商品各一組，實際 {len(ns['rubric_sets'])}"
    )
    n_gen = ns["client"].models.call_log.count("rubric_gen")
    assert n_gen == n_products, (
        f"rubric 生成應只呼叫 {n_products} 次（每商品一次），實際 {n_gen}"
    )


def test_rubric_reports_are_binary_not_scored():
    """回報必須是 pass/fail 集合，不能是分數。"""
    ns = run_notebook()
    rep = ns["rubric_reports"][0]
    assert isinstance(rep.passed_ids, list)
    assert isinstance(rep.total, int) and rep.total > 0
    assert 0.0 <= rep.pass_rate <= 100.0
    assert not hasattr(rep, "tone_score"), "不該再有 Likert 分數欄位"


def test_rubric_pass_rate_improves_with_version():
    """rubric 通過率也要呈現階梯，否則 judge 這層沒有說服力。"""
    ns = run_notebook()
    summary = ns["summarize_rubrics"](ns["rubric_reports"])
    versions = [v for v in ["v0", "v1", "v2", "v3"] if v in summary]
    rates = [summary[v]["rubric通過率%"] for v in versions]
    assert rates == sorted(rates), f"rubric 通過率不是遞增：{dict(zip(versions, rates, strict=True))}"


def test_critical_failures_block_publish():
    """critical 判準沒過就不該標記為可上架。"""
    from poc.src.judge import RubricReport

    r = RubricReport(sku="X", version="v0", passed_ids=["R2"] * 5,
                     failed=[("R1", "缺含量", True)], total=6)
    assert not r.would_publish, "critical 未通過仍標記可上架"

    ok = RubricReport(sku="X", version="v3", passed_ids=[f"R{i}" for i in range(6)],
                      failed=[], total=6)
    assert ok.would_publish


def test_cost_ledger_separates_generation_from_judging():
    """評審成本必須被單獨算出來 —— 這是演講中『最常被漏算的一筆』。"""
    ns = run_notebook()
    ledger = ns["ledger"]
    assert ledger.total_cost_usd("gen") > 0, "生成成本應大於 0"
    assert ledger.total_cost_usd("judge") > 0, "評審成本應大於 0"
    assert "評審佔總成本" in ledger.summary()


def test_scale_estimate_is_finite_and_positive():
    ns = run_notebook()
    est = ns["est"]
    assert est.total_usd > 0
    assert est.total_twd > est.total_usd, "台幣金額應大於美金金額"
    assert "合計" in est.render()


def test_insights_extracted_and_validated():
    ns = run_notebook()
    assert len(ns["insights"]) == 15, f"應有 15 則評論，實際 {len(ns['insights'])}"
    assert ns["check"]["通過率"] >= 0


def test_notebook_defaults_to_offline_when_fixtures_are_embedded():
    """有內嵌 fixtures 時，notebook 必須預設 OFFLINE_MODE = True。

    fixtures 存在的唯一目的就是離線重播。原本要靠人記得在上場前翻旗標，
    而那正是最容易忘的一步 —— 忘了就會在沒網路的會場當場打 API。
    與其寫進檢查清單，不如讓它預設就對。

    這個預設只作用在 notebook；src/config.py 維持 False，
    所以 run_eval.py 等本機腳本仍走一般連線模式。
    """
    nb = json.loads(NB.read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    fixture_cell = next((s for s in cells if "FIXTURES = {" in s), None)
    assert fixture_cell, "找不到內嵌 fixtures 的 cell"

    has_real_fixtures = '"calls": {}' not in fixture_cell and "'calls': {}" not in fixture_cell
    if not has_real_fixtures:
        return  # 尚未錄製，不強制

    assert "OFFLINE_MODE = True" in fixture_cell, (
        "已內嵌 fixtures 但 notebook 沒有預設離線模式 —— "
        "上場忘記翻旗標就會在沒網路的會場打 API"
    )


def test_dependency_cell_skips_install_when_deps_present():
    """相依偵測格在套件齊全時必須跳過安裝，不能無條件 pip install。

    這件事在 uv 環境很重要：無條件安裝會把套件裝進 .venv 卻不在 uv.lock 裡，
    環境就跟鎖定檔對不上。run_notebook 已把 subprocess.run 換成會炸的版本，
    所以這個測試能跑完，就代表那一格沒有嘗試安裝。
    """
    ns = run_notebook()
    assert "相依套件齊全，跳過安裝" in ns["_printed"], (
        "偵測邏輯沒有正確判斷套件已存在"
    )


def test_no_price_check_reminder_left_unresolved():
    """提醒訊息必須出現在輸出裡，確保上台前不會忘記更新價格。"""
    ns = run_notebook()
    assert "價格常數最後查證時間" in ns["_printed"]


# --------------------------------------------------------------------------
# 離線重播 —— 演講當天實際會走的路徑
# --------------------------------------------------------------------------
def _record_run() -> dict:
    """以錄製模式跑一次 notebook，把輸出檔導到暫存目錄。

    ⚠️ 必須覆寫 `FIXTURES_FILE`。notebook 的 §6 在 RECORD_FIXTURES=True 時
    會把 fixtures 寫成檔案；若不改路徑，測試就會在 repo 根目錄留下一份
    **由假 client 產生的** demo_outputs.json。那份檔案結構完全正確、
    看起來就像真的錄製結果，卻是假資料 —— 一旦被誤當成真的拿去用，
    台上放的就是憑空捏造的數字。這個坑實際踩過一次。
    """
    import tempfile

    tmp = pathlib.Path(tempfile.mkdtemp()) / "fixtures_from_mock.json"
    return run_notebook(
        overrides={"RECORD_FIXTURES": True, "FIXTURES_FILE": str(tmp)}
    )


def test_record_run_does_not_write_into_the_repo():
    """錄製測試不可以在 repo 裡留下假的 fixtures 檔。"""
    repo = ROOT
    before = {p for p in [repo / "demo_outputs.json", repo / "poc" / "demo_outputs.json"] if p.exists()}
    _record_run()
    after = {p for p in [repo / "demo_outputs.json", repo / "poc" / "demo_outputs.json"] if p.exists()}
    new = after - before
    assert not new, f"測試在 repo 留下假 fixtures：{[str(p) for p in new]}"


def test_record_then_replay_reproduces_identical_results():
    """錄製 → 重播必須產生完全一樣的結果。

    這是會場網路不穩時的保命機制。如果重播出來的表跟錄製時不一樣，
    台上放的就是跟程式碼對不上的東西 —— 這比當場沒網路更糟。
    """
    rec = _record_run()
    fixtures = rec["client"].dump()
    assert fixtures["calls"], "錄製模式沒有錄到任何呼叫"

    rep = run_notebook(
        overrides={"OFFLINE_MODE": True, "RECORD_FIXTURES": False, "FIXTURES": fixtures}
    )

    rec_table = rec["build_table"](rec["rule_results"])
    rep_table = rep["build_table"](rep["rule_results"])
    assert rec_table == rep_table, "重播結果與錄製結果不一致"

    # 成本也要一致，否則台上唸的數字會跟錄製時不同
    assert abs(rec["ledger"].total_cost_usd() - rep["ledger"].total_cost_usd()) < 1e-9


def test_replay_never_touches_the_network():
    """重播模式下不得建立任何真實 client。

    做法：把 genai.Client 換成會拋例外的假貨。若重播還是去呼叫它，測試就會失敗。
    """
    rec = _record_run()
    fixtures = rec["client"].dump()

    import google.genai as genai_mod

    original = genai_mod.Client

    def exploding(*a, **k):
        raise AssertionError("重播模式竟然嘗試建立真實 client —— 會場沒網路就會炸")

    genai_mod.Client = exploding
    try:
        ns = run_notebook(
            overrides={"OFFLINE_MODE": True, "RECORD_FIXTURES": False, "FIXTURES": fixtures}
        )
        assert ns["client"].models.hits > 0, "重播模式沒有命中任何錄製輸出"
    finally:
        genai_mod.Client = original


def test_replay_works_without_the_sdk_installed_at_all():
    """重播必須在**完全沒有 google-genai** 的機器上也能跑完。

    這是「把單一個 .ipynb 丟到沒有網路的 Colab」的真實情境：
    要裝 SDK 就得有網路，一旦需要網路，「零網路重播」的前提就破功了。

    做法：錄製之後把 google.genai 從 sys.modules 移除，並攔截後續的 import
    讓它一律失敗，然後在這種環境下跑完整份 notebook。
    """
    rec = _record_run()
    fixtures = rec["client"].dump()

    class _BlockGenai:
        """攔截 google.genai 的 import，模擬「這台機器沒裝 SDK」。"""

        def find_module(self, fullname, path=None):  # 舊式介面，保險起見
            return self if fullname.startswith("google.genai") else None

        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("google.genai"):
                raise ImportError(f"模擬環境未安裝 {fullname}")
            return None

        def load_module(self, fullname):
            raise ImportError(f"模擬環境未安裝 {fullname}")

    saved = {k: v for k, v in sys.modules.items() if k.startswith("google.genai")}
    for k in saved:
        del sys.modules[k]
    blocker = _BlockGenai()
    sys.meta_path.insert(0, blocker)
    try:
        # 確認攔截真的生效，否則這個測試會假通過
        try:
            import google.genai  # noqa: F401

            raise AssertionError("攔截器沒有生效，google.genai 仍可匯入")
        except ImportError:
            pass

        ns = run_notebook(
            overrides={"OFFLINE_MODE": True, "RECORD_FIXTURES": False, "FIXTURES": fixtures},
            install_fake=False,  # 關鍵：不塞假 SDK，否則 sys.modules 會蓋過攔截器
        )
        expected = len(ns["PRODUCTS"]) * len(ns["PROMPT_VERSIONS"])
        assert len(ns["rule_results"]) == expected, "沒有 SDK 時未能跑完整份 notebook"
        assert ns["client"].models.hits > 0, "沒有命中任何錄製輸出"
        assert "離線重播（OFFLINE_MODE=True）不需要它" in ns["_printed"], (
            "缺 SDK 時應說明離線重播仍可繼續"
        )
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(saved)


def test_gen_config_refuses_to_degrade_when_online():
    """連線模式下缺 SDK 必須直接炸，不能靜默降級成假 config 物件。

    降級只在離線重播時才合理。若連線模式也默默降級，會變成「明明沒裝 SDK
    卻看起來一切正常」，直到真的要呼叫 API 才失敗。
    """
    from poc.src import config as cfg
    from poc.src import generation

    saved = {k: v for k, v in sys.modules.items() if k.startswith("google.genai")}
    for k in saved:
        del sys.modules[k]
    sys.modules["google.genai"] = None  # 讓 import 觸發 ImportError

    old = cfg.OFFLINE_MODE
    try:
        cfg.OFFLINE_MODE = False
        try:
            generation.gen_config(temperature=0)
        except ImportError:
            pass
        else:
            raise AssertionError("連線模式缺 SDK 時應該拋 ImportError")

        cfg.OFFLINE_MODE = True
        obj = generation.gen_config(temperature=0, response_schema={"x": 1})
        assert obj.response_schema == {"x": 1}, "離線降級物件缺少必要屬性"
    finally:
        cfg.OFFLINE_MODE = old
        sys.modules.pop("google.genai", None)
        sys.modules.update(saved)


def test_replay_fails_loudly_when_prompt_changed():
    """prompt 改過但沒重新錄製時，必須明確報錯而不是靜默給舊資料。

    寧可在演練時炸掉，也不要在台上放出跟現在程式碼對不上的結果。
    """
    from poc.src.generation import ReplayClient

    client = ReplayClient({"calls": {}, "token_counts": {}})
    try:
        client.models.generate_content(model="m", contents="沒錄過的 prompt", config=None)
    except KeyError as e:
        assert "重新錄製" in str(e), f"錯誤訊息應指引重新錄製，實際：{e}"
    else:
        raise AssertionError("找不到 fixture 時應該拋錯，而不是回傳空結果")


def test_recording_client_keeps_the_wrapped_client_alive():
    """RecordingClient 必須保留真實 client 的參照，不能只留 .models。

    只留 .models 的話，genai.Client 在 make_client() 回傳後就沒人參照，
    會被 GC 回收並關閉底層連線 —— 之後每一次呼叫都拿到
    「Cannot send a request, as the client has been closed.」，
    整批錄製會全部失敗且 token 全為 0。

    這個 bug 用假 client 測不出來（假的沒有連線可關），是實際錄製 50 筆
    整批炸掉才發現的。所以這裡改成結構性檢查：確認包裝後的物件仍持有
    對原 client 的參照，而且 GC 之後還活著。
    """
    import gc
    import weakref

    from poc.src.generation import RecordingClient

    class FakeModels:
        def generate_content(self, **kw):
            return None

    class FakeReal:
        def __init__(self):
            self.models = FakeModels()

    real = FakeReal()
    ref = weakref.ref(real)
    rec = RecordingClient(real)
    del real
    gc.collect()

    assert ref() is not None, "RecordingClient 沒有保留真實 client，會被 GC 回收"
    assert any(v is ref() for v in vars(rec).values()), "找不到對真實 client 的參照"


def test_offline_and_record_are_mutually_exclusive():
    """兩個旗標同時開啟是設定錯誤，要在一開始就擋下來。"""
    from poc.src import config as cfg
    from poc.src.generation import make_client

    old = (cfg.OFFLINE_MODE, cfg.RECORD_FIXTURES)
    cfg.OFFLINE_MODE, cfg.RECORD_FIXTURES = True, True
    try:
        make_client({"calls": {"x": {}}})
    except RuntimeError as e:
        assert "不能同時" in str(e)
    else:
        raise AssertionError("兩個旗標同時為 True 時應該拋錯")
    finally:
        cfg.OFFLINE_MODE, cfg.RECORD_FIXTURES = old


# --------------------------------------------------------------------------
# 參數化：識別資訊在建構時注入，不寫死在 repo 裡
# --------------------------------------------------------------------------
def _rebuild_with(**profile):
    """暫時覆寫 PROFILE 後重新產生 cells，用完還原。"""
    from poc import build_notebook as bn

    old = dict(bn.PROFILE)
    bn.PROFILE.update(profile)
    try:
        return ["".join(c["source"]) for c in bn.build()]
    finally:
        bn.PROFILE.clear()
        bn.PROFILE.update(old)


def test_config_values_are_injected_as_literals():
    """注入的值要變成字面值 —— notebook 上了 Colab 就沒有你的環境變數了。"""
    cells = _rebuild_with(project_id="injected-project", bq_dataset="injected_ds")
    cfg = next(c for c in cells if "PRICING" in c and "PROJECT_ID" in c)

    assert 'PROJECT_ID = "injected-project"' in cfg, "PROJECT_ID 沒有被改寫成字面值"
    assert 'BQ_DATASET = "injected_ds"' in cfg, "BQ_DATASET 沒有被改寫成字面值"
    assert "os.environ" not in cfg, "notebook 裡不該留下讀環境變數的程式碼"


def test_injection_fails_loudly_when_a_constant_is_renamed():
    """常數被改名時要報錯。靜默不套用會讓人以為參數生效了，直到台上才發現連錯專案。"""
    from poc import build_notebook as bn

    try:
        bn._inject_config_values("# 這份原始碼裡沒有任何可改寫的常數\n")
    except RuntimeError as e:
        assert "PROJECT_ID" in str(e)
    else:
        raise AssertionError("找不到常數時應該拋錯")


def test_byline_appears_only_when_given():
    """沒給講者資訊就不該出現空白的署名行。"""
    from poc import build_notebook as bn

    before = dict(bn.PROFILE)

    blank = _rebuild_with(speaker="", event="", date="")
    assert "**講者**" not in blank[0], "沒給講者卻出現了署名"

    named = _rebuild_with(speaker="測試講者", event="測試場次", date="2026-08-21")
    assert "**講者**：測試講者" in named[0], "給了講者卻沒出現在標題"
    assert "**場次**：測試場次" in named[0]

    assert bn.PROFILE == before, "PROFILE 沒有還原"


if __name__ == "__main__":
    import traceback

    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}\n        {str(e)[:500]}")
        except Exception:
            failed += 1
            print(f"  ERROR {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
