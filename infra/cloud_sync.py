"""Cloud object-store sync stub for strategy + parquet snapshots.

Three providers are wired through one interface:

- ``s3``    : AWS S3 via lazy ``boto3``
- ``gcs``   : Google Cloud Storage via lazy ``google.cloud.storage``
- ``azure`` : Azure Blob via lazy ``azure.storage.blob``

The default ``mock=True`` mode performs all I/O against the local
filesystem so unit tests never touch a real cloud account. Real
credentials are read from standard SDK env vars only when ``mock=False``.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Optional


_VALID_PROVIDERS = {"s3", "gcs", "azure"}


@dataclass
class CloudConfig:
    """Static config for :class:`CloudSync`.

    Attributes:
        provider: ``"s3"``, ``"gcs"`` or ``"azure"``.
        bucket: bucket / container name.
        prefix: optional key prefix (``""`` = root).
        region: provider region; ignored for GCS / Azure.
        mock_root: when ``mock=True``, local directory used as fake bucket.
    """
    provider: str = "s3"
    bucket: str = "quantforge"
    prefix: str = ""
    region: str = "us-east-1"
    mock_root: Optional[str] = None


class CloudSync:
    """Push/pull strategy + parquet artifacts to S3/GCS/Azure.

    The class deliberately exposes a small surface (upload / download /
    list / delete). Higher-level snapshot helpers compose these.
    """

    def __init__(self, config: Optional[CloudConfig] = None) -> None:
        self.config = config or CloudConfig()
        if self.config.provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"provider must be one of {sorted(_VALID_PROVIDERS)}, "
                f"got {self.config.provider!r}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def upload(self, local_path: str, remote_key: str, *, mock: bool = True) -> str:
        """Upload ``local_path`` to ``remote_key``. Returns the full remote URI."""
        if not os.path.exists(local_path):
            raise FileNotFoundError(local_path)
        key = self._with_prefix(remote_key)
        if mock:
            dst = self._mock_path(key)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copy2(local_path, dst)
            return self._uri(key)
        self._provider_upload(local_path, key)
        return self._uri(key)

    def download(self, remote_key: str, local_path: str, *, mock: bool = True) -> str:
        """Download ``remote_key`` to ``local_path``. Returns ``local_path``."""
        key = self._with_prefix(remote_key)
        parent = os.path.dirname(local_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if mock:
            src = self._mock_path(key)
            if not os.path.exists(src):
                raise FileNotFoundError(self._uri(key))
            shutil.copy2(src, local_path)
            return local_path
        self._provider_download(key, local_path)
        return local_path

    def list_keys(self, prefix: str = "", *, mock: bool = True) -> list[str]:
        """List remote keys under ``prefix`` (relative to config.prefix)."""
        full_prefix = self._with_prefix(prefix)
        if mock:
            root = self._mock_path("")
            if not os.path.isdir(root):
                return []
            keys: list[str] = []
            for dp, _, files in os.walk(root):
                for f in files:
                    rel = os.path.relpath(os.path.join(dp, f), root)
                    rel_posix = rel.replace(os.sep, "/")
                    if rel_posix.startswith(full_prefix):
                        keys.append(rel_posix)
            return sorted(keys)
        return self._provider_list(full_prefix)

    def delete(self, remote_key: str, *, mock: bool = True) -> bool:
        """Delete ``remote_key``. Returns True if deleted, False if missing."""
        key = self._with_prefix(remote_key)
        if mock:
            path = self._mock_path(key)
            if not os.path.exists(path):
                return False
            os.remove(path)
            return True
        return self._provider_delete(key)

    def sync_strategy_snapshot(
        self,
        snapshot_dir: str,
        version: str,
        *,
        mock: bool = True,
    ) -> list[str]:
        """Upload every file in ``snapshot_dir`` under ``versions/<version>/``."""
        if not os.path.isdir(snapshot_dir):
            raise NotADirectoryError(snapshot_dir)
        uris: list[str] = []
        for dp, _, files in os.walk(snapshot_dir):
            for f in files:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, snapshot_dir).replace(os.sep, "/")
                key = f"versions/{version}/{rel}"
                uris.append(self.upload(full, key, mock=mock))
        return uris

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _with_prefix(self, key: str) -> str:
        prefix = self.config.prefix.strip("/")
        key = key.lstrip("/")
        if not prefix:
            return key
        return f"{prefix}/{key}" if key else prefix

    def _mock_root(self) -> str:
        if self.config.mock_root:
            return self.config.mock_root
        # Default mock root sits under the package's data cache so it does
        # not pollute the real cwd unintentionally.
        return os.path.join(
            os.path.dirname(__file__), "..", "data_cache_qf", "_cloud_mock",
            self.config.provider, self.config.bucket,
        )

    def _mock_path(self, key: str) -> str:
        root = os.path.normpath(self._mock_root())
        os.makedirs(root, exist_ok=True)
        return os.path.normpath(os.path.join(root, key))

    def _uri(self, key: str) -> str:
        if self.config.provider == "s3":
            return f"s3://{self.config.bucket}/{key}"
        if self.config.provider == "gcs":
            return f"gs://{self.config.bucket}/{key}"
        return f"azure://{self.config.bucket}/{key}"

    # --- provider-specific real I/O paths (no test coverage) ---

    def _provider_upload(self, local_path: str, key: str) -> None:  # pragma: no cover
        if self.config.provider == "s3":
            import boto3

            client = boto3.client("s3", region_name=self.config.region)
            client.upload_file(local_path, self.config.bucket, key)
        elif self.config.provider == "gcs":
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(self.config.bucket)
            bucket.blob(key).upload_from_filename(local_path)
        elif self.config.provider == "azure":
            from azure.storage.blob import BlobServiceClient

            conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            svc = BlobServiceClient.from_connection_string(conn)
            blob = svc.get_blob_client(container=self.config.bucket, blob=key)
            with open(local_path, "rb") as f:
                blob.upload_blob(f, overwrite=True)

    def _provider_download(self, key: str, local_path: str) -> None:  # pragma: no cover
        if self.config.provider == "s3":
            import boto3

            client = boto3.client("s3", region_name=self.config.region)
            client.download_file(self.config.bucket, key, local_path)
        elif self.config.provider == "gcs":
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(self.config.bucket)
            bucket.blob(key).download_to_filename(local_path)
        elif self.config.provider == "azure":
            from azure.storage.blob import BlobServiceClient

            conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            svc = BlobServiceClient.from_connection_string(conn)
            blob = svc.get_blob_client(container=self.config.bucket, blob=key)
            with open(local_path, "wb") as f:
                f.write(blob.download_blob().readall())

    def _provider_list(self, prefix: str) -> list[str]:  # pragma: no cover
        if self.config.provider == "s3":
            import boto3

            client = boto3.client("s3", region_name=self.config.region)
            resp = client.list_objects_v2(Bucket=self.config.bucket, Prefix=prefix)
            return [o["Key"] for o in resp.get("Contents", [])]
        if self.config.provider == "gcs":
            from google.cloud import storage

            client = storage.Client()
            return [b.name for b in client.list_blobs(self.config.bucket, prefix=prefix)]
        if self.config.provider == "azure":
            from azure.storage.blob import BlobServiceClient

            conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            svc = BlobServiceClient.from_connection_string(conn)
            cc = svc.get_container_client(self.config.bucket)
            return [b.name for b in cc.list_blobs(name_starts_with=prefix)]
        return []

    def _provider_delete(self, key: str) -> bool:  # pragma: no cover
        if self.config.provider == "s3":
            import boto3

            client = boto3.client("s3", region_name=self.config.region)
            client.delete_object(Bucket=self.config.bucket, Key=key)
            return True
        if self.config.provider == "gcs":
            from google.cloud import storage

            client = storage.Client()
            client.bucket(self.config.bucket).blob(key).delete()
            return True
        if self.config.provider == "azure":
            from azure.storage.blob import BlobServiceClient

            conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            svc = BlobServiceClient.from_connection_string(conn)
            svc.get_blob_client(container=self.config.bucket, blob=key).delete_blob()
            return True
        return False
