"""匹配精排评测：黄金集（evals/golden.jsonl）跑真实 LLM，与人工标注对比出分。

口径与线上完全一致：复用 matching/engine 的 build_match_input + llm_rerank，
只是绕过规则/向量层——评的就是 LLM 评分卡本身。

用法：
    uv run python scripts/eval_match.py --tag v1            # 全量 50 条
    uv run python scripts/eval_match.py --tag v1 --limit 5  # 试跑
结果存 evals/results_<tag>.jsonl，可反复对比不同 tag。
"""

import argparse
import json
import pathlib
from types import SimpleNamespace

from app.matching.engine import build_match_input, llm_rerank
from app.matching.profiles import build_summary_text


def load_golden(path: str) -> tuple[dict, list[dict]]:
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    profile = next(r["data"] for r in rows if r["kind"] == "profile")
    items = [r for r in rows if r["kind"] == "golden"]
    return profile, items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="evals/golden.jsonl")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    profile_data, items = load_golden(args.golden)
    if args.limit:
        items = items[: args.limit]
    profile = SimpleNamespace(data=profile_data, summary_text=build_summary_text(profile_data))

    results = []
    for i, it in enumerate(items, 1):
        ann = SimpleNamespace(
            title=it["announcement"]["title"],
            clean_text=it["announcement"].get("clean_text"),
        )
        project = SimpleNamespace(
            fields=it["project"].get("fields") or {},
            category=it["project"].get("category") or {},
            summary=it["project"].get("summary") or "",
        )
        card = llm_rerank(build_match_input(project, ann, profile))
        results.append(
            {
                "seq": it["seq"],
                "title": it["announcement"]["title"][:40],
                "expected_star": it["expected_star"],
                "expected_advice": it["expected_advice"],
                "got_star": card.star,
                "got_score": card.match_score,
                "got_advice": card.advice,
            }
        )
        print(
            f"[{i}/{len(items)}] #{it['seq']} 期望{it['expected_star']}星 "
            f"→ 实际{card.star}星({card.match_score:.0f}) {card.advice} | {ann.title[:32]}"
        )

    out = pathlib.Path(f"evals/results_{args.tag}.jsonl")
    out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8"
    )

    diffs = [abs(r["got_star"] - r["expected_star"]) for r in results]
    exact = sum(1 for d in diffs if d == 0)
    within1 = sum(1 for d in diffs if d <= 1)
    advice_ok = sum(1 for r in results if r["got_advice"] == r["expected_advice"])
    n = len(results)
    print(f"\n===== {args.tag} 评测报告（{n} 条）=====")
    print(f"星级完全一致: {exact}/{n} ({exact / n:.0%})")
    print(f"星级偏差≤1:   {within1}/{n} ({within1 / n:.0%})")
    print(f"星级平均偏差: {sum(diffs) / n:.2f}")
    print(f"建议一致率:   {advice_ok}/{n} ({advice_ok / n:.0%})")
    worst = sorted(results, key=lambda r: abs(r["got_star"] - r["expected_star"]), reverse=True)
    print("最大偏差样本:")
    for r in worst[:8]:
        print(
            f"  #{r['seq']} 期望{r['expected_star']}→实际{r['got_star']}"
            f"({r['got_advice']}) {r['title']}"
        )


if __name__ == "__main__":
    main()
