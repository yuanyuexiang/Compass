"""通知渠道适配器（tech-design.md §7）：统一 send(title, body, config) 接口。

- web 渠道由 dispatcher 直接落 notifications 表（必达兜底）；
- 企微/钉钉/飞书走群机器人 webhook；email 走 SMTP；未配置的渠道自动跳过。
"""

import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(title: str, body: str, config: dict) -> bool:
    address = config.get("address")
    if not (settings.smtp_host and address):
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = settings.smtp_user
    msg["To"] = address
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, [address], msg.as_string())
    return True


def send_wecom(title: str, body: str, config: dict) -> bool:
    return _post_webhook(
        config.get("webhook"),
        {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{body}"}},
    )


def send_dingtalk(title: str, body: str, config: dict) -> bool:
    return _post_webhook(
        config.get("webhook"),
        {"msgtype": "markdown", "markdown": {"title": title, "text": f"### {title}\n{body}"}},
    )


def send_feishu(title: str, body: str, config: dict) -> bool:
    return _post_webhook(
        config.get("webhook"),
        {"msg_type": "text", "content": {"text": f"{title}\n{body}"}},
    )


def _post_webhook(url: str | None, payload: dict) -> bool:
    if not url:
        return False
    resp = httpx.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    return True


CHANNELS = {
    "email": send_email,
    "wecom": send_wecom,
    "dingtalk": send_dingtalk,
    "feishu": send_feishu,
}
