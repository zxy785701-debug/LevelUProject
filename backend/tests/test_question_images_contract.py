import pytest
from pydantic import ValidationError
from app.models import GenerateRequest, Quiz, QuizContent
from app.knowledge.models import QuizRequest
from app.quiz_grounding.models import PublicQuestion, GenerationOperation
from tests.helpers import quiz_payload


def test_image_config_reuses_bailian_without_enabling_knowledge():
    from app.question_images.config import ImageSettings
    config = ImageSettings(_env_file=None, KNOWLEDGE_EMBEDDING_API_KEY='existing-key',
        KNOWLEDGE_EMBEDDING_BASE_URL='https://workspace.cn-beijing.maas.aliyuncs.com/api/v1')
    assert config.api_key.get_secret_value() == 'existing-key'
    assert config.base_url == 'https://workspace.cn-beijing.maas.aliyuncs.com/api/v1'
    assert (config.model, config.size, config.daily_limit, config.concurrency) == ('qwen-image-2.0', '512*512', 20, 5)
    assert 'existing-key' not in repr(config)


def test_optional_configuration_and_https_validation():
    from app.question_images.config import ImageSettings, load_settings
    config = ImageSettings(_env_file=None)
    assert config.unavailable_reason() == 'IMAGE_NOT_CONFIGURED'
    for field, value in [('COS_PUBLIC_BASE_URL','http://images.example.com'), ('COS_PUBLIC_BASE_URL','https://images.example.com/?token=secret'),
                         ('IMAGE_BASE_URL','https://attacker.example/api/v1'), ('IMAGE_CONCURRENCY',6)]:
        with pytest.raises(ValidationError): ImageSettings(_env_file=None, **{field:value})
    config, error = load_settings({'IMAGE_CONCURRENCY':'invalid'})
    assert config is None and error == 'IMAGE_CONFIGURATION_INVALID'


def test_requests_default_off_and_are_strict():
    assert GenerateRequest(text='apple').generate_images is False
    body = dict(scope_id='scope',scope_version=1,candidate_ids=['topic'])
    assert QuizRequest(**body).generate_images is False
    assert GenerateRequest(text='apple',generate_images=True).generate_images is True
    for schema, data in [(GenerateRequest,{'text':'apple'}),(QuizRequest,body)]:
        for invalid in ('false',1,None):
            with pytest.raises(ValidationError): schema(**data,generate_images=invalid)


def test_stored_and_public_images_do_not_change_ai_draft_schema():
    payload = quiz_payload()
    question = {**payload['questions'][0],'image_url':'https://images.example.com/q.png'}
    with pytest.raises(ValidationError): QuizContent.model_validate({**payload,'questions':[question,*payload['questions'][1:]]})
    quiz = Quiz.model_validate({**payload,'questions':[question,*payload['questions'][1:]],'id':'quiz',
        'created_at':'2026-10-22T00:00:00Z','source_text':'apple','difficulty':'easy',
        'image_generation':{'requested':3,'generated':1,'reason_code':'IMAGE_PARTIAL_FAILURE'}})
    assert quiz.questions[0].image_url.endswith('q.png')
    public = PublicQuestion.model_validate({**question,'answers':[],'explanation':''})
    assert public.image_url == question['image_url'] and not public.answers
    assert Quiz.model_validate({**quiz.model_dump(),'questions':payload['questions']}).questions[0].image_url is None
    for invalid in ('http://images.example.com/a.png','javascript:alert(1)','https://x.example/a?Expires=10'):
        with pytest.raises(ValidationError): PublicQuestion.model_validate({**question,'image_url':invalid})
    assert GenerationOperation(key='key',status='running',stage='generating_images',deadline='2026-10-22T00:00:00Z').stage == 'generating_images'
