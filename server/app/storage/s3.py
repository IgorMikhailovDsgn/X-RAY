import asyncio
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config

from app.config import settings


class S3Client:
    """Тонкая обёртка над boto3 S3.

    boto3 синхронный — методы выполняются через `asyncio.to_thread`.
    Под капотом работает и с MinIO, и с любым S3-совместимым endpoint.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def raw(self) -> Any:
        return self._client

    async def upload_bytes(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
    ) -> str:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return f"s3://{bucket}/{key}"

    async def head_bucket(self, bucket: str) -> None:
        await asyncio.to_thread(self._client.head_bucket, Bucket=bucket)

    async def download_bytes(self, *, bucket: str, key: str) -> bytes:
        def _get() -> bytes:
            obj = self._client.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read()  # type: ignore[no-any-return]
        return await asyncio.to_thread(_get)


def _build_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        # path-style addressing совместим и с MinIO, и с провайдерами вроде
        # TimeWebCloud, у которых имя бакета (часто UUID) не превратишь в валидный
        # virtual-host субдомен. По умолчанию botocore выбирает virtual-host для
        # HTTPS — для нашего multi-провайдерного случая фиксируем path.
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@lru_cache(maxsize=1)
def get_s3_client() -> S3Client:
    return S3Client(_build_client())
