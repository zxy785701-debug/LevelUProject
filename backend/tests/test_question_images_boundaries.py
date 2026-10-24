import asyncio
import httpx
import pytest
from app.errors import AppError
from tests.helpers import quiz_payload
from tests.test_question_images_transport import config, response
from tests.test_question_images_service import setup


@pytest.mark.anyio
async def test_optional_initialization_error_still_returns_reviewed_text(monkeypatch):
    import app.question_images.service as module
    monkeypatch.setattr(module,'load_settings',lambda:(config(),None))
    def broken(*args,**kwargs):raise RuntimeError('private-infrastructure-detail')
    monkeypatch.setattr(module,'QuestionImages',broken)
    result=await module.enrich_quiz(None,'uid','op',quiz_payload())
    assert len(result['questions'])==3 and result['image_generation']['reason_code']=='IMAGE_UNAVAILABLE'
    assert 'private-infrastructure-detail' not in str(result)


@pytest.mark.anyio
async def test_discarded_late_result_and_failed_status_write_remain_optional():
    service,ledger,_,_=setup()
    ledger.finish=lambda *a,**kw:False
    result=await service.attach('u','op',quiz_payload())
    assert result['image_generation']['generated']==0
    assert result['image_generation']['reason_code']=='IMAGE_RESULT_DISCARDED'
    service,ledger,_,_=setup()
    def failed(*args,**kwargs):raise RuntimeError('private-database-error')
    ledger.finish=failed
    result=await service.attach('u','op',quiz_payload())
    assert result['image_generation']['generated']==0
    assert ledger.remaining==17


@pytest.mark.anyio
async def test_enrichment_wrapper_cancellation_failure_and_budget(monkeypatch):
    from app.question_images import service as module
    class Broken:
        async def attach(self,*a,**kw):raise RuntimeError('private')
    result=await module.enrich_quiz(None,'u','op',quiz_payload(),service=Broken())
    assert result['image_generation']['reason_code']=='IMAGE_UNAVAILABLE'
    class Cancelled:
        async def attach(self,*a,**kw):raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await module.enrich_quiz(None,'u','op',quiz_payload(),service=Cancelled())
    monkeypatch.setattr(module,'load_settings',lambda:(config(IMAGE_STAGE_TIMEOUT_SECONDS=35),None))
    assert module.stage_budget()==35
    monkeypatch.setattr(module,'load_settings',lambda:(None,'invalid'))
    assert module.stage_budget()==90
    module.cleanup_images(None)


def test_cleanup_runs_when_new_requests_disabled_and_skips_missing_config(monkeypatch):
    from app.question_images import service as module
    from app.question_images.config import ImageSettings
    calls=[]
    monkeypatch.setattr(module,'load_settings',lambda:(ImageSettings(_env_file=None),None))
    module.cleanup_images(None)
    monkeypatch.setattr(module,'load_settings',lambda:(config(QUIZ_IMAGES_ENABLED=False),None))
    monkeypatch.setattr(module.ImageRepository,'__init__',lambda *a:None)
    monkeypatch.setattr(module.ImageRepository,'cleanup',lambda self,storage:calls.append(storage))
    module.cleanup_images(None)
    assert len(calls)==1
    # Removing the paid model credentials must not prevent account-image cleanup.
    from pydantic import SecretStr
    cos_only=config().model_copy(update={'api_key':SecretStr(''),'base_url':'','cos_bucket':'','cos_region':'','public_base_url':''})
    monkeypatch.setattr(module,'load_settings',lambda:(cos_only,None))
    module.cleanup_images(None)
    assert len(calls)==2
    monkeypatch.setattr(module.importlib.util,'find_spec',lambda name:None)
    module.cleanup_images(None)
    assert len(calls)==2


def test_dependencies_cos_configuration_and_stored_url_boundaries(monkeypatch):
    from app.question_images.config import ImageSettings
    from app.question_images.contracts import permanent_https,ImageGeneration
    from pydantic import ValidationError
    assert ImageSettings(_env_file=None,IMAGE_API_KEY='key',IMAGE_BASE_URL='https://dashscope.aliyuncs.com/api/v1').unavailable_reason()=='COS_NOT_CONFIGURED'
    monkeypatch.setattr('app.question_images.config.importlib.util.find_spec',lambda name:None)
    assert config().unavailable_reason()=='COS_DEPENDENCY_UNAVAILABLE'
    assert permanent_https('https://8.8.8.8/a.png')=='https://8.8.8.8/a.png'
    for url in ['https://127.0.0.1/a.png','https://[::1]/a.png','https://x.example:bad/a.png']:
        with pytest.raises(ValueError):permanent_https(url)
    with pytest.raises(ValidationError):ImageGeneration(requested=2,generated=3)


@pytest.mark.anyio
async def test_provider_oversized_metadata_network_error_and_invalid_url():
    from app.question_images.provider import QwenImages,result_url
    for value in [None,'x'*4097,'https://x.example:bad/a.png']:
        with pytest.raises(AppError):result_url(value)
    def network(request):raise httpx.ConnectError('private-address',request=request)
    with pytest.raises(AppError) as failure:
        await QwenImages(config(),transport=httpx.MockTransport(network)).generate('apple')
    assert failure.value.code=='IMAGE_UNAVAILABLE'
    for body in [{'padding':'x'*65537},response() | {'output':{'choices':[{'finish_reason':'length','message':{'content':[]}}]}}]:
        with pytest.raises(AppError):
            await QwenImages(config(),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))).generate('apple')


def test_cos_cleanup_error_is_sanitized(monkeypatch):
    from app.question_images.storage import CosImageStorage
    def broken(*args,**kwargs):raise RuntimeError('secret-provider-error')
    monkeypatch.setattr(CosImageStorage,'_client',broken)
    with pytest.raises(AppError) as failure:
        CosImageStorage(config()).delete('question-images/'+'a'*32+'.png')
    assert failure.value.code=='COS_DELETE_FAILED' and 'secret' not in str(failure.value)
