import argparse
import json
from pathlib import Path
import pytest
from app.config import Settings
from scripts import live_grounding_eval as evaluation
from tests.helpers import grounding_payload
from app.quiz_grounding.models import ScopeContent


@pytest.mark.anyio
async def test_missing_provider_preflight_never_connects_database_or_model(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, 'ROOT', tmp_path)
    monkeypatch.setattr(evaluation, 'Settings', lambda **kwargs: Settings(_env_file=None, tavily_api_key='', deepseek_api_key='test-configured'))
    def forbidden(*args, **kwargs): raise AssertionError('preflight must not connect')
    monkeypatch.setattr(evaluation, 'Database', forbidden)
    args = argparse.Namespace(run_id='test-run', case=None, assess=False, cleanup=False, run=True, selections=None)
    assert await evaluation.run(args) == 2
    manifest = json.loads((tmp_path / 'docs/quiz-grounding/live-runs/test-run/manifest.json').read_text(encoding='utf8'))
    assert manifest['executed'] is False and manifest['blocked_reason'] == 'PROVIDER_NOT_CONFIGURED'
    assert len(manifest['cases']) == 20


def test_live_selection_requires_human_confirmation_and_current_preparation():
    prepared = {'id': 'current', 'version': 1, 'content': grounding_payload(ScopeContent, '')}
    assert evaluation.confirmed_selection(prepared, {'id': 'case'}, {}, False) is None
    selection = {'confirmed': True, 'preparation_id': 'old', 'scope_version': 1, 'candidate_id': 'c-http', 'focus_id': 'f-http', 'scope_point_ids': ['p-http']}
    with pytest.raises(ValueError): evaluation.confirmed_selection(prepared, {'id': 'case'}, {'case': selection}, False)
    selection['preparation_id'] = 'current'
    assert evaluation.confirmed_selection(prepared, {'id': 'case'}, {'case': selection}, False)['scope_point_ids'] == ['p-http']


def test_unexecuted_cases_cannot_be_assessed_as_passed(tmp_path):
    assert evaluation.assess(tmp_path, [{'id': 'not-run'}]) == 1
    result = json.loads((tmp_path / 'assessment.json').read_text(encoding='utf8'))
    assert result['passed'] is False and result['online_successes'] == 0
