import asyncio
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.helpers import quiz_payload
from tests.test_question_images_service import setup


class Gateway:
    def __init__(self, items=None):
        self.items = items
        self.prompts = []

    async def generate(self, schema, prompt, check=None):
        self.prompts.append(prompt)
        result = schema.model_validate({'scenes': self.items or [
            {'question_id': f'q{i}', 'description': f'A red apple beside {i+1} green leaves on a pale table.'}
            for i in range(3)]})
        if check:
            check(result)
        return result


@pytest.mark.anyio
async def test_batch_planner_excludes_answers_and_outputs_scene_only():
    from app.question_images.planning import VisualPlanner, scene_prompt
    quiz = quiz_payload()
    quiz['questions'][0].update(stem='What fruit is an apple?', answers=['ANSWER_SECRET'],
        options=[{'id': 'A', 'text': 'OPTION_SECRET'}], explanation='EXPLANATION_SECRET')
    gateway = Gateway()
    scenes = await VisualPlanner(gateway).plan(quiz)
    assert len(gateway.prompts) == 1 and set(scenes) == {'q0', 'q1', 'q2'}
    assert all(secret not in gateway.prompts[0] for secret in ('ANSWER_SECRET','OPTION_SECRET','EXPLANATION_SECRET'))
    prompt = scene_prompt(scenes['q0'])
    assert 'red apple' in prompt and 'What fruit' not in prompt and '{' not in prompt


@pytest.mark.anyio
@pytest.mark.parametrize('items', [
    [{'question_id': 'q0', 'description': 'A red apple on a table.'}],
    [{'question_id': 'q0', 'description': 'A red apple on a table.'}]*3,
    [{'question_id': f'q{i}', 'description': '英语题目文字海报'} for i in range(3)],
    [{'question_id': f'q{i}', 'description': 'What fruit is an apple?'} for i in range(3)],
])
async def test_missing_duplicate_or_nonvisual_plan_is_rejected(items):
    from app.question_images.planning import VisualPlanner
    with pytest.raises((ValidationError, ValueError)):
        await VisualPlanner(Gateway(items)).plan(quiz_payload())


@pytest.mark.anyio
async def test_plan_is_saved_and_recovery_does_not_call_text_or_image_model_twice():
    from app.question_images.planning import VisualPlanner
    service, ledger, provider, _ = setup()
    gateway = Gateway()
    service.planner = VisualPlanner(gateway)
    first = await service.attach('u', 'op', quiz_payload())
    assert first['image_generation']['generated'] == 3
    service.planner = VisualPlanner(Gateway())
    assert await service.attach('u', 'op', quiz_payload()) == first
    assert len(gateway.prompts) == 1 and not service.planner.gateway.prompts
    assert len(provider.prompts) == 3 and ledger.remaining == 17
    assert all('第 ' not in prompt and 'red apple' in prompt for prompt in provider.prompts)


@pytest.mark.anyio
async def test_planner_failure_is_optional_uncharged_and_not_repeated():
    service, ledger, provider, _ = setup()
    class Broken:
        calls = 0
        async def plan(self, quiz):
            self.calls += 1
            raise RuntimeError('private-text-model-body')
    service.planner = Broken()
    for _ in range(2):
        result = await service.attach('u', 'op', quiz_payload())
        assert result['image_generation']['generated'] == 0
        assert 'private' not in json.dumps(result)
    assert service.planner.calls == 1 and ledger.remaining == 20 and not provider.prompts


@pytest.mark.anyio
async def test_planner_is_skipped_for_zero_quota_and_cancelled_operations():
    from app.errors import AppError
    service, ledger, provider, _ = setup(limit=0)
    gateway = Gateway()
    from app.question_images.planning import VisualPlanner
    service.planner = VisualPlanner(gateway)
    result = await service.attach('u', 'op', quiz_payload())
    assert result['image_generation']['reason_code'] == 'IMAGE_DAILY_LIMIT'
    assert not gateway.prompts and not provider.prompts
    service, ledger, provider, _ = setup()
    service.planner = VisualPlanner(gateway)
    async def guard():
        raise AppError('OPERATION_CANCELLED', 'cancelled', 409)
    result = await service.attach('u', 'op', quiz_payload(), guard=guard)
    assert not gateway.prompts and not provider.prompts and ledger.remaining == 20


@pytest.mark.anyio
async def test_description_timeout_bounds_entire_image_stage_without_quota_charge():
    service, ledger, provider, _ = setup(IMAGE_STAGE_TIMEOUT_SECONDS=.03)
    class Slow:
        calls = 0
        async def plan(self, quiz):
            self.calls += 1
            await asyncio.sleep(1)
    service.planner = Slow()
    result = await asyncio.wait_for(service.attach('u', 'op', quiz_payload()), .3)
    assert result['image_generation']['reason_code'] == 'IMAGE_TIMEOUT'
    assert not provider.prompts and ledger.remaining == 20
    await service.attach('u', 'op', quiz_payload())
    assert service.planner.calls == 1


def test_plan_repository_claim_is_persistent_isolated_and_protected_by_migration(system):
    from tests.test_question_images_repository import setup as database_setup
    from app.question_images.repository import ImageRepository
    from sqlalchemy import text
    accounts, uid, repo = database_setup(system)
    with accounts.database.engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '010_image_dispatch'
    assert repo.begin_plan(uid, 'op', 'a'*64)['fresh']
    recovered = ImageRepository(accounts, repo.config)
    assert recovered.begin_plan(uid, 'op', 'a'*64) == {'fresh':False, 'status':'started', 'scenes':None}
    scenes = {'q0':'A red apple on a pale table.'}
    assert repo.finish_plan(uid, 'op', scenes)
    assert recovered.begin_plan(uid, 'op', 'a'*64)['scenes'] == scenes
    assert not repo.finish_plan(uid, 'op', None)
    from app.errors import AppError
    with pytest.raises(AppError):
        repo.begin_plan(uid, 'op', 'b'*64)
    bob = accounts.login({'openid':'plan-bob'},'2026-10-12')['user']['id']
    assert repo.begin_plan(bob, 'op', 'a'*64)['fresh']
    assert repo.quota(uid)['remaining'] == 20


def test_concurrent_plan_claim_and_account_deletion(system):
    from concurrent.futures import ThreadPoolExecutor
    from tests.test_question_images_repository import setup as database_setup
    accounts,uid,repo=database_setup(system)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:repo.begin_plan(uid,'op','a'*64),range(5)))
    assert sum(r['fresh'] for r in results)==1
    accounts.delete_account(uid,{'openid':'image-alice'})
    assert not repo.finish_plan(uid,'op',{'q0':'A red apple on a pale table.'})


def test_plan_downgrade_refuses_before_altering_protected_schema(system):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from sqlalchemy import inspect,text
    from tests.test_question_images_repository import setup as database_setup
    accounts,uid,repo=database_setup(system)
    repo.begin_plan(uid,'op','a'*64)
    config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    with pytest.raises(RuntimeError),accounts.database.engine.begin() as connection:
        config.attributes['connection']=connection
        command.downgrade(config,'008_question_images')
    assert 'question_image_plans' in inspect(accounts.database.engine).get_table_names()
    with accounts.database.engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version'))=='010_image_dispatch'


from tests.test_mysql_accounts import system
