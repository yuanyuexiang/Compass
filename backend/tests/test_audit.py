"""日志功能单测：操作日志/运行日志写入、脱敏约定、IP 提取。"""

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.audit import audit_log_dict, client_ip, record_audit, record_event, system_event_dict
from app.core.security import CurrentUser
from app.models import AuditLog, SystemEvent, User


def _session() -> Session:
    engine = create_engine("sqlite://")
    for table in (AuditLog.__table__, SystemEvent.__table__, User.__table__):
        table.create(engine)
    return Session(engine)


def test_record_audit_with_user_snapshot():
    with _session() as session:
        session.add(
            User(id=7, tenant_id=3, username="alice", password_hash="x", role="tenant_admin")
        )
        session.commit()
        record_audit(
            session, CurrentUser(7, 3, "tenant_admin"), "profile.save",
            target="profile:3", detail={"changed": ["regions"]}, ip="1.2.3.4",
        )
        session.commit()
        row = session.scalar(select(AuditLog))
        assert row.username == "alice"  # 用户名快照：删除用户后日志仍可读
        assert row.tenant_id == 3 and row.user_id == 7
        assert row.action == "profile.save" and row.detail == {"changed": ["regions"]}
        out = audit_log_dict(row)
        assert out["ip"] == "1.2.3.4" and out["created_at"]


def test_record_audit_anonymous_login_failure():
    """登录失败无登录态：current=None，用 username 参数记尝试者。"""
    with _session() as session:
        record_audit(session, None, "auth.login_failed", username="hacker", ip="5.6.7.8")
        session.commit()
        row = session.scalar(select(AuditLog))
        assert row.user_id is None and row.tenant_id is None
        assert row.username == "hacker" and row.action == "auth.login_failed"


def test_record_event_levels():
    with _session() as session:
        record_event(session, "backpressure.pause", "自动采集暂停", level="warning")
        record_event(session, "crawl.round", "自动采集触发")
        session.commit()
        rows = session.scalars(select(SystemEvent).order_by(SystemEvent.id)).all()
        assert rows[0].level == "warning" and rows[1].level == "info"
        assert system_event_dict(rows[1])["event"] == "crawl.round"


def test_client_ip_prefers_forwarded_header():
    req = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.9"  # Traefik 反代取首个真实来源
    direct = SimpleNamespace(headers={}, client=SimpleNamespace(host="192.168.1.5"))
    assert client_ip(direct) == "192.168.1.5"
    no_client = SimpleNamespace(headers={}, client=None)
    assert client_ip(no_client) is None
