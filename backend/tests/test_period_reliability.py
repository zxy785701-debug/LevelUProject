import json
from copy import deepcopy

import pytest

from app.errors import AppError
from app.materials.services import period_narrative
from app.quiz_grounding.reporting import check_report_claims
from tests.helpers import FakeGateway


def snapshot(count=51):
    return {'sections': ['overview', 'performance', 'advice'],
            'current': {'totals': {'total': 53, 'correct': 42, 'accuracy': 79}, 'trend': [], 'types': []},
            'previous': {'totals': {'total': 0, 'accuracy': None}, 'trend': [], 'types': []},
            'knowledge': {'topics': [{'id': 'topic-hash', 'name': 'FastAPI 学习', 'points': [
                {'id': f'{i:020x}', 'name': f'验证模型知识点 {i}', 'total': 1, 'correct': 0,
                 'accuracy': 0, 'status': 'weak', 'attempt_ids': ['private-attempt'],
                 'wrong_keys': ['private-wrong'], 'latest_at': '2026-10-16'} for i in range(count)]}]},
            'attempt_ids': ['private-attempt'],
            'provenance': [{'attempt_id': 'private-attempt', 'quiz_id': 'private-quiz', 'title': 'FastAPI 学习',
                            'verification': {'status': 'unknown', 'counts': {'unknown': 3}},
                            'source': {'title': 'private-source', 'segments': [{'text': 'private source body', 'url': 'https://private.example'}]},
                            'learning_scope': {'input_text': 'private learning instructions'}}]}


class AliasGateway:
    def __init__(self): self.prompt = ''
    async def generate(self, schema, prompt, check=None):
        self.prompt = prompt
        result = schema.model_validate({'summary': ['继续练习验证模型的应用。'],
            'findings': [{'point_id': 'p51', 'analysis': '理解还需要通过练习巩固。'}],
            'suggestions': [{'point_id': 'p1', 'action': '用自己的话解释概念，再练习一题。'}]})
        if check: check(result)
        return result


@pytest.mark.anyio
async def test_short_model_references_map_back_to_real_ids_without_changing_snapshot():
    original = snapshot()
    unchanged = deepcopy(original)
    gateway = AliasGateway()
    result = await period_narrative(original, gateway)
    assert result['findings'][0]['point_id'] == original['knowledge']['topics'][0]['points'][50]['id']
    assert result['suggestions'][0]['point_id'] == original['knowledge']['topics'][0]['points'][0]['id']
    assert original == unchanged
    for private in ['private-attempt', 'private-wrong', 'private-quiz', 'private-source',
                    'private source body', 'private learning instructions', 'private.example']:
        assert private not in gateway.prompt
    assert original['knowledge']['topics'][0]['points'][50]['id'] not in gateway.prompt
    assert '"p51"' in gateway.prompt
    assert '"action"' in gateway.prompt and '"analysis"' in gateway.prompt
    assert len(gateway.prompt) < 15000


@pytest.mark.anyio
async def test_unknown_short_reference_is_rejected():
    gateway = FakeGateway({'summary': ['继续学习。'], 'findings': [],
                           'suggestions': [{'point_id': 'p999', 'action': '练习。'}]})
    with pytest.raises(AppError) as error: await period_narrative(snapshot(), gateway)
    assert error.value.code == 'MODEL_INVALID_OUTPUT'


@pytest.mark.parametrize('text', [
    '已经掌握验证模型的基本用法，继续练习。',
    '已了解验证字段与业务校验的区别。',
    '未联网，无法确认这些结论。',
    '这些知识尚未联网核实，需要回看原始材料。',
    '答对不代表知识已核实。',
])
def test_technical_validation_and_uncertainty_are_not_false_verification_claims(text):
    check_report_claims({'summary': [text]}, {'status': 'unknown', 'counts': {'unknown': 3}})


@pytest.mark.parametrize('text', ['所有知识已核实。', '知识已经联网核实。', '所有答案已被充分验证。', '联网已确认所有结论。',
    '这些知识已经完全核实。', '题库事实已经得到验证。', '所有结论已经过核验。', '答案已通过外部验证。', '已经完成了核验。'])
def test_actual_upgrades_of_unknown_knowledge_still_fail(text):
    with pytest.raises(AppError):
        check_report_claims({'summary': [text]}, {'status': 'unknown', 'counts': {'unknown': 3}})


def test_verification_uses_values_and_checks_mixed_source_counts():
    check_report_claims({'所有知识已核实': ['保持练习。', 3, None]}, {'status': 'unknown', 'counts': {}})
    check_report_claims({'summary': ['知识已经联网核实。']}, {'status': 'source_backed', 'counts': {'source_backed': 3}})
    with pytest.raises(AppError):
        check_report_claims({'nested': ({'analysis': '知识已经联网核实。'},)}, {'status': 'source_backed', 'counts': {'unknown': 1}})


def test_negation_does_not_hide_a_later_positive_claim():
    with pytest.raises(AppError):
        check_report_claims({'summary': ['未核实的知识已核实。']}, {'status': 'unknown', 'counts': {}})
    with pytest.raises(AppError):
        check_report_claims({'summary': ['不代表全部正确，但这些知识已经联网核实。']}, {'status': 'unknown', 'counts': {}})
