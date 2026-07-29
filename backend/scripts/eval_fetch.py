"""评测集取数：从运行中的实例拉公告+项目结构化字段+画像快照，存 JSONL。

快照化的意义：评测输入固定不变，之后每次改 prompt 都在同一批数据上对比，分数才可比。
只读接口，不写任何数据。

用法：
    uv run python scripts/eval_fetch.py --base https://compass.matrix-net.tech \
        --username jerry --password '***' --limit 120 --out evals/candidates.jsonl
"""

import argparse
import json
import pathlib
import urllib.request


def api(base: str, path: str, token: str | None = None):
    req = urllib.request.Request(f"{base}{path}")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def login(base: str, username: str, password: str) -> str:
    req = urllib.request.Request(f"{base}/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": username, "password": password}).encode()
    with urllib.request.urlopen(req, body, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--out", default="evals/candidates.jsonl")
    args = ap.parse_args()

    token = login(args.base, args.username, args.password)
    profile = api(args.base, "/api/profile", token)

    items: list[dict] = []
    offset = 0
    while len(items) < args.limit:
        page = api(
            args.base,
            f"/api/announcements?limit=100&offset={offset}&all_regions=true",
            token,
        )
        batch = page.get("items") or []
        if not batch:
            break
        items.extend(batch)
        offset += 100
    items = items[: args.limit]

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "profile", "data": profile}, ensure_ascii=False) + "\n")
        for it in items:
            detail = api(args.base, f"/api/projects/{it['id']}", token)
            project = detail.get("project")
            if not project:  # 未完成 AI 提取的公告不进评测集
                continue
            f.write(
                json.dumps(
                    {
                        "kind": "candidate",
                        "announcement": detail["announcement"],
                        "project": project,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            kept += 1
    print(f"snapshot: {kept} candidates (+1 profile) -> {out}")


if __name__ == "__main__":
    main()
