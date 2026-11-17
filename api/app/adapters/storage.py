"""S3-compatible object storage adapter (SDS: private storage, signed URLs <= 10 min).

Two clients are kept: one for server-to-storage traffic (internal Docker hostname) and one that
signs URLs for the *public* endpoint. SigV4 signatures cover the host, so a URL must be signed
for the host the browser will actually call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import MAX_SIGNED_URL_TTL_SECONDS, Settings

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


class StorageError(RuntimeError):
    """Raised when the storage backend is unreachable or misconfigured."""


def _client(settings: Settings, endpoint_url: str) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=settings.storage_region,
        aws_access_key_id=settings.storage_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.storage_secret_access_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=settings.readiness_timeout_seconds,
            read_timeout=10,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


class StorageAdapter:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.storage_bucket
        self._default_ttl = settings.storage_signed_url_ttl_seconds
        self._client = _client(settings, settings.storage_endpoint_url)
        self._signer = _client(settings, settings.storage_public_endpoint_url)

    @property
    def bucket(self) -> str:
        return self._bucket

    def presign_get(self, key: str, expires_in: int | None = None) -> str:
        """Return a signed GET URL. Expiry is capped at 600 s (NFR-SEC-06); larger values fail."""
        ttl = self._default_ttl if expires_in is None else expires_in
        if not 0 < ttl <= MAX_SIGNED_URL_TTL_SECONDS:
            raise ValueError(
                f"signed URL expiry must be between 1 and {MAX_SIGNED_URL_TTL_SECONDS} seconds"
            )
        return self._signer.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=ttl
        )

    def put_object(self, key: str, data: bytes, content_type: str) -> str:
        """Store bytes privately and return the ``s3://bucket/key`` URI."""
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return f"s3://{self._bucket}/{key}"

    def ping(self) -> None:
        """Readiness probe: the bucket exists and the credentials work."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            raise StorageError(f"bucket check failed: {exc.response['Error'].get('Code')}") from exc
        except Exception as exc:
            raise StorageError(f"storage unreachable: {type(exc).__name__}") from exc

    def ensure_bucket(self) -> bool:
        """Create the private bucket if it does not exist. Returns True if it was created."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return False
        except ClientError as exc:
            if exc.response["Error"].get("Code") not in {"404", "NoSuchBucket", "NotFound"}:
                raise StorageError(
                    f"bucket check failed: {exc.response['Error'].get('Code')}"
                ) from exc
        except Exception as exc:
            raise StorageError(f"storage unreachable: {type(exc).__name__}") from exc
        try:
            self._client.create_bucket(Bucket=self._bucket)
        except Exception as exc:
            raise StorageError(f"bucket creation failed: {type(exc).__name__}") from exc
        return True
