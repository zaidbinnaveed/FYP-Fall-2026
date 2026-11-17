"""Signed URLs expire in <= 600 s (NFR-SEC-06) and expired URLs are refused by the server."""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.adapters.storage import StorageAdapter
from app.core.config import Settings


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_default_expiry_is_at_most_600_seconds(settings: Settings) -> None:
    url = StorageAdapter(settings).presign_get("images/abc.png")
    expires = int(_query(url)["X-Amz-Expires"][0])
    assert 0 < expires <= 600


def test_explicit_shorter_expiry_is_honoured(settings: Settings) -> None:
    url = StorageAdapter(settings).presign_get("images/abc.png", expires_in=120)
    assert _query(url)["X-Amz-Expires"] == ["120"]


@pytest.mark.parametrize("ttl", [601, 3600, 0, -1])
def test_out_of_range_expiry_is_refused(settings: Settings, ttl: int) -> None:
    with pytest.raises(ValueError, match="600"):
        StorageAdapter(settings).presign_get("images/abc.png", expires_in=ttl)


def test_url_is_signed_for_the_public_endpoint(settings: Settings) -> None:
    url = StorageAdapter(settings).presign_get("images/abc.png")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}" == settings.storage_public_endpoint_url
    assert parsed.path == f"/{settings.storage_bucket}/images/abc.png"
    assert _query(url)["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]


# --- Integration: a real S3-compatible server (SeaweedFS in CI) --------------------------------

INTEGRATION_ENDPOINT = os.environ.get("STORAGE_INTEGRATION_ENDPOINT_URL")


@pytest.fixture
def live_adapter(monkeypatch: pytest.MonkeyPatch) -> StorageAdapter:
    if not INTEGRATION_ENDPOINT:
        pytest.skip("STORAGE_INTEGRATION_ENDPOINT_URL not set")
    monkeypatch.setenv("STORAGE_ENDPOINT_URL", INTEGRATION_ENDPOINT)
    monkeypatch.setenv("STORAGE_PUBLIC_ENDPOINT_URL", INTEGRATION_ENDPOINT)
    for key in ("STORAGE_ACCESS_KEY_ID", "STORAGE_SECRET_ACCESS_KEY", "STORAGE_BUCKET"):
        value = os.environ.get(f"INTEGRATION_{key}")
        if value:
            monkeypatch.setenv(key, value)
    adapter = StorageAdapter(Settings())  # type: ignore[call-arg]
    adapter.ensure_bucket()
    return adapter


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - test URL
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.mark.integration
def test_live_signed_url_works_then_expires(live_adapter: StorageAdapter) -> None:
    key = f"tests/{uuid.uuid4()}.txt"
    live_adapter.put_object(key, b"oscc", "text/plain")
    url = live_adapter.presign_get(key, expires_in=2)
    assert _status(url) == 200
    time.sleep(4)
    assert _status(url) == 403


@pytest.mark.integration
def test_live_unsigned_and_tampered_urls_rejected(live_adapter: StorageAdapter) -> None:
    key = f"tests/{uuid.uuid4()}.txt"
    live_adapter.put_object(key, b"oscc", "text/plain")
    url = live_adapter.presign_get(key, expires_in=60)
    assert _status(url.split("?")[0]) == 403  # bucket is private
    tampered = url.replace("X-Amz-Expires=60", "X-Amz-Expires=600")
    assert _status(tampered) == 403
