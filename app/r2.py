import boto3
import os
import uuid
from botocore.config import Config

_R2_ACCOUNT_ID  = os.environ.get('R2_ACCOUNT_ID', '18c5dd7f737e1362673ef529116837aa')
_R2_ACCESS_KEY  = os.environ.get('R2_ACCESS_KEY_ID', '')
_R2_SECRET_KEY  = os.environ.get('R2_SECRET_ACCESS_KEY', '')
_R2_BUCKET      = os.environ.get('R2_BUCKET', 'vendix-storage')
_R2_PUBLIC_URL  = os.environ.get('R2_PUBLIC_URL', 'https://pub-2601de4c6cf446ad88ad9848937c5857.r2.dev')
_R2_ENDPOINT    = f'https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com'

def _client():
    return boto3.client(
        's3',
        endpoint_url=_R2_ENDPOINT,
        aws_access_key_id=_R2_ACCESS_KEY,
        aws_secret_access_key=_R2_SECRET_KEY,
        config=Config(signature_version='s3v4'),
        region_name='auto',
    )

def upload(data: bytes, key: str, content_type: str = 'application/octet-stream') -> str:
    """Upload bytes to R2, return public URL."""
    _client().put_object(
        Bucket=_R2_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return f'{_R2_PUBLIC_URL}/{key}'

def delete(key: str):
    """Delete an object from R2."""
    try:
        _client().delete_object(Bucket=_R2_BUCKET, Key=key)
    except Exception:
        pass

def unique_key(prefix: str, ext: str) -> str:
    return f'{prefix}/{uuid.uuid4().hex}{ext}'
