"""开发演练脚本：端到端跑一遍「采集 → 入库 → 清洗」。

用法（backend/ 目录下）：
    uv run python scripts/dev_crawl.py --limit 3          # 需要 postgres 已启动
    uv run python scripts/dev_crawl.py --limit 3 --no-db  # 无数据库模式，只打印
"""

import argparse

from sqlalchemy import select


def crawl_no_db(adapter_name: str, limit: int) -> None:
    from app.crawler.base import get_adapter
    from app.parsing.clean import html_to_text

    adapter = get_adapter(adapter_name)
    try:
        items = []
        for raw in adapter.list_announcements():
            items.append(raw)
            if len(items) >= limit:
                break
        for raw in items:
            print(f"\n[{raw.ann_type}] {raw.title}")
            print(f"  发布: {raw.publish_time}  地域: {raw.region}  采购人: {raw.buyer}")
            print(f"  URL: {raw.url}")
        if items:
            text = html_to_text(adapter.fetch_detail(items[0].url), adapter.content_selectors())
            print(f"\n=== 第一条正文清洗结果（前 400 字，共 {len(text)} 字）===\n{text[:400]}")
    finally:
        adapter.close()


def crawl_with_db(adapter_name: str, limit: int) -> None:
    from app.core.db import init_db, session_scope
    from app.models import Announcement, Source
    from app.tasks.pipeline import run_crawl_source, run_fetch_and_clean

    init_db()
    source_name = f"{adapter_name}-dev"
    with session_scope() as session:
        source = session.scalar(select(Source).where(Source.name == source_name))
        if source is None:
            source = Source(name=source_name, adapter=adapter_name, cron="0 * * * *")
            session.add(source)
            session.flush()
        new_ids = run_crawl_source(session, source, limit=limit)
    print(f"新增公告 {len(new_ids)} 条: {new_ids}")

    for ann_id in new_ids:
        with session_scope() as session:
            run_fetch_and_clean(session, ann_id)

    with session_scope() as session:
        for ann_id in new_ids:
            ann = session.get(Announcement, ann_id)
            preview = (ann.clean_text or "")[:60].replace("\n", " ")
            atts = "".join(f"\n      附件[{a.status}] {a.filename}" for a in ann.attachments)
            print(f"  #{ann.id} [{ann.status}] {ann.title[:40]}… 正文: {preview}…{atts}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="ccgp", help="适配器名: ccgp / jsggzy")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--no-db", action="store_true", help="不连数据库，只打印结果")
    args = parser.parse_args()
    if args.no_db:
        crawl_no_db(args.adapter, args.limit)
    else:
        crawl_with_db(args.adapter, args.limit)
