"""Short identity-locked transactions; no network requests inside a transaction."""
from datetime import datetime, timedelta, timezone
import re
from uuid import uuid4
from sqlalchemy import delete, inspect, select, update
from sqlalchemy.dialects.mysql import insert
from ..accounts.database import User
from ..accounts.repository import SHANGHAI
from ..errors import AppError
from .contracts import permanent_https
from .database import ImageUsage, ImageCall, ImageAsset, ImagePlan, ImageDispatch


def record_account_cleanup(session, uid, now):
    if inspect(session.connection()).has_table('question_image_assets'):
        # Drain the maximum bounded provider/download/upload work before deletion.
        # Keys are registered before upload, so even a late worker cannot orphan it.
        session.execute(update(ImageAsset).where(ImageAsset.user_id == uid, ImageAsset.delete_after.is_(None))
                        .values(delete_after=now + timedelta(minutes=10)))


class ImageRepository:
    def __init__(self, accounts, config):
        self.accounts, self.config, self.database = accounts, config, accounts.database

    def now(self):
        return datetime.fromtimestamp(self.accounts.clock(), timezone.utc).replace(tzinfo=None)

    def day(self):
        return datetime.fromtimestamp(self.accounts.clock(), SHANGHAI).date().isoformat()

    def _usage(self, session, identity):
        day = self.day()
        session.execute(insert(ImageUsage).values(identity=identity, day=day, requests=0)
                        .on_duplicate_key_update(identity=identity))
        return session.scalar(select(ImageUsage).where(ImageUsage.identity == identity, ImageUsage.day == day).with_for_update())

    def quota(self, uid):
        with self.database.session() as session:
            user = self.accounts._user(session, uid, True)
            usage = self._usage(session, user.identity)
            return {'remaining':max(0,self.config.daily_limit-usage.requests), 'daily_limit':self.config.daily_limit}

    def begin_plan(self, uid, operation_id, source_hash):
        if (not isinstance(operation_id,str) or not 1 <= len(operation_id) <= 64
                or not isinstance(source_hash,str) or not re.fullmatch(r'[a-f0-9]{64}',source_hash)):
            raise ValueError('Invalid image plan identity')
        with self.database.session() as session:
            user = self.accounts._user(session,uid,True)
            old = session.get(ImagePlan,(uid,operation_id))
            if old:
                if old.source_hash != source_hash:
                    raise AppError('IMAGE_REQUEST_CONFLICT','配图内容已变化，本轮保留文字题目',409)
                return {'fresh':False,'status':old.status,'scenes':old.scenes}
            if self._usage(session,user.identity).requests >= self.config.daily_limit:
                return {'fresh':False,'status':'quota_exceeded','scenes':None}
            session.add(ImagePlan(user_id=uid,operation_id=operation_id,source_hash=source_hash,created_at=self.now()))
            return {'fresh':True,'status':'started','scenes':None}

    def finish_plan(self, uid, operation_id, scenes):
        with self.database.session() as session:
            if not session.get(User,uid):return False
            self.accounts._user(session,uid,True)
            row = session.get(ImagePlan,(uid,operation_id))
            if row is None or row.status != 'started':return False
            row.status,row.scenes = ('ready',scenes) if scenes is not None else ('failed',None)
            return True

    def dispatch_slot(self):
        """Book a future send time, shared by every API/Worker process."""
        interval = self.config.min_request_interval_seconds
        if interval <= 0:return None
        with self.database.session() as session:
            session.execute(insert(ImageDispatch).values(model=self.config.model,next_allowed_at=0)
                            .on_duplicate_key_update(model=self.config.model))
            row = session.get(ImageDispatch,self.config.model,with_for_update=True)
            now = self.accounts.clock()
            scheduled = max(now+interval,row.next_allowed_at)
            row.next_allowed_at=scheduled+interval
            return scheduled

    def start(self, uid, operation_id, question_id, prompt_hash):
        if (not isinstance(operation_id,str) or not 1 <= len(operation_id) <= 64 or
                not isinstance(question_id,str) or not 1 <= len(question_id) <= 64 or
                not isinstance(prompt_hash,str) or not re.fullmatch(r'[a-f0-9]{64}',prompt_hash)):
            raise ValueError('Invalid image request identity')
        with self.database.session() as session:
            user = self.accounts._user(session, uid, True)
            old = session.scalar(select(ImageCall).where(ImageCall.user_id == uid,
                ImageCall.operation_id == operation_id, ImageCall.question_id == question_id))
            if old:
                if old.prompt_hash != prompt_hash:
                    raise AppError('IMAGE_REQUEST_CONFLICT','配图恢复参数已变化，请重新发起关卡',409)
                return {'fresh':False,'status':old.status,'object_key':old.object_key,'image_url':old.image_url,
                        'error_code':old.error_code}
            usage = self._usage(session,user.identity)
            if usage.requests >= self.config.daily_limit:
                return {'fresh':False,'status':'quota_exceeded','image_url':None,'error_code':'IMAGE_DAILY_LIMIT'}
            key = 'question-images/' + uuid4().hex + '.png'
            usage.requests += 1
            session.add(ImageCall(id=str(uuid4()),user_id=uid,operation_id=operation_id,question_id=question_id,
                prompt_hash=prompt_hash,day=usage.day,object_key=key,created_at=self.now()))
            session.add(ImageAsset(object_key=key,user_id=uid,bucket=self.config.cos_bucket,region=self.config.cos_region))
            return {'fresh':True,'status':'started','object_key':key,'image_url':None,'error_code':None}

    def finish(self, uid, operation_id, question_id, *, image_url=None, error=None):
        if image_url: permanent_https(image_url)
        with self.database.session() as session:
            if not session.get(User,uid): return False
            self.accounts._user(session,uid,True)
            row = session.scalar(select(ImageCall).where(ImageCall.user_id == uid,
                ImageCall.operation_id == operation_id,ImageCall.question_id == question_id))
            if row is None or row.status != 'started': return False
            row.status = 'succeeded' if image_url else 'failed'
            row.image_url, row.error_code = image_url, None if image_url else (error or 'IMAGE_FAILED')[:80]
            return True

    def abandon(self,uid,operation_id,question_id):
        """Undo only a reservation the caller knows never reached HTTP dispatch."""
        with self.database.session() as session:
            if not session.get(User,uid):return False
            user=self.accounts._user(session,uid,True)
            row=session.scalar(select(ImageCall).where(ImageCall.user_id==uid,
                ImageCall.operation_id==operation_id,ImageCall.question_id==question_id))
            if row is None or row.status!='started':return False
            usage=session.scalar(select(ImageUsage).where(ImageUsage.identity==user.identity,ImageUsage.day==row.day).with_for_update())
            if usage:usage.requests=max(0,usage.requests-1)
            row.status,row.error_code='failed','IMAGE_NOT_STARTED'
            asset=session.get(ImageAsset,row.object_key)
            if asset:session.delete(asset)
            return True

    def cleanup(self, storage):
        with self.database.session() as session:
            keys = list(session.scalars(select(ImageAsset.object_key).where(ImageAsset.delete_after <= self.now()).limit(20)))
            session.execute(delete(ImageUsage).where(ImageUsage.day < self.day()))
        removed = 0
        for key in keys:
            with self.database.session() as session:
                asset = session.get(ImageAsset,key)
                if not asset or asset.delete_after is None or asset.delete_after > self.now(): continue
                bucket,region = asset.bucket,asset.region
            try:
                storage.delete(key,bucket=bucket,region=region)
            except Exception:
                with self.database.session() as session:
                    asset = session.get(ImageAsset,key)
                    if asset:
                        asset.attempts += 1
                        asset.delete_after = self.now()+timedelta(seconds=min(900,2**min(asset.attempts,9)))
            else:
                with self.database.session() as session:
                    asset = session.get(ImageAsset,key)
                    if asset: session.delete(asset)
                removed += 1
        return removed
