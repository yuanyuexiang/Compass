"""通知分发：即时提醒 + 每日日报（tech-design.md §7）。

站内信（notifications 表）永远写入作为兜底；外部渠道按订阅配置逐个尝试，
单渠道失败只记日志不影响其他渠道。
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.matching.schemas import RISK_KEYS
from app.models import Announcement, MatchResult, Notification, Project, Subscription

logger = logging.getLogger(__name__)

RISK_LABELS = {
    "brand_restriction": "品牌限制",
    "exclusivity": "排他条件",
    "special_qualification": "特殊资质",
    "insufficient_budget": "预算不足",
    "high_competition": "竞争激烈",
    "rejection_risk": "废标风险",
}


def build_match_message(session: Session, match: MatchResult) -> tuple[str, str]:
    project = session.get(Project, match.project_id)
    ann = session.get(Announcement, project.announcement_id)
    fields = {k: (v or {}).get("value") for k, v in (project.fields or {}).items()}
    hit_risks = [
        RISK_LABELS[k] for k in RISK_KEYS if (match.risks or {}).get(k, {}).get("hit")
    ]
    title = f"{'★' * match.star} 新商机：{ann.title[:40]}"
    lines = [
        f"匹配度 {match.match_score:.0f} 分 | {match.advice}",
        f"预算: {fields.get('budget') or '未知'} | 截止: {fields.get('bid_deadline') or '未知'}",
        f"地区: {fields.get('region') or '未知'} | 采购人: {fields.get('tender_org') or '未知'}",
    ]
    if hit_risks:
        lines.append(f"风险: {'、'.join(hit_risks)}")
    lines.append(f"原文: {ann.url}")
    return title, "\n".join(lines)


def dispatch_match(session: Session, match: MatchResult) -> None:
    """即时提醒：星级达到订阅阈值时推送。站内信必写，外部渠道按配置。"""
    sub = session.scalar(select(Subscription).where(Subscription.tenant_id == match.tenant_id))
    if sub is None or not sub.immediate or match.star < sub.min_star:
        return
    title, body = build_match_message(session, match)
    _deliver(session, match.tenant_id, title, body, sub.channels or {}, match.id)


def dispatch_daily_digest(session: Session, tenant_id: int) -> None:
    """每日日报：昨日以来的推荐汇总。"""
    sub = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    if sub is None or not sub.daily_digest:
        return
    since = func.now() - func.make_interval(0, 0, 0, 1)  # 1 day
    matches = session.scalars(
        select(MatchResult)
        .where(
            MatchResult.tenant_id == tenant_id,
            MatchResult.created_at >= since,
            MatchResult.star >= 3,
        )
        .order_by(MatchResult.star.desc(), MatchResult.match_score.desc())
        .limit(20)
    ).all()
    if not matches:
        return
    lines = []
    for m in matches:
        project = session.get(Project, m.project_id)
        ann = session.get(Announcement, project.announcement_id)
        lines.append(f"{'★' * m.star} [{m.match_score:.0f}分] {ann.title[:45]}")
    title = f"商机日报：今日推荐 {len(matches)} 条"
    _deliver(session, tenant_id, title, "\n".join(lines), sub.channels or {})


def _deliver(
    session: Session,
    tenant_id: int,
    title: str,
    body: str,
    channels: dict,
    related_match_id: int | None = None,
) -> None:
    from app.notify.channels import CHANNELS

    session.add(
        Notification(
            tenant_id=tenant_id, channel="web", title=title, body=body,
            related_match_id=related_match_id,
        )
    )
    for name, sender in CHANNELS.items():
        conf = (channels or {}).get(name) or {}
        if not conf.get("enabled"):
            continue
        try:
            ok = sender(title, body, conf)
            status = "sent" if ok else "skipped"
        except Exception as exc:
            status = "failed"
            logger.warning("通知渠道 %s 发送失败 tenant=%s: %s", name, tenant_id, exc)
        session.add(
            Notification(
                tenant_id=tenant_id, channel=name, title=title, body="",
                related_match_id=related_match_id, read=True, status=status,
            )
        )
