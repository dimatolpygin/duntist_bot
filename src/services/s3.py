"""Заливка файлов в S3-совместимое хранилище (Beget) и получение публичной ссылки.

Используется как fallback для больших файлов, если прямая отправка по file_id не прошла.
boto3 синхронный — вызовы уносим в поток через asyncio.to_thread, чтобы не блокировать loop.
"""
from __future__ import annotations

import asyncio

from ..config import settings
from ..logger import logger


def is_configured() -> bool:
    """S3 настроен, если заданы endpoint, бакет и ключи доступа."""
    return bool(
        settings.s3_endpoint
        and settings.s3_bucket
        and settings.s3_access_key
        and settings.s3_secret_key
    )


def _public_url(key: str) -> str:
    base = (settings.s3_public_base_url or settings.s3_endpoint).rstrip("/")
    # Path-style: <base>/<bucket>/<key>
    return f"{base}/{settings.s3_bucket}/{key}"


def _put_object_sync(key: str, data: bytes, content_type: str | None) -> str:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region or None,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )
    return _public_url(key)


async def upload_bytes(key: str, data: bytes, content_type: str | None = None) -> str:
    """Заливает объект в S3 и возвращает публичную ссылку. Бросает исключение при ошибке."""
    url = await asyncio.to_thread(_put_object_sync, key, data, content_type)
    logger.info(f"☁️ Файл залит в S3: {key} → {url}")
    return url
