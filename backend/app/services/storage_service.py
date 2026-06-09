from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from app.core.config import settings


class StorageServiceError(RuntimeError):
    """Base exception for storage errors."""


class StorageObjectNotFoundError(FileNotFoundError):
    """Raised when an encrypted object does not exist in storage."""


class StorageBackendUnavailableError(StorageServiceError):
    """Raised when MinIO/S3 or local storage is unavailable."""


SUPPORTED_STORAGE_BACKENDS = {"local", "minio"}


# -------------------------
# Common helpers
# -------------------------


def _sanitize_filename(original_filename: str) -> str:
    filename = original_filename or "artifact"
    return filename.replace("/", "_").replace("\\", "_").strip() or "artifact"


def _validate_encrypted_data(encrypted_data: bytes) -> None:
    if not isinstance(encrypted_data, bytes):
        raise TypeError("encrypted_data must be bytes")


# -------------------------
# Local storage
# -------------------------


def ensure_storage_dir() -> Path:
    path = Path(settings.LOCAL_STORAGE_PATH)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_local(encrypted_data: bytes, original_filename: str) -> str:
    _validate_encrypted_data(encrypted_data)

    storage_dir = ensure_storage_dir()
    safe_name = _sanitize_filename(original_filename)
    object_key = f"{uuid4()}_{safe_name}.enc"

    try:
        file_path = storage_dir / object_key
        file_path.write_bytes(encrypted_data)
    except OSError as exc:
        raise StorageBackendUnavailableError("Failed to write encrypted object to local storage") from exc

    return object_key


def _read_local(object_key: str) -> bytes:
    storage_dir = ensure_storage_dir()
    file_path = storage_dir / object_key

    if not file_path.exists():
        raise StorageObjectNotFoundError(f"Encrypted object not found: {object_key}")

    try:
        return file_path.read_bytes()
    except OSError as exc:
        raise StorageBackendUnavailableError("Failed to read encrypted object from local storage") from exc


# -------------------------
# MinIO / S3 storage
# -------------------------


@lru_cache(maxsize=1)
def _get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _is_not_found_error(exc: ClientError) -> bool:
    code = exc.response.get("Error", {}).get("Code", "")
    return code in {"404", "NoSuchBucket", "NoSuchKey", "NotFound"}


def _ensure_bucket_exists() -> None:
    client = _get_s3_client()
    bucket = settings.MINIO_BUCKET

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if not _is_not_found_error(exc):
            raise StorageBackendUnavailableError(f"Failed to access MinIO bucket: {bucket}") from exc

        try:
            client.create_bucket(Bucket=bucket)
        except ClientError as create_exc:
            raise StorageBackendUnavailableError(f"Failed to create MinIO bucket: {bucket}") from create_exc
    except (EndpointConnectionError, NoCredentialsError) as exc:
        raise StorageBackendUnavailableError("MinIO/S3 backend is unavailable") from exc


def _save_minio(encrypted_data: bytes, original_filename: str) -> str:
    _validate_encrypted_data(encrypted_data)
    _ensure_bucket_exists()

    safe_name = _sanitize_filename(original_filename)
    object_key = f"artifacts/{uuid4()}_{safe_name}.enc"

    client = _get_s3_client()

    try:
        client.put_object(
            Bucket=settings.MINIO_BUCKET,
            Key=object_key,
            Body=encrypted_data,
            ContentType="application/octet-stream",
            Metadata={
                "encrypted": "true",
                "storage-format": "swf-aes-gcm-envelope",
            },
        )
    except (ClientError, EndpointConnectionError, NoCredentialsError) as exc:
        raise StorageBackendUnavailableError("Failed to write encrypted object to MinIO") from exc

    return object_key


def _read_minio(object_key: str) -> bytes:
    client = _get_s3_client()

    try:
        response = client.get_object(
            Bucket=settings.MINIO_BUCKET,
            Key=object_key,
        )
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()
    except ClientError as exc:
        if _is_not_found_error(exc):
            raise StorageObjectNotFoundError(f"Encrypted object not found in MinIO: {object_key}") from exc

        raise StorageBackendUnavailableError("Failed to read encrypted object from MinIO") from exc
    except (EndpointConnectionError, NoCredentialsError) as exc:
        raise StorageBackendUnavailableError("MinIO/S3 backend is unavailable") from exc


# -------------------------
# Public storage API
# -------------------------


def _get_storage_backend() -> str:
    backend = settings.STORAGE_BACKEND.lower().strip()
    if backend not in SUPPORTED_STORAGE_BACKENDS:
        raise StorageServiceError(f"Unsupported storage backend: {settings.STORAGE_BACKEND}")

    return backend


def save_encrypted_file(encrypted_data: bytes, original_filename: str) -> str:
    backend = _get_storage_backend()

    if backend == "minio":
        return _save_minio(encrypted_data, original_filename)

    return _save_local(encrypted_data, original_filename)


def read_encrypted_file(object_key: str) -> bytes:
    if not object_key:
        raise StorageObjectNotFoundError("Encrypted object key is empty")

    backend = _get_storage_backend()

    if backend == "minio":
        return _read_minio(object_key)

    return _read_local(object_key)