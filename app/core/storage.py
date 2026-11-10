"""Resolve: file storage for attachments. Two interchangeable backends.

    STORAGE_BACKEND=local   files on this server's disk (default)
    STORAGE_BACKEND=s3      Amazon S3 (or any S3-compatible store such as MinIO)

Both expose the same methods, so nothing else in the app changes:
    new_key(ext)                   a random server-made object name
    save(key, chunks) -> size      stream bytes in; partial data is removed on failure
    delete(key)
    exists(key) -> bool
    download(key, filename, type)  LocalFile(path) or Redirect(presigned url)
    read_chunks(key)               stream bytes out (used by migration scripts)

S3 notes
- Files are encrypted at rest (SSE-S3 by default, SSE-KMS when S3_KMS_KEY_ID is set).
- Downloads never expose the bucket: the API checks permission, then redirects to a
  presigned URL that expires after S3_PRESIGN_SECONDS (default 60) and forces
  "download as attachment".
- Credentials: on AWS leave S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY empty and give
  the server an IAM role. Set them only for local development or non-AWS stores.
- Boto3 is synchronous, so every call runs in a worker thread.

Requires: boto3 (S3 only), anyio (installed with FastAPI)
"""
import re
import uuid
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import quote

import anyio

from app.core.config import settings

_KEY_RE = re.compile(r"^[0-9a-f]{32}(\.[a-z0-9]{1,5})?$")
READ_CHUNK = 64 * 1024


@dataclass
class LocalFile:
    path: Path


@dataclass
class Redirect:
    url: str


def content_disposition(filename: str) -> str:
    """'attachment' header that survives non-ASCII names (RFC 6266)."""
    plain = filename.encode("ascii", "ignore").decode().replace('"', "").strip() or "download"
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(filename)}"


def _check_key(key: str) -> str:
    if not _KEY_RE.match(key):
        raise ValueError("invalid storage key")
    return key


def new_key(extension: str) -> str:
    return uuid.uuid4().hex + extension


# ---------------------------------------------------------------------- local
class LocalStorage:
    name = "local"

    def __init__(self, base_dir: str):
        self.base = Path(base_dir).resolve()

    def new_key(self, extension: str) -> str:
        return new_key(extension)

    def path(self, key: str) -> Path:
        return self.base / _check_key(key)

    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> int:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            async with await anyio.open_file(target, "wb") as f:
                async for chunk in chunks:
                    await f.write(chunk)
                    size += len(chunk)
        except BaseException:
            await self.delete(key)
            raise
        return size

    async def delete(self, key: str) -> None:
        await anyio.Path(self.path(key)).unlink(missing_ok=True)

    async def exists(self, key: str) -> bool:
        return await anyio.Path(self.path(key)).exists()

    async def download(self, key: str, filename: str, content_type: str) -> LocalFile:
        return LocalFile(self.path(key))

    async def read_chunks(self, key: str) -> AsyncIterator[bytes]:
        async with await anyio.open_file(self.path(key), "rb") as f:
            while chunk := await f.read(READ_CHUNK):
                yield chunk

    async def size(self, key: str) -> int:
        return (await anyio.Path(self.path(key)).stat()).st_size


