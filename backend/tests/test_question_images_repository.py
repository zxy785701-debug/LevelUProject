from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from sqlalchemy import inspect, select, text
import pytest
from app.errors import AppError
from tests.test_mysql_accounts import system


def setup(system, limit=20):
    from app.question_images.config import ImageSettings
    from app.question_images.repository import ImageRepository
    a=system.state.accounts
    user=a.login({'openid':'image-alice'},'2026-10-12')['user']['id']
    config=ImageSettings(_env_file=None,IMAGE_DAILY_LIMIT=limit)
    return a,user,ImageRepository(a,config)


def test_migration_and_first_call_persists_across_repository_instances(system):
    a,uid,repo=setup(system)
    with a.database.engine.connect() as c:
        assert c.scalar(text('SELECT version_num FROM alembic_version')) == '010_image_dispatch'
    assert {'question_image_usage','question_image_calls','question_image_assets'} <= set(inspect(a.database.engine).get_table_names())
    result=repo.start(uid,'operation','q1','a'*64)
    assert result['fresh'] and result['status']=='started'
    assert repo.quota(uid)=={'remaining':19,'daily_limit':20}
    from app.question_images.repository import ImageRepository
    again=ImageRepository(a,repo.config).start(uid,'operation','q1','a'*64)
    assert not again['fresh'] and again['object_key']==result['object_key']
    assert repo.quota(uid)['remaining']==19
    with pytest.raises(AppError,match='参数'):
        repo.start(uid,'operation','q1','b'*64)


def test_success_failure_and_account_isolation(system):
    a,uid,repo=setup(system)
    repo.start(uid,'operation','q1','a'*64)
    assert repo.finish(uid,'operation','q1',image_url='https://images.example.com/1.png')
    assert repo.start(uid,'operation','q1','a'*64)['image_url'].endswith('1.png')
    assert not repo.finish(uid,'operation','q1',error='IMAGE_FAILED')
    repo.start(uid,'operation','q2','a'*64)
    repo.finish(uid,'operation','q2',error='IMAGE_TIMEOUT')
    assert repo.start(uid,'operation','q2','a'*64)['status']=='failed'
    bob=a.login({'openid':'image-bob'},'2026-10-12')['user']['id']
    assert repo.quota(bob)['remaining']==20
    assert repo.start(bob,'operation','q1','a'*64)['fresh']
    assert repo.quota(uid)['remaining']==18


def test_concurrent_calls_never_exceed_daily_limit(system):
    _,uid,repo=setup(system,2)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda i:repo.start(uid,'operation',f'q{i}','a'*64),range(5)))
    assert sum(r['fresh'] for r in results)==2
    assert sum(r['status']=='quota_exceeded' for r in results)==3
    assert repo.quota(uid)['remaining']==0


def test_shanghai_midnight_and_recovery_do_not_charge_new_day(system):
    a,uid,repo=setup(system)
    a.clock=lambda:datetime(2026,10,22,15,59,59,tzinfo=timezone.utc).timestamp()
    repo.start(uid,'old','q','a'*64)
    assert repo.quota(uid)['remaining']==19
    a.clock=lambda:datetime(2026,10,22,16,0,0,tzinfo=timezone.utc).timestamp()
    assert repo.quota(uid)['remaining']==20
    assert not repo.start(uid,'old','q','a'*64)['fresh']
    assert repo.quota(uid)['remaining']==20
    repo.start(uid,'new','q','a'*64)
    assert repo.quota(uid)['remaining']==19


def test_delete_account_preserves_quota_and_schedules_all_reserved_objects(system):
    from app.question_images.database import ImageAsset
    a,uid,repo=setup(system)
    call=repo.start(uid,'operation','q','a'*64)
    a.delete_account(uid,{'openid':'image-alice'})
    restored=a.login({'openid':'image-alice'},'2026-10-12')['user']['id']
    assert restored!=uid and repo.quota(restored)['remaining']==19
    assert not repo.finish(uid,'operation','q',image_url='https://images.example.com/late.png')
    with a.database.session() as s:
        asset=s.scalar(select(ImageAsset).where(ImageAsset.object_key==call['object_key']))
        assert asset.delete_after is not None


def test_cleanup_retries_and_does_not_remove_active_images(system):
    from app.question_images.database import ImageAsset
    from app.accounts.database import utcnow
    a,uid,repo=setup(system)
    call=repo.start(uid,'operation','q','a'*64)
    class Storage:
        fail=True
        calls=[]
        def delete(self,key,**kwargs):
            self.calls.append(key)
            if self.fail: raise RuntimeError('temporary')
    store=Storage()
    assert repo.cleanup(store)==0
    a.delete_account(uid,{'openid':'image-alice'})
    with a.database.session() as s:
        s.scalar(select(ImageAsset)).delete_after=utcnow()-timedelta(seconds=2)
    assert repo.cleanup(store)==0
    with a.database.session() as s:
        asset=s.scalar(select(ImageAsset))
        assert asset.attempts==1
        asset.delete_after=utcnow()-timedelta(seconds=2)
    store.fail=False
    assert repo.cleanup(store)==1 and store.calls==[call['object_key']]*2


def test_ledger_rejects_invalid_and_deleted_users(system):
    a,uid,repo=setup(system)
    for op,q,h in [('', 'q','a'*64),('o','','a'*64),('o','q','bad')]:
        with pytest.raises(ValueError):repo.start(uid,op,q,h)
    a.delete_account(uid,{'openid':'image-alice'})
    with pytest.raises(AppError):repo.start(uid,'o','q','a'*64)


def test_cancel_before_dispatch_refunds_only_the_original_day_once(system):
    a,uid,repo=setup(system)
    a.clock=lambda:datetime(2026,10,22,15,59,59,tzinfo=timezone.utc).timestamp()
    repo.start(uid,'op','q','a'*64)
    assert repo.quota(uid)['remaining']==19
    assert repo.abandon(uid,'op','q')
    assert repo.quota(uid)['remaining']==20
    assert not repo.abandon(uid,'op','q')
    repo.start(uid,'op','sent','a'*64)
    repo.finish(uid,'op','sent',image_url='https://images.example.com/a.png')
    assert not repo.abandon(uid,'op','sent')
    a.clock=lambda:datetime(2026,10,22,16,0,0,tzinfo=timezone.utc).timestamp()
    assert repo.quota(uid)['remaining']==20


def test_multi_version_downgrade_refusal_preserves_image_schema(system):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from app.knowledge.database import Document
    a,uid,repo=setup(system)
    with a.database.session() as session:
        session.add(Document(id='protected',user_id=uid,title='Keep',source_type='txt'))
    config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    with pytest.raises(RuntimeError),a.database.engine.begin() as connection:
        config.attributes['connection']=connection
        command.downgrade(config,'006_retrieval_audit')
    assert {'question_image_usage','question_image_calls','question_image_assets'}<=set(inspect(a.database.engine).get_table_names())
    a.database.migrate()
    assert repo.quota(uid)['remaining']==20
