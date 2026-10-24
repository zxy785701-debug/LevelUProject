import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

import pytest
from sqlalchemy import text

from app.question_images.service import QuestionImages
from tests.helpers import quiz_payload
from tests.test_mysql_accounts import system
from tests.test_question_images_repository import setup as database_setup
from tests.test_question_images_service import Provider,Storage,Planner,setup
from tests.test_question_images_transport import config,png


def test_dispatch_slot_is_shared_across_repository_instances(system):
    from app.question_images.repository import ImageRepository
    accounts,_,repo=database_setup(system)
    accounts.clock=lambda:1800000000.0
    first=repo.dispatch_slot()
    assert first==pytest.approx(1800000000.55)
    other=ImageRepository(accounts,repo.config)
    with ThreadPoolExecutor(max_workers=5) as pool:
        slots=list(pool.map(lambda _:other.dispatch_slot(),range(5)))
    assert sorted(s-1800000000 for s in slots)==pytest.approx([1.1,1.65,2.2,2.75,3.3],abs=.00001)
    accounts.clock=lambda:1800000004.0
    assert other.dispatch_slot()==pytest.approx(1800000004.55)
    with accounts.database.engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version'))=='010_image_dispatch'


@pytest.mark.anyio
async def test_smooth_dispatch_keeps_five_requests_in_flight(system):
    accounts,uid,_=database_setup(system)
    class Measured(Provider):
        starts=[]
        async def generate(self,prompt,*,before_dispatch=None):
            if before_dispatch:await before_dispatch()
            self.starts.append(time.monotonic())
            return await super().generate(prompt)
    provider=Measured(delay=.6)
    service=QuestionImages(accounts,config(IMAGE_MIN_REQUEST_INTERVAL_SECONDS=.045),provider=provider,
        planner=Planner(),storage=Storage(),download=lambda u,c:png())
    result=await service.attach(uid,'paced',quiz_payload(5))
    assert result['image_generation']['generated']==5 and provider.maximum==5
    assert all(b-a>=.03 for a,b in zip(provider.starts,provider.starts[1:]))
    assert service.repository.quota(uid)['remaining']==15


@pytest.mark.anyio
async def test_timeout_while_waiting_for_dispatch_refunds_unsent_requests():
    service,ledger,provider,_=setup(IMAGE_STAGE_TIMEOUT_SECONDS=.035)
    ledger.dispatch_slot=lambda:time.time()+1.0
    result=await service.attach('u','op',quiz_payload())
    assert result['image_generation']['reason_code']=='IMAGE_TIMEOUT'
    assert not provider.prompts and ledger.remaining==20
    assert all(call['error_code']=='IMAGE_NOT_STARTED' for call in ledger.calls.values())


@pytest.mark.anyio
async def test_guard_failure_before_dispatch_refunds_reservation():
    from app.errors import AppError
    service,ledger,provider,_=setup()
    def dispatch():raise AppError('OPERATION_CANCELLED','cancelled',409)
    ledger.dispatch_slot=dispatch
    result=await service.attach('u','op',quiz_payload())
    assert result['image_generation']['generated']==0
    assert not provider.prompts and ledger.remaining==20


@pytest.mark.anyio
async def test_rate_gate_runs_after_transport_preparation():
    service,ledger,_,_=setup()
    events=[]
    class PreparedProvider:
        async def generate(self,prompt,*,before_dispatch=None):
            events.append('prepared')
            if before_dispatch:await before_dispatch()
            events.append('sent')
            from tests.test_question_images_transport import URL
            return URL
    def dispatch():events.append('slot');return None
    ledger.dispatch_slot=dispatch
    service.provider=PreparedProvider()
    quiz=quiz_payload();quiz['questions']=quiz['questions'][:1]
    result=await service.attach('u','op',quiz)
    assert result['image_generation']['generated']==1
    assert events==['prepared','slot','sent']


@pytest.mark.anyio
async def test_stale_sql_ticket_is_rebooked_instead_of_sending_a_burst():
    service,ledger,provider,_=setup(IMAGE_MIN_REQUEST_INTERVAL_SECONDS=.55)
    slots=[]
    def ticket():
        slots.append(True)
        return time.time()-.2 if len(slots)==1 else time.time()+.015
    ledger.dispatch_slot=ticket
    quiz=quiz_payload();quiz['questions']=quiz['questions'][:1]
    result=await service.attach('u','op',quiz)
    assert result['image_generation']['generated']==1
    assert len(slots)==2 and len(provider.prompts)==1 and ledger.remaining==19
