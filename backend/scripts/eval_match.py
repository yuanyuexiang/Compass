"""匹配精排评测：支持多企业画像，并同时评估逐条分类与 Top-K 排序质量。

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
from collections import Counter, defaultdict
from types import SimpleNamespace

from app.matching.engine import build_match_input, llm_rerank
from app.matching.profiles import build_summary_text

POSITIVE_STAR = 4
DEFAULT_TOKEN_BUDGET = 100_000


def load_golden(path: str) -> tuple[dict[str, dict], list[dict]]:
    """读取新旧两种黄金集；旧格式自动归入 default 画像。"""
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    profiles = {
        str(r.get("profile_id") or r.get("id") or "default"): r["data"]
        for r in rows
        if r["kind"] == "profile"
    }
    if not profiles:
        raise ValueError("黄金集至少需要一条 kind=profile 记录")
    items = [r for r in rows if r["kind"] == "golden"]
    fallback = next(iter(profiles))
    for item in items:
        item.setdefault("profile_id", fallback)
        if item["profile_id"] not in profiles:
            raise ValueError(f"样本 #{item.get('seq')} 引用了未知画像 {item['profile_id']}")
    return profiles, items


def ranking_metrics(results: list[dict], k: int) -> dict[str, float | int]:
    """按每个企业分别取 Top-K，再做宏平均，避免大样本企业支配指标。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        groups[str(row.get("profile_id") or "default")].append(row)
    precisions: list[float] = []
    recalls: list[float] = []
    for rows in groups.values():
        ranked = sorted(rows, key=lambda r: r["got_score"], reverse=True)
        top = ranked[:k]
        positives = sum(r["expected_star"] >= POSITIVE_STAR for r in rows)
        hits = sum(r["expected_star"] >= POSITIVE_STAR for r in top)
        precisions.append(hits / len(top) if top else 0.0)
        if positives:
            recalls.append(hits / positives)
    return {
        f"precision_at_{k}": sum(precisions) / len(precisions) if precisions else 0.0,
        f"recall_at_{k}": sum(recalls) / len(recalls) if recalls else 0.0,
    }


def calculate_metrics(results: list[dict]) -> dict:
    if not results:
        return {"n": 0}
    diffs = [abs(r["got_star"] - r["expected_star"]) for r in results]
    metrics = {
        "n": len(results),
        "profiles": len({r.get("profile_id", "default") for r in results}),
        "star_exact": sum(d == 0 for d in diffs) / len(results),
        "star_within_1": sum(d <= 1 for d in diffs) / len(results),
        "star_mae": sum(diffs) / len(results),
        "advice_exact": sum(
            r["got_advice"] == r["expected_advice"] for r in results
        ) / len(results),
        "positive_count": sum(r["expected_star"] >= POSITIVE_STAR for r in results),
        "high_value_missed": sum(
            r["expected_star"] >= POSITIVE_STAR and r["got_star"] < POSITIVE_STAR
            for r in results
        ),
    }
    metrics.update(ranking_metrics(results, 10))
    metrics.update(ranking_metrics(results, 20))
    return metrics


def dataset_summary(items: list[dict]) -> dict:
    return {
        "profiles": len({i["profile_id"] for i in items}),
        "samples": len(items),
        "stars": dict(sorted(Counter(i["expected_star"] for i in items).items())),
        "positive_count": sum(i["expected_star"] >= POSITIVE_STAR for i in items),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="evals/golden.jsonl")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--token-budget",
        type=int,
        default=DEFAULT_TOKEN_BUDGET,
        help="本次评测成功响应的 Token 上限，默认 100000；<=0 表示不限",
    )
    args = ap.parse_args()

    profiles, items = load_golden(args.golden)
    if args.limit:
        items = items[: args.limit]
    print("黄金集体检：" + json.dumps(dataset_summary(items), ensure_ascii=False))

    results = []
    used_tokens = 0

    def record_usage(usage) -> None:
        nonlocal used_tokens
        if usage is not None:
            used_tokens += int(getattr(usage, "total_tokens", 0) or 0)

    for i, it in enumerate(items, 1):
        if args.token_budget > 0 and used_tokens >= args.token_budget:
            print(f"Token 预算已用完（{used_tokens}/{args.token_budget}），停止后续样本")
            break
        profile_data = profiles[it["profile_id"]]
        profile = SimpleNamespace(data=profile_data, summary_text=build_summary_text(profile_data))
        ann = SimpleNamespace(
            title=it["announcement"]["title"],
            clean_text=it["announcement"].get("clean_text"),
        )
        project = SimpleNamespace(
            fields=it["project"].get("fields") or {},
            category=it["project"].get("category") or {},
            summary=it["project"].get("summary") or "",
        )
        card = llm_rerank(
            build_match_input(project, ann, profile),
            scene="match_eval",
            usage_callback=record_usage,
        )
        results.append(
            {
                "seq": it["seq"],
                "profile_id": it["profile_id"],
                "title": it["announcement"]["title"][:40],
                "expected_star": it["expected_star"],
                "expected_advice": it["expected_advice"],
                "got_star": card.star,
                "got_score": card.match_score,
                "got_advice": card.advice,
                "dimensions": {
                    key: value.model_dump() for key, value in card.dimensions.items()
                },
                "fit_level": card.fit_level,
                "qualification_status": card.qualification_status,
                "delivery_mode": card.delivery_mode,
            }
        )
        print(
            f"[{i}/{len(items)}] #{it['seq']} 期望{it['expected_star']}星 "
            f"→ 实际{card.star}星({card.match_score:.0f}) {card.advice} | {ann.title[:32]} "
            f"| 累计 {used_tokens} tokens"
        )

    out = pathlib.Path(f"evals/results_{args.tag}.jsonl")
    out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8"
    )

    metrics = calculate_metrics(results)
    print(f"\n===== {args.tag} 评测报告（{metrics['n']} 条）=====")
    print(f"星级完全一致: {metrics['star_exact']:.0%}")
    print(f"星级偏差≤1:   {metrics['star_within_1']:.0%}")
    print(f"星级平均偏差: {metrics['star_mae']:.2f}")
    print(f"建议一致率:   {metrics['advice_exact']:.0%}")
    print(f"Precision@10: {metrics['precision_at_10']:.0%}")
    print(f"Recall@10:    {metrics['recall_at_10']:.0%}")
    print(f"Precision@20: {metrics['precision_at_20']:.0%}")
    print(f"Recall@20:    {metrics['recall_at_20']:.0%}")
    print(f"高价值漏报:   {metrics['high_value_missed']}/{metrics['positive_count']}")
    metrics_path = pathlib.Path(f"evals/metrics_{args.tag}.json")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    worst = sorted(results, key=lambda r: abs(r["got_star"] - r["expected_star"]), reverse=True)
    print("最大偏差样本:")
    for r in worst[:8]:
        print(
            f"  #{r['seq']} 期望{r['expected_star']}→实际{r['got_star']}"
            f"({r['got_advice']}) {r['title']}"
        )


if __name__ == "__main__":
    main()