# ------------------------------------------------------------------------ S3
class S3Storage:
    name = "s3"
    MIN_PART = 5 * 1024 * 1024  # S3 requires >= 5 MiB for every part except the last

    def __init__(
        self,
        bucket: str,
        *,
        region: str | None = None,
        prefix: str = "",
        endpoint_url: str | None = None,
        kms_key_id: str | None = None,
        presign_seconds: int = 60,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        part_size: int = 8 * 1024 * 1024,
        client: Any = None,
    ):
        if part_size < self.MIN_PART:
            raise ValueError("part_size must be at least 5 MiB")
        self.bucket, self.prefix = bucket, prefix
        self.region, self.endpoint_url = region, endpoint_url
        self.kms_key_id, self.presign_seconds = kms_key_id, presign_seconds
        self.access_key_id, self.secret_access_key = access_key_id, secret_access_key
        self.part_size = part_size
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=self.endpoint_url or None,
                aws_access_key_id=self.access_key_id or None,
                aws_secret_access_key=self.secret_access_key or None,
                config=Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                    s3={"addressing_style": "path" if self.endpoint_url else "auto"},
                ),
            )
        return self._client

    def object_key(self, key: str) -> str:
        return f"{self.prefix}{_check_key(key)}"

    def _sse(self) -> dict:
        if self.kms_key_id:
            return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id}
        return {"ServerSideEncryption": "AES256"}

    @staticmethod
    async def _call(fn, /, **kwargs):
        return await anyio.to_thread.run_sync(partial(fn, **kwargs))

    def new_key(self, extension: str) -> str:
        return new_key(extension)

    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> int:
        """Small files use one PUT. Anything bigger than one part streams as a
        multipart upload, so memory use stays at about one part."""
        okey, c = self.object_key(key), self.client
        buf, size = bytearray(), 0
        upload_id: str | None = None
        parts: list[dict] = []

        async def send_part(data: bytes) -> None:
            number = len(parts) + 1
            resp = await self._call(
                c.upload_part, Bucket=self.bucket, Key=okey, UploadId=upload_id,
                PartNumber=number, Body=data,
            )
            parts.append({"ETag": resp["ETag"], "PartNumber": number})

        try:
            async for chunk in chunks:
                buf += chunk
                size += len(chunk)
                while len(buf) >= self.part_size:
                    if upload_id is None:
                        upload_id = (
                            await self._call(
                                c.create_multipart_upload, Bucket=self.bucket, Key=okey, **self._sse()
                            )
                        )["UploadId"]
                    await send_part(bytes(buf[: self.part_size]))
                    del buf[: self.part_size]
            if upload_id is None:
                await self._call(
                    c.put_object, Bucket=self.bucket, Key=okey, Body=bytes(buf), **self._sse()
                )
            else:
                if buf:
                    await send_part(bytes(buf))
                await self._call(
                    c.complete_multipart_upload, Bucket=self.bucket, Key=okey,
                    UploadId=upload_id, MultipartUpload={"Parts": parts},
                )
        except BaseException:
            if upload_id is not None:  # do not leave billable orphan parts behind
                with anyio.CancelScope(shield=True):
                    try:
                        await self._call(
                            c.abort_multipart_upload, Bucket=self.bucket, Key=okey, UploadId=upload_id
                        )
                    except Exception:
                        pass
            raise
        return size

    async def delete(self, key: str) -> None:
        await self._call(self.client.delete_object, Bucket=self.bucket, Key=self.object_key(key))

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            await self._call(self.client.head_object, Bucket=self.bucket, Key=self.object_key(key))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    async def size(self, key: str) -> int:
        head = await self._call(self.client.head_object, Bucket=self.bucket, Key=self.object_key(key))
        return int(head["ContentLength"])

    async def download(self, key: str, filename: str, content_type: str) -> Redirect:
        url = await self._call(
            self.client.generate_presigned_url,
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.object_key(key),
                "ResponseContentDisposition": content_disposition(filename),
                "ResponseContentType": content_type,
            },
            ExpiresIn=self.presign_seconds,
        )
        return Redirect(url)

    async def read_chunks(self, key: str) -> AsyncIterator[bytes]:
        obj = await self._call(self.client.get_object, Bucket=self.bucket, Key=self.object_key(key))
        body = obj["Body"]
        try:
            while chunk := await anyio.to_thread.run_sync(body.read, READ_CHUNK):
                yield chunk
        finally:
            body.close()


# -------------------------------------------------------------------- factory
def build_local() -> LocalStorage:
    return LocalStorage(settings.upload_dir)


def build_s3() -> S3Storage:
    return S3Storage(
        settings.s3_bucket_name or "",
        region=settings.s3_region,
        prefix=settings.s3_prefix,
        endpoint_url=settings.s3_endpoint_url,
        kms_key_id=settings.s3_kms_key_id,
        presign_seconds=settings.s3_presign_seconds,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )


def build_storage() -> LocalStorage | S3Storage:
    return build_s3() if settings.storage_backend == "s3" else build_local()


# The storage the app uses. Tests (and scripts) replace this attribute.
storage = build_storage()