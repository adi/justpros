import hashlib
import os
import secrets

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


IMAGE_EXTENSION_MAP = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

VIDEO_EXTENSION_MAP = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}

# Combined map for post media (images + videos)
POST_MEDIA_EXTENSION_MAP = {**IMAGE_EXTENSION_MAP, **VIDEO_EXTENSION_MAP}


def _hash_user_id(user_id: int) -> str:
    """Create a non-guessable hash from user ID."""
    secret = R2_SECRET_ACCESS_KEY.encode()
    data = str(user_id).encode()
    return hashlib.blake2b(data, key=secret, digest_size=16).hexdigest()


def delete_avatar(avatar_path: str) -> None:
    """Delete avatar from storage."""
    s3.delete_object(Bucket=R2_BUCKET_NAME, Key=avatar_path)


def get_avatar_url(avatar_path: str) -> str:
    """Get full URL for avatar path."""
    return f"{R2_PUBLIC_URL}/{avatar_path}"


def delete_cover(cover_path: str) -> None:
    """Delete cover image from storage."""
    s3.delete_object(Bucket=R2_BUCKET_NAME, Key=cover_path)


def get_cover_url(cover_path: str) -> str:
    """Get full URL for cover path."""
    return f"{R2_PUBLIC_URL}/{cover_path}"


def _hash_post_media(post_id: int, index: int) -> str:
    """Create a non-guessable hash for post media."""
    secret = R2_SECRET_ACCESS_KEY.encode()
    data = f"{post_id}:{index}".encode()
    return hashlib.blake2b(data, key=secret, digest_size=16).hexdigest()


def delete_post_media(media_path: str) -> None:
    """Delete post media from storage."""
    s3.delete_object(Bucket=R2_BUCKET_NAME, Key=media_path)


def get_post_media_url(media_path: str) -> str:
    """Get full URL for post media path."""
    return f"{R2_PUBLIC_URL}/{media_path}"


# --- Presigned URL Generation ---


def _generate_upload_url(path: str, content_type: str, expiration: int = 900) -> str:
    """Generate presigned PUT URL for direct R2 upload."""
    return s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": R2_BUCKET_NAME,
            "Key": path,
            "ContentType": content_type,
        },
        ExpiresIn=expiration,
    )


def generate_avatar_upload_url(user_id: int, content_type: str) -> dict:
    """Generate presigned URL for direct avatar upload."""
    ext = IMAGE_EXTENSION_MAP.get(content_type)
    if ext is None:
        raise ValueError(f"Unsupported content type: {content_type}")
    random_id = secrets.token_hex(16)
    path = f"avatars/{random_id}.{ext}"
    return {"upload_url": _generate_upload_url(path, content_type), "media_path": path}


def generate_cover_upload_url(user_id: int, content_type: str) -> dict:
    """Generate presigned URL for direct cover upload."""
    ext = IMAGE_EXTENSION_MAP.get(content_type)
    if ext is None:
        raise ValueError(f"Unsupported content type: {content_type}")
    random_id = secrets.token_hex(16)
    path = f"covers/{random_id}.{ext}"
    return {"upload_url": _generate_upload_url(path, content_type), "media_path": path}


def generate_post_media_upload_url(post_id: int, index: int, content_type: str) -> dict:
    """Generate presigned URL for direct post media upload."""
    ext = POST_MEDIA_EXTENSION_MAP.get(content_type)
    if ext is None:
        raise ValueError(f"Unsupported content type: {content_type}")
    hashed_id = _hash_post_media(post_id, index)
    path = f"newsfeed/{hashed_id}.{ext}"
    return {"upload_url": _generate_upload_url(path, content_type), "media_path": path}


def get_media_type(content_type: str) -> str:
    """Return 'image' or 'video' based on content type."""
    if content_type in IMAGE_EXTENSION_MAP:
        return "image"
    if content_type in VIDEO_EXTENSION_MAP:
        return "video"
    raise ValueError(f"Unsupported content type: {content_type}")
