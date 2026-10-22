"""Account-local LangChain embeddings over Bailian's native HTTP API."""
import asyncio
import hashlib
import json
import math
import threading
import time
from uuid import uuid4
import httpx
from langchain_core.embeddings import Embeddings
from ..errors import AppError
from .budgets import JobBudgets
from .database import EmbeddingCache

MAX_INPUT_BYTES = 8192
_limiters, _limiter_lock = {}, threading.Lock()


def safe_text_parts(text, maximum=MAX_INPUT_BYTES):
    """Conservative UTF-8 byte bound; these are not reported as measured Tokens."""
    result, start, used = [], 0, 0
    for index,char in enumerate(text):
        size = len(char.encode())
        if used+size > maximum:
            result.append(text[start:index])
            start, used = index, 0
        used += size
    if start < len(text): result.append(text[start:])
    return result


def valid_vector(vector, dimension):
    return (isinstance(vector,list) and len(vector) == dimension
            and all(type(v) in (int,float) and math.isfinite(v) for v in vector))


class BailianEmbeddings(Embeddings):
    def __init__(self, accounts, config, claim, *, client=None, sleep=time.sleep):
        self.accounts, self.config, self.claim = accounts, config, claim
        self.ledger, self.client, self.sleep = JobBudgets(accounts,config), client, sleep
        self.profile = self.ledger.profile
        with _limiter_lock:
            self.limiter = _limiters.setdefault((self.profile,config.embedding_concurrency),threading.BoundedSemaphore(config.embedding_concurrency))

    def _remaining(self):
        return max(0,(self.claim.deadline_at-self.ledger.now()).total_seconds())

    def _cache(self, texts, text_type):
        result = {}
        with self.ledger.database.session() as session:
            self.ledger._active(session,self.claim)
            for text in dict.fromkeys(texts):
                key = hashlib.sha256(text.encode()).hexdigest()
                row = session.get(EmbeddingCache,(self.claim.user_id,self.profile,key,text_type))
                if row:
                    if not valid_vector(row.vector,self.config.embedding_dimension):
                        raise AppError('EMBEDDING_CACHE_INVALID','向量缓存校验失败，请重建索引',503)
                    result[text] = row.vector
        return result

    def _save(self, texts, vectors, text_type):
        with self.ledger.database.session() as session:
            self.ledger._active(session,self.claim)
            for text,vector in zip(texts,vectors,strict=True):
                key = hashlib.sha256(text.encode()).hexdigest()
                if session.get(EmbeddingCache,(self.claim.user_id,self.profile,key,text_type)) is None:
                    session.add(EmbeddingCache(user_id=self.claim.user_id,profile=self.profile,content_hash=key,text_type=text_type,vector=vector))

    def _validate(self, body, count):
        try:
            rows = body['output']['embeddings']
            if not isinstance(rows,list) or len(rows) != count: raise ValueError()
            result, seen = [None]*count, set()
            for row in rows:
                index,vector = row['text_index'],row['embedding']
                if type(index) is not int or not 0 <= index < count or index in seen or not valid_vector(vector,self.config.embedding_dimension):
                    raise ValueError()
                seen.add(index)
                result[index] = [float(v) for v in vector]
            return result
        except (KeyError,TypeError,ValueError,OverflowError):
            raise AppError('EMBEDDING_INVALID_RESPONSE','向量服务返回数量、位置或维度不正确，未发布索引',502) from None

    def _request(self, texts, text_type):
        if not self.config.embedding_api_key.get_secret_value().strip() or not self.config.embedding_base_url:
            raise AppError('EMBEDDING_NOT_CONFIGURED','请在服务端配置北京百炼向量服务',503)
        url = self.config.embedding_base_url+'/services/embeddings/text-embedding/text-embedding'
        payload = {'model':self.config.embedding_model,'input':{'texts':texts},
                   'parameters':{'dimension':self.config.embedding_dimension,'text_type':text_type}}
        reserved = sum(len(t.encode()) for t in texts)
        for attempt in range(self.config.embedding_max_attempts):
            if self._remaining() <= 0:
                raise AppError('KNOWLEDGE_JOB_EXPIRED','向量化已超过原任务期限',409)
            if not self.limiter.acquire(timeout=self._remaining()):
                raise AppError('EMBEDDING_BUSY','向量服务等待已超时，请稍后重试',503)
            request_id, transient, delay = str(uuid4()), False, min(.5*2**attempt,2)
            try:
                self.ledger.reserve_embedding(self.claim,request_id,reserved)
                timeout = min(self.config.embedding_timeout_seconds,self._remaining())
                headers = {'Authorization':'Bearer '+self.config.embedding_api_key.get_secret_value(),'Accept':'application/json'}
                client = self.client or httpx.Client(follow_redirects=False,trust_env=False)
                try:
                    with client.stream('POST',url,json=payload,headers=headers,timeout=max(.001,timeout)) as response:
                        status = response.status_code
                        if status != 200:
                            transient = status in (408,429) or status >= 500
                            code = 'EMBEDDING_AUTH_ERROR' if status in (401,403) else 'EMBEDDING_SERVICE_REJECTED' if status in (400,402) else 'EMBEDDING_UNAVAILABLE'
                            message = '向量服务凭据、余额或输入不可用，请检查服务端配置' if not transient else '向量服务暂时繁忙，请稍后重试'
                            error = AppError(code,message,503)
                            try:
                                retry_after = float(response.headers.get('Retry-After','0'))
                                if math.isfinite(retry_after) and retry_after >= 0: delay = max(delay,retry_after)
                            except ValueError: pass
                        else:
                            chunks, size = [], 0
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > 2*1024*1024:
                                    raise AppError('EMBEDDING_INVALID_RESPONSE','向量服务响应超过安全上限',502)
                                chunks.append(chunk)
                            try: body = json.loads(b''.join(chunks))
                            except (ValueError,UnicodeError):
                                raise AppError('EMBEDDING_INVALID_RESPONSE','向量服务返回格式不正确',502) from None
                            usage = body.get('usage',{}).get('total_tokens') if isinstance(body,dict) and isinstance(body.get('usage',{}),dict) else None
                            if type(usage) is int and usage >= 0:
                                self.ledger.settle_embedding(self.claim,request_id,usage)
                            return self._validate(body,len(texts))
                finally:
                    if self.client is None: client.close()
            except (httpx.TimeoutException,httpx.NetworkError):
                transient = True
                error = AppError('EMBEDDING_UNAVAILABLE','向量服务连接超时或暂时不可用，请稍后重试',503)
            finally:
                self.limiter.release()
            if not transient or attempt+1 >= self.config.embedding_max_attempts or delay >= self._remaining():
                raise error from None
            self.sleep(delay)

    def _embed(self, texts, text_type):
        if (not isinstance(texts,list) or len(texts)>1000 or
                any(not isinstance(t,str) or not t.strip() or len(t.encode())>MAX_INPUT_BYTES for t in texts)):
            raise AppError('EMBEDDING_INPUT_TOO_LONG','向量输入为空或超过保守上界，请先拆分正文或缩短查询',422)
        if not texts: return []
        vectors = self._cache(texts,text_type)
        missing = [text for text in dict.fromkeys(texts) if text not in vectors]
        for start in range(0,len(missing),self.config.embedding_batch_size):
            batch = missing[start:start+self.config.embedding_batch_size]
            values = self._request(batch,text_type)
            self._save(batch,values,text_type)
            vectors.update(zip(batch,values,strict=True))
        return [vectors[text] for text in texts]

    def embed_documents(self, texts): return self._embed(texts,'document')
    def embed_query(self, text): return self._embed([text],'query')[0]
    async def aembed_documents(self, texts): return await asyncio.to_thread(self.embed_documents,texts)
    async def aembed_query(self, text): return await asyncio.to_thread(self.embed_query,text)
