import pytest
from sqlalchemy import select,func
from app.accounts.database import Attempt
from app.question_images.service import QuestionImages
from tests.test_knowledge_repository import repo
from tests.test_knowledge_index import index
from tests.test_knowledge_quiz_publication import setup_quiz
from tests.test_question_images_transport import config,png
from tests.test_question_images_service import Provider,Storage,Planner


def setup_images(repo,index):
    # These direct pipeline calls have no Worker heartbeat. Lifecycle tests
    # advance lease state explicitly; native index speed must not expire it.
    now=repo.accounts.clock()
    repo.accounts.clock=lambda:now
    pipeline,_,gateway,_,body=setup_quiz(repo,index)
    provider=Provider()
    pipeline.images=QuestionImages(repo.accounts,config(),provider=provider,storage=Storage(),download=lambda u,c:png(),planner=Planner())
    job=pipeline.submit_quiz('alice','image-quiz',{**body,'generate_images':True})
    return pipeline,pipeline.claim('image-worker'),provider,gateway,job


def test_knowledge_images_are_published_and_recovered_without_new_calls(repo,index,monkeypatch):
    pipeline,claim,provider,gateway,job=setup_images(repo,index)
    original=pipeline.complete
    monkeypatch.setattr(pipeline,'complete',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('publication interrupted')))
    with pytest.raises(RuntimeError):pipeline.process(claim)
    assert len(provider.prompts)==3
    with repo.database.session() as s:assert s.scalar(select(func.count()).select_from(Attempt))==0
    monkeypatch.setattr(pipeline,'complete',original)
    result=pipeline.process(claim)
    assert all(q['image_url'] for q in result['quiz']['questions'])
    assert len(provider.prompts)==3 and result['quiz']['image_generation']['generated']==3
    restored=pipeline.get('alice',job['id'])['result']
    assert restored['id']==result['id'] and restored['quiz']==result['quiz']
    assert pipeline.process(claim)==restored
    with repo.database.session() as s:assert s.scalar(select(func.count()).select_from(Attempt))==1


def test_knowledge_visual_plan_is_counted_and_reused_after_publication_interruption(repo,index,monkeypatch):
    from app.knowledge.database import Job
    from tests.test_question_images_planning import Gateway
    pipeline,claim,provider,gateway,job=setup_images(repo,index)
    pipeline.images.planner=None
    planner=Gateway()
    class Combined:
        async def generate(self,schema,prompt,check=None):
            return await (planner if schema.__name__=='VisualScenes' else gateway).generate(schema,prompt,check)
    pipeline.gateway=Combined()
    original=pipeline.complete
    monkeypatch.setattr(pipeline,'complete',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('publication interrupted')))
    with pytest.raises(RuntimeError):pipeline.process(claim)
    with repo.database.session() as s:
        assert s.get(Job,job['id']).budget['model_calls']==3
    monkeypatch.setattr(pipeline,'complete',original)
    assert pipeline.process(claim)['quiz']['image_generation']['generated']==3
    assert len(planner.prompts)==1 and len(provider.prompts)==3


def test_knowledge_image_option_is_part_of_recovery_identity(repo,index):
    pipeline,_,_,_,body=setup_quiz(repo,index)
    from app.errors import AppError
    with pytest.raises(AppError):pipeline.submit_quiz('alice','quiz',{**body,'generate_images':True})


@pytest.mark.parametrize('action',['cancel','lease','delete'])
def test_late_images_cannot_publish_after_lifecycle_change(repo,index,action):
    from datetime import timedelta
    from app.knowledge.database import Job
    from app.accounts.database import User
    from app.errors import AppError
    pipeline,claim,provider,_,job=setup_images(repo,index)
    original=provider.generate
    changed=False
    async def generate(prompt,*,before_dispatch=None):
        nonlocal changed
        url=await original(prompt,before_dispatch=before_dispatch)
        if not changed:
            changed=True
            if action=='cancel':pipeline.cancel('alice',job['id'])
            else:
                with repo.database.session() as s:
                    if action=='lease':s.get(Job,job['id']).lease_until=repo.now()-timedelta(seconds=2)
                    else:s.delete(s.get(User,'alice'))
        return url
    provider.generate=generate
    with pytest.raises(AppError):pipeline.process(claim)
    assert changed and provider.prompts
    with repo.database.session() as s:
        assert s.scalar(select(func.count()).select_from(Attempt))==0
    assert not pipeline.images.storage.calls
