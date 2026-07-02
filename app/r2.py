import boto3
import os
import uuid
from botocore.config import Config

_R2_ACCOUNT_ID  = os.environ.get('R2_ACCOUNT_ID', '')
_R2_ACCESS_KEY  = os.environ.get('R2_ACCESS_KEY_ID', '')
_R2_SECRET_KEY  = os.environ.get('R2_SECRET_ACCESS_KEY', '')
_R2_BUCKET      = os.environ.get('R2_BUCKET', '')
_R2_PUBLIC_URL  = os.environ.get('R2_PUBLIC_URL', '').rstrip('/')

def _r2_configurado():
    return all([_R2_ACCOUNT_ID, _R2_ACCESS_KEY, _R2_SECRET_KEY, _R2_BUCKET, _R2_PUBLIC_URL])

def _client():
    if not _r2_configurado():
        raise RuntimeError('R2 não configurado: defina R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET e R2_PUBLIC_URL no ambiente.')
    endpoint = f'https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=_R2_ACCESS_KEY,
        aws_secret_access_key=_R2_SECRET_KEY,
        config=Config(signature_version='s3v4'),
        region_name='auto',
    )

# Cache longo para conteudo imutavel (chaves uuid nunca sao reutilizadas).
# NAO usar em releases (download.py), cuja chave pode ser reaproveitada.
_IMG_CACHE = 'public, max-age=31536000, immutable'  # 1 ano

def upload(data: bytes, key: str, content_type: str = 'application/octet-stream',
           long_cache: bool = False) -> str:
    """Upload bytes to R2, return public URL. long_cache=True aplica cache de 1 ano."""
    extra = {'CacheControl': _IMG_CACHE} if long_cache else {}
    _client().put_object(
        Bucket=_R2_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
        **extra,
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
