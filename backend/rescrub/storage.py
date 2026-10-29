"""Video storage: a local folder (STORAGE_BACKEND=local) or an S3-compatible bucket such as Vultr Object Storage.

Keys are random (uploads/<uuid>.mp4); raw videos are never served publicly.
"""

import shutil
from pathlib import Path

from .settings import Settings


def parse_range(header: str, size: int) -> tuple[int, int]:
    """'bytes=a-b' | 'bytes=a-' | 'bytes=-n' -> inclusive (start, end). ValueError if unusable."""
    unit, _, spec = header.partition("=")
    if unit.strip() != "bytes" or "," in spec:
        raise ValueError("unsupported range")
    first, _, last = spec.strip().partition("-")
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        n = int(last)
        start, end = max(0, size - n), size - 1
    if start > end or start >= size:
        raise ValueError("range outside the file")
    return start, end


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("bad storage key")
        return p

    def put_file(self, local: Path, key: str, content_type: str = "video/mp4") -> None:
        dest = self.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, dest)

    def get_file(self, key: str, local: Path) -> None:
        shutil.copyfile(self.path(key), local)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def presigned_url(self, key: str) -> str | None:
        return None  # served by the API instead (see /sessions/{id}/annotated.mp4)


class S3Storage:
    def __init__(self, settings: Settings):
        import boto3

        self.bucket = settings.s3_bucket
        self.ttl = settings.presign_ttl_sec
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

    def put_file(self, local: Path, key: str, content_type: str = "video/mp4") -> None:
        self.client.upload_file(str(local), self.bucket, key, ExtraArgs={"ContentType": content_type})

    def get_file(self, key: str, local: Path) -> None:
        self.client.download_file(self.bucket, key, str(local))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def presigned_url(self, key: str) -> str | None:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.ttl
        )

    def stream(self, key: str, range_header: str | None):
        """(status, headers, byte iterator) for an HTTP response, honoring a single `bytes=` range."""
        size = self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        headers = {"Accept-Ranges": "bytes"}
        if not range_header:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
            return 200, {**headers, "Content-Length": str(size)}, obj["Body"].iter_chunks(1024 * 1024)
        start, end = parse_range(range_header, size)
        obj = self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}")
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
        return 206, headers, obj["Body"].iter_chunks(1024 * 1024)


def get_storage(settings: Settings):
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.local_storage_dir)
