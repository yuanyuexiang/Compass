"""存量公告发布时间时区修正（一次性）。

历史缺陷：适配器解析出的北京时间没带时区，入 timestamptz 列被当成 UTC，
展示整体 +8 小时。新数据已在入库时归一（crawler/base.ensure_cst），
本脚本把存量值回拨 8 小时还原为真实 UTC。

以 system_settings 标志防重复执行（回拨两次会变 -8），deploy.sh 每次跑也安全。
用法：uv run python scripts/fix_publish_tz.py
"""

from sqlalchemy import text

from app.core.db import session_scope
from app.core.kv import get_setting, set_setting

FLAG_KEY = "publish_time_tz_fixed"


def main() -> None:
    with session_scope() as session:
        if get_setting(session, FLAG_KEY):
            print("publish_time timezone already fixed, skip")
            return
        n = session.execute(
            text(
                "UPDATE announcements SET publish_time = publish_time - interval '8 hours' "
                "WHERE publish_time IS NOT NULL"
            )
        ).rowcount
        set_setting(session, FLAG_KEY, "1")
        print(f"shifted publish_time -8h for {n} announcements")


if __name__ == "__main__":
    main()
