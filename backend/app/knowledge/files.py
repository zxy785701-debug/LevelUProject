"""Server-generated private paths, with explicit ownership and root markers."""
import hashlib
from pathlib import Path, PurePath
import re
from uuid import uuid4
from ..errors import AppError

MARKER = '.levelup-knowledge-root'
SIGNATURE = 'levelup-knowledge-storage-v1\n'


def validate_upload(name, data, maximum):
    name = PurePath(name.replace('\\', '/')).name
    extension = PurePath(name).suffix.lower().lstrip('.')
    if extension not in ('pdf', 'docx', 'txt', 'md', 'markdown'):
        raise AppError('UNSUPPORTED_FORMAT', '请选择文字 PDF、DOCX、Markdown 或 TXT；不支持旧 DOC 和扫描件', 422)
    if not data or len(data) > maximum:
        raise AppError('KNOWLEDGE_FILE_TOO_LARGE', '文件为空或超过 20 MB 上限', 413)
    if extension == 'pdf' and not data.startswith(b'%PDF-') or extension == 'docx' and not data.startswith(b'PK\x03\x04'):
        raise AppError('KNOWLEDGE_FILE_INVALID', '文件内容与格式不符，请重新导出后上传', 422)
    if extension in ('txt', 'md', 'markdown'):
        text = None
        for encoding in ('utf-8-sig', 'gb18030'):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                pass
        if text is None or not text.strip() or re.search(r'[\x00-\x08\x0b\x0e-\x1f]', text) or data.startswith((b'%PDF-', b'PK\x03\x04')):
            raise AppError('KNOWLEDGE_FILE_INVALID', '文本编码或内容不正确，请使用 UTF-8 或常见中文文本编码', 422)
    return name[:180], extension


class FileStore:
    def __init__(self, root, *, create=False):
        original = Path(root)
        self.root = original.resolve()
        try:
            if not original.is_absolute() or original.is_symlink():
                raise ValueError()
            marker = self.root / MARKER
            if create:
                if self.root.exists() and (not self.root.is_dir() or not marker.exists() and any(self.root.iterdir())):
                    raise ValueError()
                self.root.mkdir(parents=True, exist_ok=True)
                try:
                    with marker.open('x', encoding='utf-8') as stream: stream.write(SIGNATURE)
                except FileExistsError:
                    pass
            if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding='utf-8') != SIGNATURE:
                raise ValueError()
        except (OSError, ValueError):
            raise AppError('KNOWLEDGE_STORAGE_UNAVAILABLE', '知识库私有存储未就绪，请检查专用目录', 503) from None

    @staticmethod
    def bucket(uid): return hashlib.sha256(uid.encode()).hexdigest()

    def _path(self, uid, relative):
        parts = relative.split('/')
        if (len(parts) != 3 or parts[0] != 'files' or parts[1] != self.bucket(uid)
                or not re.fullmatch(r'[0-9a-f]{32}\.bin', parts[2])):
            raise AppError('KNOWLEDGE_FILE_PATH_INVALID', '资料文件位置不可用', 409)
        target = self.root.joinpath(*parts)
        if any(path.is_symlink() for path in [target, *target.parents] if path != self.root.parent):
            raise AppError('KNOWLEDGE_FILE_PATH_INVALID', '资料文件位置不可用', 409)
        if not target.resolve().is_relative_to(self.root):
            raise AppError('KNOWLEDGE_FILE_PATH_INVALID', '资料文件位置不可用', 409)
        return target

    def save(self, uid, data):
        relative = f'files/{self.bucket(uid)}/{uuid4().hex}.bin'
        path = self._path(uid, relative)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            return relative
        except OSError:
            path.unlink(missing_ok=True)
            raise AppError('KNOWLEDGE_STORAGE_UNAVAILABLE', '文件保存失败，请检查存储空间后重试', 503) from None

    def read(self, uid, relative):
        try:
            return self._path(uid, relative).read_bytes()
        except OSError:
            raise AppError('KNOWLEDGE_FILE_MISSING', '原文件无法读取，请重新添加资料', 409) from None

    def delete(self, uid, relative):
        self._path(uid, relative).unlink(missing_ok=True)

    def delete_user(self, uid):
        bucket = self.root/'files'/self.bucket(uid)
        if not bucket.exists(): return
        if bucket.is_symlink() or not bucket.resolve().is_relative_to(self.root):
            raise AppError('KNOWLEDGE_FILE_PATH_INVALID','账号文件目录不可用',409)
        for path in bucket.iterdir():
            self.delete(uid,f'files/{self.bucket(uid)}/{path.name}')
        bucket.rmdir()
