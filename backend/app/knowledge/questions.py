"""Single-turn question facts, separate from learning attempts and rewards."""
from datetime import timedelta
from copy import deepcopy
import hashlib
import json
from uuid import uuid4
from sqlalchemy import select,func,delete
from ..errors import AppError
from .budgets import JobBudgets
from ..accounts.repository import stamp
from .database import Job,Question,Document,Checkpoint,PublishedResult
from .models import QuestionRequest
from .repository import pagination


class QuestionRepository(JobBudgets):
    def submit_question(self, uid, key, body):
        body = QuestionRequest.model_validate(body)
        if not isinstance(key,str) or not 1 <= len(key) <= 128: raise AppError('INVALID_INPUT','操作标识不正确',422)
        hashed = hashlib.sha256(json.dumps(body.model_dump(mode='json'),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        with self.database.session() as session:
            user = self.accounts._user(session,uid,True)
            old = session.scalar(select(Job).where(Job.user_id == uid,Job.kind == 'question',Job.key == key))
            if old:
                if old.digest != hashed: raise AppError('IDEMPOTENCY_CONFLICT','同一提问标识的内容或范围不同',409)
                return self.job_data(old)
            selected = self._selection(session,uid,body.document_ids,body.all_ready)
            usage = self._usage(session,user.identity)
            if usage.questions >= self.config.question_daily_limit:
                raise AppError('KNOWLEDGE_QUESTION_DAILY_LIMIT','今天的知识库提问次数已用完，请明天再试',429)
            usage.questions += 1
            row = Job(id=str(uuid4()),user_id=uid,kind='question',key=key,digest=hashed,operation_id=str(uuid4()),
                payload={'question':body.question,'documents':selected,'supplement':body.supplement},
                budget={'question_reserved':1},priority=10,deadline_at=self.now()+timedelta(seconds=self.config.question_timeout_seconds),created_at=self.now())
            session.add(row)
            session.flush()
            return self.job_data(row)

    def _question(self, session, uid, qid, *, lock=False,include_deleted=False):
        query = select(Question).where(Question.id == qid,Question.user_id == uid)
        if not include_deleted: query = query.where(Question.deleted_at.is_(None))
        if lock: query = query.with_for_update()
        row = session.scalar(query)
        if row is None: raise AppError('NOT_FOUND','问答记录不存在或已删除',404)
        return row

    def _question_data(self, session, row):
        from .evidence import mark_deleted_sources
        content = deepcopy(row.content)
        mark_deleted_sources(session,row.user_id,content['sources'])
        documents = deepcopy(row.documents)
        for snapshot in documents:
            document = session.get(Document,snapshot['id'])
            removed = document is None or document.user_id != row.user_id or document.deleted_at is not None
            snapshot.update(deleted=removed,version_changed=bool(not removed and document.active_revision_id != snapshot['revision_id']))
        return {**content,'kind':'knowledge_answer','id':row.id,'question':row.question,'documents':documents,
                'supplement':bool(row.supplement),'created_at':stamp(row.created_at)}

    def question(self, uid, qid):
        with self.database.session() as session:
            self.accounts._user(session,uid)
            return self._question_data(session,self._question(session,uid,qid))

    def list_questions(self, uid, page=1,page_size=20):
        pagination(page,page_size)
        with self.database.session() as session:
            self.accounts._user(session,uid)
            filters = [Question.user_id == uid,Question.deleted_at.is_(None)]
            total = session.scalar(select(func.count()).select_from(Question).where(*filters))
            rows = session.scalars(select(Question).where(*filters).order_by(Question.created_at.desc(),Question.id.desc()).offset((page-1)*page_size).limit(page_size))
            items = [{'id':row.id,'question':row.question,'status':row.content['status'],
                'answer_preview':' '.join(p['text'] for p in row.content['paragraphs'])[:160],
                'message':row.content.get('message'),'created_at':stamp(row.created_at)} for row in rows]
            return {'items':items,'total':total,'page':page,'page_size':page_size}

    def delete_question(self, uid, qid):
        with self.database.session() as session:
            self.accounts._user(session,uid,True)
            row = self._question(session,uid,qid,lock=True,include_deleted=True)
            if row.deleted_at: return {'deleted':True}
            row.deleted_at,row.question,row.documents,row.content = self.now(),'',[],{}
            session.execute(delete(Checkpoint).where(Checkpoint.user_id == uid,Checkpoint.operation_id == row.operation_id))
            jobs = session.scalars(select(Job).where(Job.user_id == uid,Job.operation_id == row.operation_id).with_for_update())
            for job in jobs:
                job.payload = {'history_deleted':True}
                job.result = {'question_id':qid,'deleted':True}
            published = session.get(PublishedResult,row.operation_id)
            if published and published.user_id == uid: published.result = {'question_id':qid,'deleted':True}
            return {'deleted':True}

    def quiz_context(self, uid, qid):
        with self.database.session() as session:
            self.accounts._user(session,uid)
            row = self._question(session,uid,qid)
            try: self.validate_documents(uid,row.documents,session=session)
            except AppError:
                raise AppError('KNOWLEDGE_SCOPE_CHANGED','原问题的资料已删除或更新，请重新选择资料并确认范围',409) from None
            return {'goal':row.question,'documents':deepcopy(row.documents),'supplement':bool(row.supplement),'requires_confirmation':True}
