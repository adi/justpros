import hashlib
import os

import boto3
from botocore.config import Config

R2_ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_ENDPOINT = os.environ["R2_ENDPOINT"]
R2_BUCKET_NAME = os.environ["R2_BUCKET_NAME"]
R2_PUBLIC_URL = os.environ["R2_PUBLIC_URL"]

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
)


EXTENSION_MAP = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def _hash_user_id(user_id: int) -> str:
    """Create a non-guessable hash from user ID."""
    secret = R2_SECRET_ACCESS_KEY.encode()
    data = str(user_id).encode()
    return hashlib.blake2b(data, key=secret, digest_size=16).hexdigest()


def upload_avatar(user_id: int, file_data: bytes, content_type: str) -> str:
    """Upload avatar and return path."""
    ext = EXTENSION_MAP.get(content_type)
    if ext is None:
        raise ValueError(f"Unsupported content type: {content_type}")
    hashed_id = _hash_user_id(user_id)
    path = f"avatars/{hashed_id}.{ext}"
    s3.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=path,
        Body=file_data,
        ContentType=content_type,
    )
    return path


def delete_avatar(avatar_path: str) -> None:
    """Delete avatar from storage."""
    s3.delete_object(Bucket=R2_BUCKET_NAME, Key=avatar_path)


def get_avatar_url(avatar_path: str) -> str:
    """Get full URL for avatar path."""
    return f"{R2_PUBLIC_URL}/{avatar_path}"


def upload_cover(user_id: int, file_data: bytes, content_type: str) -> str:
    """Upload cover image and return path."""
    ext = EXTENSION_MAP.get(content_type)
    if ext is None:
        raise ValueError(f"Unsupported content type: {content_type}")
    hashed_id = _hash_user_id(user_id)
    path = f"covers/{hashed_id}.{ext}"
    s3.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=path,
        Body=file_data,
        ContentType=content_type,
    )
    return path


def delete_cover(cover_path: str) -> None:
    """Delete cover image from storage."""
    s3.delete_object(Bucket=R2_BUCKET_NAME, Key=cover_path)


def get_cover_url(cover_path: str) -> str:
    """Get full URL for cover path."""
    return f"{R2_PUBLIC_URL}/{cover_path}"
