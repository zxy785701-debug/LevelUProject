"""Rebuildable vectors. MySQL remains authoritative for text and permissions."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import threading
from sqlalchemy import select
from ..errors import AppError
from .database import Document,Revision,Chunk
from .embeddings import valid_vector
from .jobs import DurableJobs
from .repository import KnowledgeRepository


class VectorIndex(KnowledgeRepository):
    def __init__(self, accounts, config, *, lock, guard):
        super().__init__(accounts,config)
        if (lock.stream is None or lock.root.resolve() != config.storage_root.resolve()
                or guard.config.storage_root.resolve() != config.storage_root.resolve()):
            raise AppError('KNOWLEDGE_WORKER_LOCK_REQUIRED','本地索引只允许独立执行器打开',503)
        guard.heartbeat()
        self.guard, self.directory_lock = guard, lock
        self.mutex, self.jobs = threading.RLock(), DurableJobs(accounts,config)
        import chromadb
        from chromadb.config import Settings
        self.client = chromadb.PersistentClient(path=str(config.storage_root/'chroma'),settings=Settings(anonymized_telemetry=False))

    @staticmethod
    def collection_name(uid,profile):
        return 'kb-'+hashlib.sha256(uid.encode()).hexdigest()[:32]+'-'+profile[:20]

    def _writer(self):
        if self.directory_lock.stream is None:
            raise AppError('KNOWLEDGE_WORKER_LOCK_REQUIRED','执行器目录锁已释放',503)
        self.guard.heartbeat()

    def collection(self, uid, profile=None):
        self._writer()
        profile = profile or self.profile
        metadata = {'owner':hashlib.sha256(uid.encode()).hexdigest(),'profile':profile,'dimension':1024,'metric':'cosine'}
        collection = self.client.get_or_create_collection(name=self.collection_name(uid,profile),embedding_function=None,
            metadata=metadata,configuration={'hnsw':{'space':'cosine'}})
        if collection.metadata != metadata:
            raise AppError('KNOWLEDGE_INDEX_PROFILE_MISMATCH','索引配置不一致，请重建资料索引',503)
        return collection

    def _revision(self, session, claim, rid, *, staging=False):
        row = self.jobs._active(session,claim)
        revision = session.get(Revision,rid)
        if (revision is None or revision.document_id != row.document_id or revision.profile != self.profile
                or staging and revision.status != 'staging'):
            raise AppError('KNOWLEDGE_INDEX_PROFILE_MISMATCH','资料版本或向量配置已变化，请重新处理',409)
        return revision

    def upsert(self, claim, rid, chunks, vectors):
        if (not chunks or len(chunks) != len(vectors) or
                any(not valid_vector(v,self.config.embedding_dimension) for v in vectors)):
            raise AppError('EMBEDDING_INVALID_RESPONSE','向量数量或维度校验失败，未写入索引',502)
        with self.mutex:
            self._writer()
            with self.database.session() as session:
                revision = self._revision(session,claim,rid,staging=True)
                for chunk in chunks:
                    stored = session.get(Chunk,chunk['id'])
                    if stored is None or stored.revision_id != rid or stored.text != chunk['text'] or stored.content_hash != chunk['content_hash']:
                        raise AppError('KNOWLEDGE_CHUNK_MISMATCH','分块清单与持久正文不符',409)
            collection = self.collection(claim.user_id)
            collection.upsert(ids=[c['id'] for c in chunks],embeddings=vectors,
                metadatas=[{'user_id':claim.user_id,'profile':self.profile,'document_id':claim.document_id,
                            'revision_id':rid,'content_hash':c['content_hash']} for c in chunks])
            # A delete can commit while Chroma is writing; never leave that batch alive.
            try:
                with self.database.session() as session: self._revision(session,claim,rid,staging=True)
            except AppError:
                collection.delete(ids=[c['id'] for c in chunks])
                raise

    def verify(self, claim, rid, expected, *, complete=True):
        with self.mutex:
            self._writer()
            with self.database.session() as session: self._revision(session,claim,rid)
            collection = self.collection(claim.user_id)
            where = {'$and':[{'user_id':claim.user_id},{'profile':self.profile},{'revision_id':rid}]}
            values = collection.get(where=where,ids=None if complete else expected,include=['embeddings','metadatas'])
            if set(values['ids']) != set(expected) or len(values['ids']) != len(expected):
                raise AppError('KNOWLEDGE_INDEX_INCOMPLETE','索引尚未完整写入或清单不一致，未发布资料',409)
            embeddings = values['embeddings']
            if embeddings is None or len(embeddings) != len(expected):
                raise AppError('KNOWLEDGE_INDEX_INCOMPLETE','索引向量缺失，未发布资料',409)
            for vector in embeddings:
                if not valid_vector(vector.tolist(),self.config.embedding_dimension):
                    raise AppError('EMBEDDING_INVALID_RESPONSE','索引向量校验不通过，未发布资料',502)
            return len(expected)

    def search(self, claim, selected, vector, *, maximum=12,min_score=.35):
        if not valid_vector(vector,self.config.embedding_dimension) or type(maximum) is not int or not 1 <= maximum <= 12:
            raise AppError('INVALID_INPUT','检索向量或条数不正确',422)
        with self.mutex:
            self._writer()
            with self.database.session() as session:
                self.jobs._active(session,claim)
                self.validate_documents(claim.user_id,selected,session=session)
            collection = self.collection(claim.user_id)
            count = collection.count()
            if not count:
                raise AppError('KNOWLEDGE_INDEX_UNAVAILABLE','资料索引为空，请重建所选资料后重试',503)
            groups = []
            for document in selected:
                where = {'$and':[{'user_id':claim.user_id},{'profile':self.profile},
                        {'document_id':document['id']},{'revision_id':document['revision_id']}]}
                found = collection.query(query_embeddings=[vector],n_results=min(count,maximum*3),where=where,include=['distances'])
                if not found['ids'][0]:
                    # A recently upserted filtered subset can be present in get()
                    # before the ANN query exposes it. Bound an exact fallback for
                    # small subsets rather than falsely declaring them unrelated.
                    stored = collection.get(where=where,limit=257,include=['embeddings'])
                    if len(stored['ids'])>256:
                        raise AppError('KNOWLEDGE_INDEX_UNAVAILABLE','索引暂未可读，请稍后重试或重建资料',503)
                    query_norm = math.sqrt(sum(v*v for v in vector))
                    pairs = []
                    if stored['ids'] and (stored['embeddings'] is None or not query_norm):
                        raise AppError('KNOWLEDGE_INDEX_UNAVAILABLE','索引向量不可读取，请重建资料',503)
                    if stored['embeddings'] is not None and query_norm:
                        for cid,values in zip(stored['ids'],stored['embeddings'],strict=True):
                            values = values.tolist()
                            if not valid_vector(values,self.config.embedding_dimension):
                                raise AppError('KNOWLEDGE_INDEX_UNAVAILABLE','索引向量校验失败，请重建资料',503)
                            norm = math.sqrt(sum(v*v for v in values))
                            if not norm:
                                raise AppError('KNOWLEDGE_INDEX_UNAVAILABLE','索引向量无法用于检索，请重建资料',503)
                            if norm:
                                distance = 1-sum(a*b for a,b in zip(vector,values,strict=True))/(query_norm*norm)
                                pairs.append((cid,distance))
                    pairs.sort(key=lambda pair:pair[1])
                    found = {'ids':[[p[0] for p in pairs[:maximum*3]]],'distances':[[p[1] for p in pairs[:maximum*3]]]}
                candidates = [(cid,distance) for cid,distance in zip(found['ids'][0],found['distances'][0],strict=True)
                              if math.isfinite(distance) and 1-distance >= min_score]
                if candidates: groups.append(candidates)
            groups.sort(key=lambda values:values[0][1])
            ordered = []
            while any(groups) and len(ordered)<maximum*3:
                for group in groups:
                    if group and len(ordered)<maximum*3: ordered.append(group.pop(0))
            result = {'ids':[[v[0] for v in ordered]],'distances':[[v[1] for v in ordered]]}
        available = {d['id']:d['revision_id'] for d in selected}
        output, hashes = [], set()
        with self.database.session() as session:
            self.jobs._active(session,claim)
            self.validate_documents(claim.user_id,selected,session=session)
            for cid,distance in zip(result['ids'][0],result['distances'][0],strict=True):
                if not math.isfinite(distance) or 1-distance < min_score: continue
                chunk = session.get(Chunk,cid)
                revision = session.get(Revision,chunk.revision_id) if chunk else None
                document = session.get(Document,revision.document_id) if revision else None
                if (document is None or document.user_id != claim.user_id or document.deleted_at is not None
                        or available.get(document.id) != revision.id or document.active_revision_id != revision.id
                        or revision.status != 'ready' or revision.profile != self.profile or chunk.content_hash in hashes):
                    continue
                # Adjacent near-identical offsets do not get counted as separate support.
                if any(v['revision_id'] == revision.id and
                       max(0,min(v['location']['end_index'],chunk.location['end_index'])-max(v['location']['start_index'],chunk.location['start_index']))
                       > .8*min(len(v['text']),len(chunk.text)) for v in output): continue
                hashes.add(chunk.content_hash)
                output.append({'chunk_id':chunk.id,'position':chunk.position,'document_id':document.id,'revision_id':revision.id,'version':revision.number,
                    'title':document.title,'source_type':document.source_type,'source':deepcopy(document.source),'text':chunk.text,
                    'location':deepcopy(chunk.location),'score':round(1-distance,6)})
                if len(output) >= maximum: break
        return output

    def close(self):
        with self.mutex: self.client.close()

    def remove(self, uid, payload):
        from chromadb.errors import NotFoundError
        with self.mutex:
            self._writer()
            profiles = set(payload.get('profiles',[]))
            if payload['kind'] == 'account':
                prefix = 'kb-'+hashlib.sha256(uid.encode()).hexdigest()[:32]+'-'
                names, offset = [], 0
                while True:
                    page = self.client.list_collections(limit=100,offset=offset)
                    names.extend(c.name for c in page if c.name.startswith(prefix))
                    if len(page)<100: break
                    offset += 100
            else:
                names = [self.collection_name(uid,p) for p in profiles]
            for name in names:
                try: collection = self.client.get_collection(name,embedding_function=None)
                except NotFoundError: continue
                if (collection.metadata or {}).get('owner') != hashlib.sha256(uid.encode()).hexdigest():
                    raise AppError('KNOWLEDGE_INDEX_PROFILE_MISMATCH','索引账号标记不一致，清理已停止',503)
                if payload['kind'] == 'account': self.client.delete_collection(name)
                elif payload['kind'] == 'revision':
                    collection.delete(where={'$and':[{'document_id':payload['document_id']},{'revision_id':payload['revision_id']}]})
                else: collection.delete(where={'document_id':payload['document_id']})
