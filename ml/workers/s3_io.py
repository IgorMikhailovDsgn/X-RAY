"""S3-доступ для GPU-worker'а (Phase 8).

Worker качает манифест + crop'ы и заливает веса напрямую в S3 (boto3 уже в
зависимостях). Креды берём из env — те же имена, что у server'а
(S3_ENDPOINT_URL/S3_ACCESS_KEY/S3_SECRET_KEY/S3_REGION), плюс S3_BUCKET_MODELS/
S3_PREFIX_MODELS для заливки весов. boto3-клиент ленивый: импортируется и
строится только при первом обращении, чтобы import модуля был дешёвым.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"{key} is required for S3 access in GPU-worker")
    return value


@lru_cache(maxsize=1)
def _client() -> Any:
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=_require_env("S3_ENDPOINT_URL"),
        aws_access_key_id=_require_env("S3_ACCESS_KEY"),
        aws_secret_access_key=_require_env("S3_SECRET_KEY"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        # path-style — как на server'е (TimeWebCloud bucket-UUID не лезет в
        # virtual-host субдомен).
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """`s3://bucket/key/with/slashes` → ('bucket', 'key/with/slashes')."""
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Not an s3:// URI: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def download_json(uri: str) -> dict[str, Any]:
    bucket, key = parse_s3_uri(uri)
    obj = _client().get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def download_file(uri: str, dest: Path) -> Path:
    bucket, key = parse_s3_uri(uri)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(bucket, key, str(dest))
    return dest


def upload_file(
    local_path: Path, bucket: str, key: str, content_type: str = "application/octet-stream"
) -> str:
    _client().upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"s3://{bucket}/{key}"


def models_bucket_and_prefix() -> tuple[str, str]:
    """Bucket + prefix для заливки весов. Совпадает с server-side раскладкой."""
    return _require_env("S3_BUCKET_MODELS"), os.environ.get("S3_PREFIX_MODELS", "")
