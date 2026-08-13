"""在 200 筆評測集上跑完整流程，產出可引用的統計結論。

## 這支跟 notebook 的分工

- **notebook（12 筆）**：台上跑的 demo。要快、要看得懂、要能內嵌成單一檔案。
- **這支（200 筆）**：離線跑的評測。用來回答「v2 和 v3 的差別是真的還是雜訊」。

12 筆時翻轉一次檢查就是 1.2 個百分點，小幅差距完全分不出是不是雜訊。
200 筆才有辦法做這種比較。這也是真實團隊的作法：demo 給人看流程，
結論來自夠大的評測集。

## 每一筆商品實際會做什麼

    [1] 生成      每個商品 × 4 版 → 4 份文案      flash
    [2] 規則層    4 份全部檢查                     本機，免費、毫秒級
    [3] rubric    每個商品產一次驗收清單           pro，v0~v3 共用同一份考卷
    [4] 逐條檢查  **全部送審**（分母一致才能比）    pro，這是最貴的一段

## 速度

瓶頸完全在等 API 回應，不在 CPU，所以拉高並行度幾乎線性加速。
實測（gemini-2.5-pro，零失敗）：8→10.3、16→26.1、32→46.5、64→80.7 次/分。

50 筆含評審層：並行 8 要 24 分鐘，並行 64 只要 3 分鐘，成本一樣。

## 用法

    uv run python poc/run_eval.py --limit 10                # 小量試跑
    uv run python poc/run_eval.py --limit 50 --workers 64   # 50 筆，最快
    uv run python poc/run_eval.py --no-judge                # 只跑規則層（免費）

結果會寫到 poc/data/eval_results.json，並印出摘要。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from poc.src import config, generation, judge, prompts, report, rules  # noqa: E402

DATA = pathlib.Path(__file__).parent / "data"
RESULTS = DATA / "eval_results.json"

# 每個 worker 每分鐘能完成幾次呼叫。實測 8/16/32/64 並行都接近線性，
# 因為瓶頸是等待回應而非 CPU（2026-08-13、cacafly-poc、零失敗）：
#     pro    8→10.3  16→26.1  32→46.5  64→80.7 次/分
#     flash  8→67.8 次/分（來自 200 筆規則層實跑）
CALLS_PER_WORKER_MIN = {"pro": 1.4, "flash": 8.5}
USD = {"pro": 0.005, "flash": 0.0008}


def estimate(n: int, with_judge: bool, workers: int | None = None) -> tuple[float, float]:
    """回傳 (預估分鐘, 預估美金)。先讓人看到代價再決定要不要跑。

    用「每 worker 吞吐 × 並行度」估算，而不是「單次延遲 ÷ 並行度」——
    後者算出來的 200 筆是 45 分鐘，實跑卻要 92 分鐘，差一倍。
    併發下的單次延遲遠高於單獨呼叫時量到的。
    """
    workers = workers or config.MAX_WORKERS
    flash_calls = n * len(prompts.PROMPT_VERSIONS)
    pro_calls = (n + int(flash_calls * 0.95)) if with_judge else 0

    mins = flash_calls / (CALLS_PER_WORKER_MIN["flash"] * workers)
    if pro_calls:
        mins += pro_calls / (CALLS_PER_WORKER_MIN["pro"] * workers)
    return mins, pro_calls * USD["pro"] + flash_calls * USD["flash"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 筆（試跑用）")
    ap.add_argument("--no-judge", action="store_true", help="只跑規則層，不呼叫評審模型")
    ap.add_argument("--yes", action="store_true", help="跳過確認直接執行")
    ap.add_argument(
        "--workers", type=int, default=None,
        help=f"並行度（預設 {config.MAX_WORKERS}）。實測到 64 都還沒撞配額，想更快就調高。",
    )
    ap.add_argument(
        "--record", action="store_true",
        help="把這次的真實輸出錄下來，之後可零網路重播（存到 data/eval_fixtures.json）",
    )
    args = ap.parse_args()
    if args.workers:
        config.MAX_WORKERS = args.workers
    if args.record:
        config.RECORD_FIXTURES = True

    path = DATA / "eval_products.json"
    if not path.exists():
        print("找不到 eval_products.json，請先執行：")
        print("  uv run python poc/data/build_eval_set.py")
        return 1

    products = json.loads(path.read_text(encoding="utf-8"))["products"]
    if args.limit:
        products = products[: args.limit]
    banned = json.loads((DATA / "banned_terms.json").read_text(encoding="utf-8"))

    with_judge = not args.no_judge
    mins, usd = estimate(len(products), with_judge, config.MAX_WORKERS)
    print("=" * 66)
    print(f"評測集 {len(products)} 筆　評審層 {'開啟' if with_judge else '關閉'}")
    print(f"預估耗時 {mins:.0f} 分鐘　預估成本 約 US${usd:.2f}（NT${usd * 32:.0f}）")
    print(f"並行度 MAX_WORKERS={config.MAX_WORKERS}")
    print("=" * 66)

    if with_judge and not args.yes:
        try:
            answer = input("確定要跑嗎？[y/N] ").strip().lower()
        except EOFError:
            # 非互動環境（Colab 的 !python、CI、管線）讀不到 stdin。
            # 這時不能當成「同意」—— 預設不花錢，要明確加 --yes。
            print("\n偵測到非互動環境，已取消。要直接執行請加 --yes。")
            return 0
        if answer != "y":
            print("已取消。可加 --limit 10 先試跑，或 --no-judge 只跑規則層。")
            return 0

    client = generation.make_client()
    ledger = generation.UsageLedger()
    versions = list(prompts.PROMPT_VERSIONS)
    t_start = time.time()

    # ---------------------------------------------------------------- 生成
    print("\n[1/3] 生成文案")
    jobs = [(p, v) for p in products for v in versions]

    def _gen(job):
        product, version = job
        prompt = prompts.PROMPT_VERSIONS[version](
            product,
            banned_terms=prompts.get_banned_terms_for(product, banned),
            tone_examples=prompts.TONE_EXAMPLES.get(product["brand"]),
        )
        res = generation.generate(
            client, prompt, structured=(version in prompts.STRUCTURED_VERSIONS)
        )
        ledger.record(f"gen:{version}", res.usage)
        return (product["sku"], version), res.text

    outputs = dict(generation.run_parallel(_gen, jobs, label="生成"))

    # ------------------------------------------------------------ 規則層
    print("\n[2/3] 規則層（免費、毫秒級）")
    rule_results = [
        rules.evaluate_rules(
            outputs[(p["sku"], v)], p, v, prompts.get_banned_terms_for(p, banned)
        )
        for p in products
        for v in versions
    ]
    print(report.render_text_table(rule_results))

    rubric_reports: list = []
    rubric_sets: dict = {}
    if with_judge:
        # -------------------------------------------------------- 評審層
        print("\n[3/3] 評審層")
        rubric_sets = dict(
            generation.run_parallel(
                lambda p: (p["sku"], judge.generate_rubrics(client, p, ledger)),
                products,
                label="產生 rubric",
            )
        )
        by_key = {(r.sku, r.version): r for r in rule_results}
        # 評測一律全部送審，分母才會一致（見 judge.should_judge_for_eval 的說明）
        to_judge = [(p, v) for p in products for v in versions]
        would_skip = sum(
            1 for p in products for v in versions
            if not judge.should_judge(by_key[(p["sku"], v)])
        )
        total = len(products) * len(versions)
        print(f"  送審 {len(to_judge)}／{total} 筆（評測全送，分母才一致）")
        print(f"  參考：生產環境會擋下其中 {would_skip} 筆，省 {would_skip / total * 100:.0f}% 評審成本；"
              f"評測時不值得為此犧牲可比性")
        rubric_reports = generation.run_parallel(
            lambda job: judge.check_against_rubrics(
                client, outputs[(job[0]["sku"], job[1])],
                rubric_sets[job[0]["sku"]], job[1], ledger
            ),
            to_judge,
            label="評審",
        )

    # ------------------------------------------------------------ 結論
    elapsed = time.time() - t_start
    summary = judge.summarize_rubrics(rubric_reports, total_items=len(products)) if with_judge else {}

    print("\n" + "=" * 66)
    print(f"完成，耗時 {elapsed / 60:.1f} 分鐘")
    print("=" * 66)

    if with_judge:
        import pandas as pd

        print("\n【評審層】")
        print(pd.DataFrame(summary).T.to_string())
        print("\n" + report.PARSER_CAVEAT)
        print("\n" + report.render_paired(rubric_reports, versions))
        print("\n" + report.significance_note(len(products), 7))

        print("\n【最常沒過的判準】")
        for criterion, n in judge.most_common_failures(rubric_reports, rubric_sets, limit=8):
            print(f"  {n:>4} 次 — {criterion[:56]}")

    print("\n【成本】")
    print(ledger.summary())

    RESULTS.write_text(
        json.dumps(
            {
                "商品數": len(products),
                "版本": versions,
                "耗時秒": round(elapsed, 1),
                "規則層": report.build_table(rule_results),
                "評審層": summary,
                "成本USD": round(ledger.total_cost_usd(), 4),
                "設定": {
                    "GEN_MODEL": config.GEN_MODEL,
                    "JUDGE_MODEL": config.JUDGE_MODEL,
                    "MAX_WORKERS": config.MAX_WORKERS,
                },
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n✓ 結果已寫入 {RESULTS.relative_to(RESULTS.parents[2])}")

    if args.record:
        fixtures = client.dump()
        out = DATA / "eval_fixtures.json"
        out.write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
        print(
            f"✓ 已錄製 {len(fixtures['calls']):,} 筆呼叫 → {out.relative_to(out.parents[2])}"
            f"（{out.stat().st_size / 1024 / 1024:.1f} MB）"
        )
        print("  之後可用 OFFLINE_MODE 零網路重播這次的評測。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
