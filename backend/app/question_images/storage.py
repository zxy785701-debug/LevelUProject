"""Pinned public downloads and synchronous, bounded COS SDK operations."""
import io
import logging
import re
from urllib.parse import quote
from PIL import Image, UnidentifiedImageError
from ..errors import AppError
from ..materials.sources import public_read
from .provider import result_url


def download_png(url,config,*,reader=public_read):
    result_url(url)
    try:
        final,data,kind=reader(url,config.download_timeout_seconds,config.max_bytes)
        result_url(final)
        if (not data or len(data)>config.max_bytes or kind.split(';')[0].strip().lower()
                not in ('image/png','image/jpeg','image/webp','application/octet-stream')):
            raise ValueError('invalid image content')
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('PNG','JPEG','WEBP') or image.size!=(512,512):
                raise ValueError('invalid image dimensions')
            image.load()
            output=io.BytesIO()
            image.convert('RGB').save(output,'PNG')
            return output.getvalue()
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,AppError):
        raise AppError('IMAGE_DOWNLOAD_FAILED','配图下载或校验失败，本轮仍可文字学习',502) from None


class CosImageStorage:
    def __init__(self,config):self.config=config

    def _client(self,region=None):
        from qcloud_cos import CosConfig,CosS3Client
        # The SDK logs raw provider errors at warning/error levels; our boundary
        # reports only sanitized application error codes.
        logging.getLogger('qcloud_cos').setLevel(logging.CRITICAL)
        c=self.config
        conf=CosConfig(Region=region or c.cos_region,SecretId=c.cos_secret_id.get_secret_value(),
            SecretKey=c.cos_secret_key.get_secret_value(),Scheme='https',Timeout=c.upload_timeout_seconds,
            PoolMaxSize=c.concurrency,AllowRedirects=False)
        return CosS3Client(conf,retry=0)

    @staticmethod
    def _key(key):
        if not re.fullmatch(r'question-images/[a-f0-9]{32}\.png',key):
            raise AppError('COS_INVALID_KEY','配图保存位置不可用',422)

    def upload(self,data,key):
        self._key(key)
        try:
            self._client().put_object(Bucket=self.config.cos_bucket,Key=key,Body=data,
                ContentType='image/png',CacheControl='public, max-age=31536000, immutable',EnableMD5=True)
            return self.config.public_base_url+'/'+quote(key,safe='/')
        except Exception:
            raise AppError('COS_UPLOAD_FAILED','配图暂时无法保存，本轮仍可文字学习',502) from None

    def delete(self,key,*,bucket=None,region=None):
        self._key(key)
        try:
            self._client(region).delete_object(Bucket=bucket or self.config.cos_bucket,Key=key)
        except Exception:
            raise AppError('COS_DELETE_FAILED','配图清理将在稍后重试',502) from None
