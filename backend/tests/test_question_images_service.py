import asyncio
from copy import deepcopy
import threading
import pytest
from app.errors import AppError
from tests.helpers import quiz_payload
from tests.test_question_images_transport import config, URL, png


class Ledger:
    def __init__(self,remaining=20):self.remaining=remaining;self.calls={};self.plans={};self.lock=threading.Lock()
    def begin_plan(self,uid,op,h):
        with self.lock:
            if op in self.plans:return {**deepcopy(self.plans[op]),'fresh':False}
            if not self.remaining:return {'fresh':False,'status':'quota_exceeded','scenes':None}
            self.plans[op]={'fresh':True,'status':'started','scenes':None}
            return deepcopy(self.plans[op])
    def finish_plan(self,uid,op,scenes):
        with self.lock:
            if self.plans[op]['status']!='started':return False
            self.plans[op].update(status='ready' if scenes is not None else 'failed',scenes=deepcopy(scenes))
            return True
    def start(self,uid,op,q,h):
        with self.lock:
            if q in self.calls:return {**self.calls[q],'fresh':False}
            if not self.remaining:return {'fresh':False,'status':'quota_exceeded','error_code':'IMAGE_DAILY_LIMIT'}
            self.remaining-=1
            self.calls[q]={'fresh':True,'status':'started','object_key':'question-images/'+str(len(self.calls)).zfill(32)+'.png','image_url':None}
            return deepcopy(self.calls[q])
    def finish(self,uid,op,q,*,image_url=None,error=None):
        with self.lock:self.calls[q].update(status='succeeded' if image_url else 'failed',image_url=image_url,error_code=error)
        return True
    def abandon(self,uid,op,q):
        with self.lock:
            self.remaining+=1
            self.calls[q].update(status='failed',error_code='IMAGE_NOT_STARTED')
    def dispatch_slot(self):return None


class Provider:
    def __init__(self,fail=(),delay=.01):self.prompts=[];self.active=0;self.maximum=0;self.fail=fail;self.delay=delay
    async def generate(self,prompt,*,before_dispatch=None):
        if before_dispatch:await before_dispatch()
        self.prompts.append(prompt);self.active+=1;self.maximum=max(self.maximum,self.active)
        try:
            await asyncio.sleep(self.delay)
            if any(s in prompt for s in self.fail):raise AppError('IMAGE_REJECTED','unavailable',502)
            return URL
        finally:self.active-=1


class Storage:
    def __init__(self):self.calls=[];self.threads=[]
    def upload(self,data,key):
        self.calls.append(key);self.threads.append(threading.current_thread().name)
        assert data==png()
        return 'https://images.example.com/'+key


class Planner:
    async def plan(self,quiz):
        return {q['id']:f'A red apple beside object {i+1} on a pale tabletop.' for i,q in enumerate(quiz['questions'])}


def setup(*,limit=20,provider=None,**values):
    from app.question_images.service import QuestionImages
    ledger,store=Ledger(limit),Storage()
    provider=provider or Provider()
    service=QuestionImages(None,config(**values),repository=ledger,provider=provider,storage=store,download=lambda u,c:png(),planner=Planner())
    return service,ledger,provider,store


@pytest.mark.anyio
async def test_five_questions_run_concurrently_and_map_to_stable_questions():
    service,ledger,provider,store=setup()
    original=quiz_payload(5)
    result=await service.attach('uid','operation',original)
    assert provider.maximum==5 and len(store.calls)==5 and ledger.remaining==15
    assert result['image_generation']=={'requested':5,'generated':5,'reason_code':None}
    assert len({q['image_url'] for q in result['questions']})==5
    assert all(name!='MainThread' for name in store.threads)
    assert all('image_url' not in q for q in original['questions'])
    again=await service.attach('uid','operation',original)
    assert len(provider.prompts)==5 and again==result


@pytest.mark.anyio
async def test_partial_quota_and_zero_quota_return_normal_questions():
    for limit,generated in [(2,2),(0,0)]:
        service,ledger,provider,_=setup(limit=limit)
        result=await service.attach('uid','operation',quiz_payload(5))
        assert result['image_generation']=={'requested':5,'generated':generated,'reason_code':'IMAGE_DAILY_LIMIT'}
        assert len(provider.prompts)==generated and len(result['questions'])==5
        assert ledger.remaining==0


@pytest.mark.anyio
async def test_single_or_total_failure_does_not_change_text_or_retry():
    for failures,expected in [(('object 1',),2),(('object',),0)]:
        service,ledger,provider,_=setup(provider=Provider(fail=failures))
        quiz=quiz_payload()
        result=await service.attach('uid','operation',quiz)
        assert result['image_generation']['generated']==expected
        assert len(provider.prompts)==3 and ledger.remaining==17
        assert [q['stem'] for q in result['questions']]==[q['stem'] for q in quiz['questions']]
        await service.attach('uid','operation',quiz)
        assert len(provider.prompts)==3


@pytest.mark.anyio
async def test_stage_timeout_returns_text_and_does_not_retry_unknown_requests():
    service,ledger,provider,_=setup(provider=Provider(delay=1),IMAGE_STAGE_TIMEOUT_SECONDS=.03)
    result=await service.attach('uid','operation',quiz_payload())
    assert result['image_generation']['reason_code']=='IMAGE_TIMEOUT' and result['image_generation']['generated']==0
    assert ledger.remaining==17
    await service.attach('uid','operation',quiz_payload())
    assert len(provider.prompts)==3


@pytest.mark.anyio
async def test_unavailable_config_deadline_and_cancelled_guard_do_not_request():
    service,ledger,provider,_=setup(QUIZ_IMAGES_ENABLED=False)
    result=await service.attach('uid','operation',quiz_payload())
    assert result['image_generation']['reason_code']=='IMAGE_DISABLED' and not provider.prompts and ledger.remaining==20
    service,ledger,provider,_=setup()
    assert (await service.attach('uid','op',quiz_payload(),seconds=0))['image_generation']['reason_code']=='IMAGE_TIMEOUT'
    async def guard():raise AppError('OPERATION_CANCELLED','cancelled',409)
    await service.attach('uid','operation',quiz_payload(),guard=guard)
    assert not provider.prompts and ledger.remaining==20


@pytest.mark.anyio
async def test_download_upload_and_ledger_failure_are_isolated():
    for boundary in ('download','upload','ledger'):
        service,ledger,provider,store=setup()
        def fail(*args,**kwargs):raise RuntimeError('private-body')
        if boundary=='download':service.download=fail
        elif boundary=='upload':store.upload=fail
        else:ledger.start=fail
        result=await service.attach('uid','operation',quiz_payload())
        assert result['image_generation']['generated']==0 and len(result['questions'])==3
        assert 'private-body' not in str(result)


@pytest.mark.anyio
async def test_external_cancellation_propagates():
    service,_,provider,_=setup(provider=Provider(delay=1))
    task=asyncio.create_task(service.attach('uid','operation',quiz_payload()))
    await asyncio.sleep(.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert provider.active==0


@pytest.mark.anyio
async def test_timeout_during_reservation_does_not_charge_an_unsent_request():
    import time
    service,ledger,provider,_=setup(IMAGE_STAGE_TIMEOUT_SECONDS=.01)
    original=ledger.start
    def slow(*args):time.sleep(.05);return original(*args)
    ledger.start=slow
    result=await service.attach('uid','operation',quiz_payload())
    assert result['image_generation']['generated']==0 and not provider.prompts
    await asyncio.sleep(.08)  # Observe the already-running reservation thread too.
    assert ledger.remaining==20
