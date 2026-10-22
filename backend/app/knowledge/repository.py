"""Account-scoped facts and operation coordination; never opens a vector client."""
from datetime import datetime, timezone, timedelta
from copy import deepcopy
import hashlib
import json
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from ..accounts.database import Material
from ..accounts.repository import stamp, SHANGHAI
from ..errors import AppError
from ..materials.parsers import validate_url
from .database import Document, Revision, Chunk, Job, Usage


def embedding_profile(config):
    data = [config.embedding_model, config.embedding_dimension, config.embedding_distance,
            config.embedding_region, config.embedding_base_url]
    return hashlib.sha256(json.dumps(data, separators=(',', ':')).encode()).hexdigest()


def pagination(page, page_size):
    if type(page) is not int or type(page_size) is not int or not 1 <= page <= 10000 or not 1 <= page_size <= 100:
        raise AppError('INVALID_PAGINATION', '分页范围不正确，每页最多 100 项', 422)


class KnowledgeRepository:
    def __init__(self, accounts, config):
        self.accounts, self.database, self.config = accounts, accounts.database, config
        self.profile = embedding_profile(config)

    def now(self):
        return datetime.fromtimestamp(self.accounts.clock(), timezone.utc).replace(tzinfo=None)

    def material_choices(self, uid, page=1,page_size=20):
        pagination(page,page_size)
        with self.database.session() as session:
            self.accounts._user(session,uid)
            filters = [Material.user_id == uid,Material.content['source_type'].as_string().in_(['pdf','docx','txt','web']),
                       func.json_length(Material.content['segments'])>0]
            total = session.scalar(select(func.count()).select_from(Material).where(*filters))
            rows = session.scalars(select(Material).where(*filters).order_by(Material.created_at.desc(),Material.id.desc())
                                   .offset((page-1)*page_size).limit(page_size))
            return {'items':[{'id':row.id,'title':row.content['title'],'source_type':row.content['source_type'],
                             'created_at':stamp(row.created_at)} for row in rows],'total':total,'page':page,'page_size':page_size}

    def _usage(self, session, identity):
        day = datetime.fromtimestamp(self.accounts.clock(), SHANGHAI).date().isoformat()
        session.execute(insert(Usage).values(identity=identity, day=day).on_duplicate_key_update(identity=identity))
        return session.scalar(select(Usage).where(Usage.identity == identity, Usage.day == day).with_for_update())

    @staticmethod
    def job_data(row):
        return {'kind': 'knowledge_job', 'id': row.id, 'job_id': row.id, 'job_type': row.kind,
                'document_id': row.document_id, 'status': row.status, 'stage': row.stage,
                'progress': row.progress, 'error_code': row.error_code, 'message': row.message,
                'retry_after_seconds': row.retry_after_seconds, 'deadline': stamp(row.deadline_at),
                'created_at': stamp(row.created_at), 'result': row.result}

    def _submit_import(self, uid, key, identity, build):
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise AppError('INVALID_INPUT', '操作标识不正确', 422)
        hashed = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        saved_file, store = None, None
        try:
            with self.database.session() as session:
                user = self.accounts._user(session, uid, True)
                old = session.scalar(select(Job).where(Job.user_id == uid, Job.kind == 'import', Job.key == key))
                if old:
                    if old.digest != hashed:
                        raise AppError('IDEMPOTENCY_CONFLICT', '相同操作标识的资料或参数不同', 409)
                    return self.job_data(old)
                usage = self._usage(session, user.identity)
                if usage.imports >= self.config.import_daily_limit:
                    raise AppError('KNOWLEDGE_IMPORT_DAILY_LIMIT', '今天的知识库导入次数已用完，请明天再试', 429)
                total = session.scalar(select(func.count()).select_from(Document).where(Document.user_id == uid, Document.deleted_at.is_(None)))
                if total >= self.config.max_documents:
                    raise AppError('KNOWLEDGE_DOCUMENT_LIMIT', '知识库资料数量已达上限，请先删除不需要的资料', 429)
                title, source_type, source, payload, data = build(session)
                if data is not None:
                    from .files import FileStore
                    store = FileStore(self.config.storage_root, create=True)
                    saved_file = store.save(uid, data)
                    payload['file_path'] = saved_file
                now = self.now()
                did, jid = str(uuid4()), str(uuid4())
                session.add(Document(id=did, user_id=uid, title=title, source_type=source_type, source=source,
                                     created_at=now, updated_at=now))
                job = Job(id=jid, user_id=uid, kind='import', key=key, digest=hashed, operation_id=str(uuid4()),
                          document_id=did, payload=payload, created_at=now,
                          deadline_at=now+timedelta(seconds=self.config.import_timeout_seconds))
                session.add(job)
                usage.imports += 1
                session.flush()
                result = self.job_data(job)
            return result
        except Exception:
            if saved_file and store:
                store.delete(uid, saved_file)
            raise

    def submit_file(self, uid, key, filename, data):
        from .files import validate_upload
        name, kind = validate_upload(filename, data, self.accounts.settings.material_max_bytes)
        identity = {'source': 'file', 'name': name, 'sha256': hashlib.sha256(data).hexdigest()}
        return self._submit_import(uid, key, identity, lambda session: (
            name, kind, {'filename': name}, {'source': 'file', 'filename': name, 'sha256': identity['sha256']}, data))

    def submit_web(self, uid, key, url):
        canonical = validate_url(url)
        return self._submit_import(uid, key, {'source': 'web', 'url': canonical}, lambda session: (
            canonical[:180], 'web', {'url': canonical}, {'source': 'web', 'url': canonical}, None))

    def submit_material(self, uid, key, material_id):
        def copy_material(session):
            row = session.get(Material, material_id)
            if row is None or row.user_id != uid:
                raise AppError('NOT_FOUND', '原材料不存在或已清理', 404)
            content = deepcopy(row.content)
            if content.get('source_type') not in ('pdf', 'docx', 'txt', 'web') or not content.get('segments'):
                raise AppError('UNSUPPORTED_FORMAT', '这份材料没有可加入知识库的文档或网页正文', 422)
            if not any(s.get('text', '').strip() for s in content['segments']):
                raise AppError('NO_READABLE_CONTENT', '原材料没有可读取正文', 422)
            source = {k: content[k] for k in ('filename', 'url') if content.get(k)}
            return content['title'][:180], content['source_type'], source, {'source': 'material', 'material_content': content}, None
        return self._submit_import(uid, key, {'source': 'material', 'material_id': material_id}, copy_material)

    def _document(self, session, uid, did, *, lock=False):
        query = select(Document).where(Document.id == did, Document.user_id == uid, Document.deleted_at.is_(None))
        if lock: query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise AppError('NOT_FOUND', '知识库资料不存在', 404)
        return row

    def _data(self, session, row):
        revision = session.get(Revision, row.active_revision_id) if row.active_revision_id else None
        job = session.scalar(select(Job).where(Job.user_id == row.user_id, Job.document_id == row.id,
            Job.kind.in_(['import', 'reindex'])).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
        return {
            'id': row.id, 'title': row.title, 'source_type': row.source_type, 'status': row.status,
            'source': {k: v for k, v in row.source.items() if k in ('filename', 'url', 'retrieved_at', 'published_at', 'truncated', 'source_chars')},
            'active_revision_id': row.active_revision_id, 'version': revision.number if revision else None,
            'text_chars': len(revision.text) if revision else 0,
            'chunk_count': session.scalar(select(func.count()).select_from(Chunk).where(Chunk.revision_id == revision.id)) if revision else 0,
            'job_id': job.id if job else None, 'error_code': job.error_code if job else None,
            'message': job.message if job else None, 'created_at': stamp(row.created_at), 'updated_at': stamp(row.updated_at),
        }

    def documents(self, uid, page=1, page_size=20):
        pagination(page, page_size)
        with self.database.session() as session:
            self.accounts._user(session, uid)
            filters = [Document.user_id == uid, Document.deleted_at.is_(None)]
            total = session.scalar(select(func.count()).select_from(Document).where(*filters))
            rows = session.scalars(select(Document).where(*filters).order_by(Document.created_at.desc(), Document.id.desc())
                                   .offset((page-1)*page_size).limit(page_size))
            return {'items': [self._data(session, row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}

    def document(self, uid, did):
        with self.database.session() as session:
            self.accounts._user(session, uid)
            return self._data(session, self._document(session, uid, did))

    def chunks(self, uid, did, page=1, page_size=20):
        pagination(page, page_size)
        with self.database.session() as session:
            self.accounts._user(session, uid)
            row = self._document(session, uid, did)
            if not row.active_revision_id:
                raise AppError('DOCUMENT_NOT_READY', '资料尚未就绪，请查看处理进度', 409)
            revision = session.get(Revision, row.active_revision_id)
            if revision is None or revision.document_id != row.id or revision.status != 'ready':
                raise AppError('DOCUMENT_NOT_READY', '资料版本尚未就绪', 409)
            query = select(Chunk).where(Chunk.revision_id == revision.id)
            total = session.scalar(select(func.count()).select_from(Chunk).where(Chunk.revision_id == revision.id))
            rows = session.scalars(query.order_by(Chunk.position).offset((page-1)*page_size).limit(page_size))
            return {'items': [{'id': c.id, 'revision_id': c.revision_id, 'position': c.position, 'text': c.text,
                               'location': c.location} for c in rows], 'total': total, 'page': page, 'page_size': page_size}

    def _selection(self, session, uid, ids, all_ready=False):
        if all_ready and ids or not all_ready and not ids or len(ids) > self.config.max_documents or len(ids) != len(set(ids)):
            raise AppError('INVALID_KNOWLEDGE_SCOPE', '请选择资料，或明确选择全部就绪资料', 422)
        query = select(Document).where(Document.user_id == uid, Document.deleted_at.is_(None))
        if all_ready:
            query = query.where(Document.status == 'ready', Document.active_revision_id.is_not(None))
        else:
            query = query.where(Document.id.in_(ids))
        rows = list(session.scalars(query.order_by(Document.id)))
        if not all_ready and {r.id for r in rows} != set(ids):
            raise AppError('NOT_FOUND', '知识库资料不存在', 404)
        if not rows:
            raise AppError('EMPTY_KNOWLEDGE_SCOPE', '还没有就绪资料，请先添加并完成入库', 409)
        result = []
        for row in rows:
            revision = session.get(Revision, row.active_revision_id) if row.active_revision_id else None
            if row.status != 'ready' or revision is None or revision.document_id != row.id or revision.status != 'ready':
                raise AppError('DOCUMENT_NOT_READY', '所选资料尚未就绪，请更新选择', 409)
            if revision.profile != self.profile:
                raise AppError('KNOWLEDGE_REINDEX_REQUIRED', '向量配置已变化，请先重建所选资料索引', 409)
            result.append({'id': row.id, 'revision_id': revision.id, 'version': revision.number,
                           'title': row.title, 'source_type': row.source_type,
                           'source': {k: v for k, v in row.source.items() if k in ('filename', 'url', 'retrieved_at', 'truncated')}})
        return result

    def select_documents(self, uid, ids, *, all_ready=False):
        with self.database.session() as session:
            self.accounts._user(session, uid)
            return self._selection(session, uid, ids, all_ready)

    def validate_documents(self, uid, snapshots, *, session=None):
        def check(current_session):
            current = self._selection(current_session, uid, [v['id'] for v in snapshots])
            if {v['id']: v['revision_id'] for v in current} != {v['id']: v['revision_id'] for v in snapshots}:
                raise AppError('KNOWLEDGE_VERSION_CHANGED', '资料版本已变化，请重新准备学习范围', 409)
            return current
        if session is not None:
            return check(session)
        with self.database.session() as current_session:
            self.accounts._user(current_session, uid)
            return check(current_session)
