"""在 200 筆評測集上跑完整流程，產出可引用的統計結論。

## 這支跟 notebook 的分工

- **notebook（12 筆）**：台上跑的 demo。要快、要看得懂、要能內嵌成單一檔案。
- **這支（200 筆）**：離線跑的評測。用來回答「v2 和 v3 的差別是真的還是雜訊」。

12 筆時翻轉一次檢查就是 1.2 個百分點，小幅差距完全分不出是不是雜訊。
200 筆才有辦法做這種比較。這也是真實團隊的作法：demo 給人看流程，
結論來自夠大的評測集。

## 用法

    uv run python poc/run_eval.py --limit 10     # 先小量試跑，確認流程沒問題
    uv run python poc/run_eval.py                # 全量 200 筆（約 45 分鐘）
    uv run python poc/run_eval.py --no-judge     # 只跑規則層（免費、幾秒鐘）

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

PRO_SEC, PRO_USD = 20.0, 0.005   # 實測 gemini-2.5-pro：15–26 秒、約 US$0.005/次
FLASH_SEC, FLASH_USD = 3.0, 0.0008


def estimate(n: int, with_judge: bool) -> tuple[float, float]:
    """回傳 (預估分鐘, 預估美金)。先讓人看到代價再決定要不要跑。"""
    gen_calls = n * len(prompts.PROMPT_VERSIONS)
    pro_calls = (n + int(gen_calls * 0.95)) if with_judge else 0
    secs = (pro_calls * PRO_SEC + gen_calls * FLASH_SEC) / config.MAX_WORKERS
    usd = pro_calls * PRO_USD + gen_calls * FLASH_USD
    return secs / 60, usd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 筆（試跑用）")
    ap.add_argument("--no-judge", action="store_true", help="只跑規則層，不呼叫評審模型")
    ap.add_argument("--yes", action="store_true", help="跳過確認直接執行")
    args = ap.parse_args()

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
    mins, usd = estimate(len(products), with_judge)
    print("=" * 66)
    print(f"評測集 {len(products)} 筆　評審層 {'開啟' if with_judge else '關閉'}")
    print(f"預估耗時 {mins:.0f} 分鐘　預估成本 約 US${usd:.2f}（NT${usd * 32:.0f}）")
    print(f"並行度 MAX_WORKERS={config.MAX_WORKERS}")
    print("=" * 66)

    if with_judge and not args.yes:
        if input("確定要跑嗎？[y/N] ").strip().lower() != "y":
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
        to_judge = [
            (p, v) for p in products for v in versions if judge.should_judge(by_key[(p["sku"], v)])
        ]
        print(f"  送審 {len(to_judge)}／{len(products) * len(versions)} 筆"
              f"（規則層擋下 {len(products) * len(versions) - len(to_judge)} 筆）")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
