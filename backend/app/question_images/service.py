"""Best-effort parallel illustrations for an already reviewed quiz."""
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import logging
import time
from ..errors import AppError
from .config import load_settings
from .provider import QwenImages
from .planning import VisualPlanner, plan_signature, scene_prompt
from .repository import ImageRepository
from .storage import CosImageStorage, download_png

logger=logging.getLogger(__name__)


def outcome(quiz,generated,reason=None):
    quiz['image_generation']={'requested':len(quiz['questions']),'generated':generated,'reason_code':reason}
    return quiz


def stage_budget():
    config,error=load_settings()
    return config.stage_timeout_seconds if config and not error else 90


class QuestionImages:
    def __init__(self,accounts,config,*,repository=None,provider=None,storage=None,download=None,planner=None):
        self.config=config
        self.repository=repository or ImageRepository(accounts,config)
        self.provider=provider or QwenImages(config)
        self.storage=storage or CosImageStorage(config)
        self.download=download or download_png
        self.planner=planner
        self.clock=(lambda:accounts.clock()) if accounts is not None else time.time

    async def attach(self,uid,operation_id,quiz,*,seconds=None,guard=None,gateway=None):
        result=deepcopy(quiz)
        for question in result['questions']:question.pop('image_url',None)
        reason=self.config.unavailable_reason()
        if reason:return outcome(result,0,reason)
        budget=min(self.config.stage_timeout_seconds,seconds if seconds is not None else self.config.stage_timeout_seconds)
        if budget<=0:return outcome(result,0,'IMAGE_TIMEOUT')
        deadline=asyncio.get_running_loop().time()+budget
        errors=[]
        semaphore=asyncio.Semaphore(self.config.concurrency)

        async def check():
            if guard:await guard()

        async def plan():
            await check()
            cached=await asyncio.to_thread(self.repository.begin_plan,uid,operation_id,plan_signature(result))
            if not cached['fresh']:
                if cached['status']=='ready':return cached['scenes']
                code='IMAGE_DAILY_LIMIT' if cached['status']=='quota_exceeded' else 'IMAGE_PROMPT_FAILED'
                raise AppError(code,'本轮部分配图未完成，仍可文字学习',409)
            try:
                await check()
                planner=self.planner or (VisualPlanner(gateway) if gateway is not None else None)
                if planner is None:raise ValueError('Counted visual planner unavailable')
                scenes=await planner.plan(result)
                await check()
                if not await asyncio.to_thread(self.repository.finish_plan,uid,operation_id,scenes):
                    raise ValueError('Plan no longer publishable')
                return scenes
            except Exception:
                await asyncio.to_thread(self.repository.finish_plan,uid,operation_id,None)
                raise

        try:
            scenes=await asyncio.wait_for(plan(),budget)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code='IMAGE_TIMEOUT' if isinstance(error,TimeoutError) else error.code if isinstance(error,AppError) else 'IMAGE_PROMPT_FAILED'
            logger.info('image_plan_failed operation=%s code=%s',operation_id,code)
            return outcome(result,0,code)

        async def one(question):
            started=False
            dispatched=False
            try:
                async with semaphore:
                    await check()
                    prompt=scene_prompt(scenes[question['id']])
                    signature=hashlib.sha256((self.config.model+'\0'+self.config.size+'\0'+prompt).encode()).hexdigest()
                    reservation=asyncio.create_task(asyncio.to_thread(self.repository.start,uid,operation_id,question['id'],signature))
                    try:
                        call=await asyncio.shield(reservation)
                    except asyncio.CancelledError:
                        # Cancelling an await cannot stop its SQL thread. Join that
                        # short transaction and release only definitely-unsent work.
                        try:
                            reserved=await reservation
                            if reserved['fresh']:
                                await asyncio.to_thread(self.repository.abandon,uid,operation_id,question['id'])
                        except Exception:
                            pass
                        raise
                    if not call['fresh']:
                        if call['status']=='succeeded' and call.get('image_url'):
                            question['image_url']=call['image_url']
                        else:
                            errors.append(call.get('error_code') or 'IMAGE_REQUEST_UNCERTAIN')
                        return
                    started=True
                    async def before_dispatch():
                        nonlocal dispatched
                        while True:
                            await check()
                            scheduled=await asyncio.to_thread(self.repository.dispatch_slot)
                            if scheduled is None:break
                            while (delay:=scheduled-self.clock())>0:
                                await asyncio.sleep(delay)
                                await check()
                            # SQL results can wait behind synchronous client setup.
                            # Never bunch those old slots into a new HTTP burst.
                            tolerance=min(.02,self.config.min_request_interval_seconds*.1)
                            if self.clock()-scheduled<=tolerance:break
                        await check()
                        dispatched=True
                    # No automatic paid retry: a lost response still consumes quota.
                    url=await self.provider.generate(prompt,before_dispatch=before_dispatch)
                    await check()
                    data=await asyncio.to_thread(self.download,url,self.config)
                    await check()
                    saved=await asyncio.to_thread(self.storage.upload,data,call['object_key'])
                    accepted=await asyncio.to_thread(self.repository.finish,uid,operation_id,question['id'],image_url=saved)
                    if accepted:question['image_url']=saved
                    else:errors.append('IMAGE_RESULT_DISCARDED')
            except asyncio.CancelledError:
                # A started request remains uncertain rather than being replayed.
                if started and not dispatched:
                    try:await asyncio.to_thread(self.repository.abandon,uid,operation_id,question['id'])
                    except Exception:pass
                raise
            except Exception as error:
                code=error.code if isinstance(error,AppError) else 'IMAGE_FAILED'
                errors.append(code)
                logger.info('image_failed operation=%s question=%s code=%s',operation_id,question['id'],code)
                if started:
                    try:
                        if dispatched:
                            await asyncio.to_thread(self.repository.finish,uid,operation_id,question['id'],error=code)
                        else:
                            await asyncio.to_thread(self.repository.abandon,uid,operation_id,question['id'])
                    except Exception:
                        pass  # The started ledger entry still prevents a second paid call.

        tasks=[asyncio.create_task(one(question)) for question in result['questions']]
        try:
            _,pending=await asyncio.wait(tasks,timeout=max(0,deadline-asyncio.get_running_loop().time()))
            if pending:errors.append('IMAGE_TIMEOUT')
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        generated=sum(bool(q.get('image_url')) for q in result['questions'])
        reason=None
        if generated<len(result['questions']):
            reason=('IMAGE_DAILY_LIMIT' if 'IMAGE_DAILY_LIMIT' in errors else 'IMAGE_TIMEOUT' if 'IMAGE_TIMEOUT' in errors
                    else errors[0] if errors and len(set(errors))==1 and not generated else 'IMAGE_PARTIAL_FAILURE')
        return outcome(result,generated,reason)


async def enrich_quiz(accounts,uid,operation_id,quiz,*,service=None,seconds=None,guard=None,gateway=None):
    try:
        if service is None:
            config,error=load_settings()
            if error:return outcome(deepcopy(quiz),0,error)
            service=QuestionImages(accounts,config)
        return await service.attach(uid,operation_id,quiz,seconds=seconds,guard=guard,gateway=gateway)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Optional initialization/infrastructure errors must not drop a valid quiz.
        return outcome(deepcopy(quiz),0,'IMAGE_UNAVAILABLE')


def cleanup_images(accounts):
    config,error=load_settings()
    if error:return
    # Deletion uses the bucket/region recorded per object. Neither paid-model
    # credentials nor a public distribution domain are needed to remove it.
    if not all((config.cos_secret_id.get_secret_value().strip(),config.cos_secret_key.get_secret_value().strip())):return
    if importlib.util.find_spec('qcloud_cos') is None:return
    ImageRepository(accounts,config).cleanup(CosImageStorage(config))
