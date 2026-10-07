"""MinIO/S3 ストレージ操作サービス"""

import logging
from uuid import UUID

import boto3
from botocore.exceptions import ClientError

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.MINIO_SECURE else 'http'}://{settings.MINIO_ENDPOINT}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        use_ssl=settings.MINIO_SECURE,
    )


def sanitize_file_name(file_name: str) -> str:
    """オブジェクトキーへ埋め込むファイル名を無害化する。

    パス区切りや親ディレクトリ参照（`..`）を残すと、キー経由で
    意図しないパスへ到達しうる（path traversal）。
    """
    name = (file_name or "").replace("\\", "/").split("/")[-1]
    name = name.replace("..", "_").strip()
    return name or "unnamed"


def generate_storage_key(
    org_id: UUID, doc_id: UUID, version: int, file_name: str
) -> str:
    return f"{org_id}/{doc_id}/v{version}/{sanitize_file_name(file_name)}"


def initialize_bucket() -> bool:
    try:
        s3 = _get_s3_client()
        s3.head_bucket(Bucket=settings.MINIO_BUCKET)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            try:
                s3.create_bucket(Bucket=settings.MINIO_BUCKET)
                logger.info("Created bucket: %s", settings.MINIO_BUCKET)
                return True
            except ClientError:
                logger.exception("Failed to create bucket")
                return False
        logger.exception("Failed to check bucket")
        return False


def upload_file(file_content: bytes, storage_key: str, content_type: str) -> bool:
    try:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=settings.MINIO_BUCKET,
            Key=storage_key,
            Body=file_content,
            ContentType=content_type,
        )
        logger.info("Uploaded file: %s (size=%d)", storage_key, len(file_content))
        return True
    except ClientError:
        logger.exception("Failed to upload file: %s", storage_key)
        return False


def get_file(storage_key: str) -> bytes | None:
    try:
        s3 = _get_s3_client()
        response = s3.get_object(Bucket=settings.MINIO_BUCKET, Key=storage_key)
        return response["Body"].read()
    except ClientError:
        logger.exception("Failed to get file: %s", storage_key)
        return None


def get_file_stream(storage_key: str):
    try:
        s3 = _get_s3_client()
        response = s3.get_object(Bucket=settings.MINIO_BUCKET, Key=storage_key)
        return response["Body"]
    except ClientError:
        logger.exception("Failed to get file stream: %s", storage_key)
        return None


def delete_file(storage_key: str) -> bool:
    try:
        s3 = _get_s3_client()
        s3.delete_object(Bucket=settings.MINIO_BUCKET, Key=storage_key)
        logger.info("Deleted file: %s", storage_key)
        return True
    except ClientError:
        logger.exception("Failed to delete file: %s", storage_key)
        return False
