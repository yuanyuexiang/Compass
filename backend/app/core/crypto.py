"""敏感配置的对称加密（LLM API Key 入库前加密，防数据库泄露直接裸奔）。

密钥从 jwt_secret 派生：不引入新密钥配置项，换 jwt_secret 会使已存密文失效
（表现为解密返回空串，管理员重填即可）。显示层一律用 mask()，接口永不回传明文。
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "enc:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain: str) -> str:
    return _PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt(stored: str) -> str:
    """解密失败（密钥更换/数据损坏）返回空串——调用方按「未配置」处理。"""
    if not stored:
        return ""
    if not stored.startswith(_PREFIX):
        return stored  # 兼容历史明文（若有），下次保存时会转加密
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.warning("密文解密失败（jwt_secret 是否更换过？），按未配置处理")
        return ""


def mask(plain: str) -> str:
    """脱敏展示：只露尾 4 位。"""
    if not plain:
        return ""
    return f"···{plain[-4:]}" if len(plain) > 8 else "···"
