"""对象存储（MinIO，S3 协议）：附件原文件落盘（tech-design.md §3，已确认）。"""

import io
import logging

from minio import Minio

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        if not _client.bucket_exists(settings.minio_bucket):
            _client.make_bucket(settings.minio_bucket)
    return _client


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str | None:
    """上传字节流，返回 object key；存储不可用时返回 None（不阻塞流水线，
    解析文本已入库，原件可后补）。"""
    try:
        get_client().put_object(
            settings.minio_bucket, key, io.BytesIO(data), len(data), content_type=content_type
        )
        return key
    except Exception as exc:
        logger.warning("MinIO 上传失败 key=%s: %s", key, exc)
        return None
