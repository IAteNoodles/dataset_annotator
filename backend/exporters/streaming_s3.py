from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from backend.config import AppConfig
from backend.database import Database
from backend.exporters.parquet_exporter import ParquetExporter
from backend.exporters.manifest import create_manifest, write_manifest


class S3Exporter:
    def __init__(self, config: AppConfig, db: Database):
        self.config = config
        self.db = db
        self.parquet_exporter = ParquetExporter(db, config)

        s3_config = config.s3
        boto_config = BotoConfig(
            max_pool_connections=10,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )

        session = boto3.Session()

        def _none_if_empty(v):
            return v if v else None

        self.s3 = session.client(
            "s3",
            region_name=s3_config.region,
            endpoint_url=_none_if_empty(getattr(s3_config, "endpoint_url", None)),
            aws_access_key_id=_none_if_empty(getattr(s3_config, "access_key_id", None)),
            aws_secret_access_key=_none_if_empty(getattr(s3_config, "secret_access_key", None)),
            config=boto_config,
        )
        self.bucket = s3_config.bucket
        self.prefix = s3_config.prefix.rstrip("/") + "/"
        self.multipart_threshold = s3_config.multipart_threshold_mb * 1024 * 1024
        self.chunk_size = s3_config.multipart_chunksize_mb * 1024 * 1024

    async def upload_file(self, local_path: Path, s3_key: str) -> dict[str, Any]:
        sha256_hash = hashlib.sha256()
        file_size = local_path.stat().st_size

        if file_size > self.multipart_threshold:
            return await self._multipart_upload(local_path, s3_key, sha256_hash)
        else:
            return await self._simple_upload(local_path, s3_key, sha256_hash, file_size)

    async def _simple_upload(self, local_path: Path, s3_key: str, sha256_hash: hashlib._Hash, file_size: int) -> dict[str, Any]:
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)

        self.s3.upload_file(
            str(local_path),
            self.bucket,
            s3_key,
            ExtraArgs={"Metadata": {"sha256": sha256_hash.hexdigest()}},
        )

        return {
            "s3_key": s3_key,
            "size_bytes": file_size,
            "sha256": sha256_hash.hexdigest(),
        }

    async def _multipart_upload(self, local_path: Path, s3_key: str, sha256_hash: hashlib._Hash) -> dict[str, Any]:
        mpu = self.s3.create_multipart_upload(
            Bucket=self.bucket,
            Key=s3_key,
            Metadata={"sha256": ""},
        )
        upload_id = mpu["UploadId"]
        parts = []

        try:
            with open(local_path, "rb") as f:
                part_number = 1
                while True:
                    chunk = f.read(self.chunk_size)
                    if not chunk:
                        break

                    sha256_hash.update(chunk)

                    with tempfile.NamedTemporaryFile(delete=False) as tmp:
                        tmp.write(chunk)
                        tmp_path = tmp.name

                    try:
                        response = self.s3.upload_part(
                            Bucket=self.bucket,
                            Key=s3_key,
                            PartNumber=part_number,
                            UploadId=upload_id,
                            Body=chunk,
                        )
                        parts.append({
                            "PartNumber": part_number,
                            "ETag": response["ETag"],
                        })
                    finally:
                        os.unlink(tmp_path)

                    part_number += 1

            self.s3.complete_multipart_upload(
                Bucket=self.bucket,
                Key=s3_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

            self.s3.copy_object(
                Bucket=self.bucket,
                CopySource={"Bucket": self.bucket, "Key": s3_key},
                Key=s3_key,
                Metadata={"sha256": sha256_hash.hexdigest()},
                MetadataDirective="REPLACE",
            )

            return {
                "s3_key": s3_key,
                "size_bytes": local_path.stat().st_size,
                "sha256": sha256_hash.hexdigest(),
            }

        except Exception:
            self.s3.abort_multipart_upload(
                Bucket=self.bucket,
                Key=s3_key,
                UploadId=upload_id,
            )
            raise

    async def download_file(self, s3_key: str, local_path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
        local_path.parent.mkdir(parents=True, exist_ok=True)

        self.s3.download_file(self.bucket, s3_key, str(local_path))

        actual_sha256 = hashlib.sha256()
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                actual_sha256.update(chunk)

        actual_sha256_hex = actual_sha256.hexdigest()

        if expected_sha256 and actual_sha256_hex != expected_sha256:
            local_path.unlink(missing_ok=True)
            raise ValueError(f"Checksum mismatch: expected {expected_sha256}, got {actual_sha256_hex}")

        return {
            "local_path": str(local_path),
            "size_bytes": local_path.stat().st_size,
            "sha256": actual_sha256_hex,
        }

    async def list_objects(self, dataset_id: int, prefix: str = "") -> list[dict[str, Any]]:
        dataset_name = self.config.dataset.name
        full_prefix = f"{self.prefix}{dataset_name}/{prefix}"

        paginator = self.s3.get_paginator("list_objects_v2")
        objects = []

        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                objects.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                    "etag": obj["ETag"].strip('"'),
                })

        return objects

    async def delete_object(self, s3_key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=s3_key)

    def get_s3_url(self, s3_key: str) -> str:
        return f"s3://{self.bucket}/{s3_key}"