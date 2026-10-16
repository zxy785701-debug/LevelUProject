import json

import pytest

from scripts import summarize_grounding_eval as summary


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf8')


def review_packet(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    runs = root / 'docs/quiz-grounding/live-runs'
    cases = [{'id': f'case-{i}', 'text': 'Learning task', 'expected': 'Selected topic',
              'expect_meme_majority': i == 0} for i in range(20)]
    case_file = root / 'cases.json'
    write(case_file, cases)
    monkeypatch.setattr(summary, 'ROOT', root)
    monkeypatch.setattr(summary, 'RUNS', runs)
    monkeypatch.setattr(summary, 'CASES', case_file)
    for case in cases:
        quiz = {'id': case['id'], 'grounding': {'status': 'source_backed'},
                'source': {'segments': [{'id': 's1'}]},
                'questions': [{'id': f'q{i}', 'type': kind, 'source_ids': ['s1'],
                               'grounding': {'status': 'source_backed'}}
                              for i, kind in enumerate(['single', 'multi', 'judge'])]}
        review = {'scope_matches_intent': True, 'questions': [
            {'id': q['id'], 'status': 'source_backed', 'in_scope': True,
             'contradicts': False, 'supported_by_cited_text': True,
             'meme_substantive': True} for q in quiz['questions']]}
        write(runs / 'first' / (case['id'] + '.json'), {
            'case': case, 'status': 'awaiting_human_evidence_review',
            'quiz': quiz, 'human_review': review})
    return runs


@pytest.mark.parametrize('failure', [None, 'missing_review', 'unsupported', 'wrong_scope', 'fake_source', 'missing_meme_majority'])
def test_summary_requires_complete_human_and_evidence_results(tmp_path, monkeypatch, failure):
    runs = review_packet(tmp_path, monkeypatch)
    first = runs / 'first/case-0.json'
    record = json.loads(first.read_text(encoding='utf8'))
    if failure == 'missing_review':
        record['human_review']['questions'][0]['supported_by_cited_text'] = None
    elif failure == 'unsupported':
        record['human_review']['questions'][0]['supported_by_cited_text'] = False
    elif failure == 'wrong_scope':
        record['human_review']['questions'][0]['in_scope'] = False
    elif failure == 'fake_source':
        record['quiz']['questions'][0]['source_ids'] = ['not-registered']
    elif failure == 'missing_meme_majority':
        for q in record['human_review']['questions'][:2]:
            q['meme_substantive'] = False
    write(first, record)
    summary.build(['first'], runs / 'review.html')
    result = json.loads((runs / 'review.json').read_text(encoding='utf8'))['summary']
    # One bad scope may be accepted by the specified >=18/20 threshold;
    # unsupported citations, missing reviews and insufficient memes never are.
    assert result['human_acceptance_passed'] is (failure in (None, 'wrong_scope'))
    assert result['human_scope_passed_cases'] == (19 if failure in ('wrong_scope', 'missing_review') else 20)


def test_later_failed_attempt_cannot_be_hidden_by_earlier_reviewed_quiz(tmp_path, monkeypatch):
    runs = review_packet(tmp_path, monkeypatch)
    first = json.loads((runs / 'first/case-0.json').read_text(encoding='utf8'))
    write(runs / 'retest/case-0.json', {'case': first['case'], 'status': 'failed',
                                      'error_code': 'INSUFFICIENT_KNOWLEDGE'})
    summary.build(['first', 'retest'], runs / 'review.html')
    packet = json.loads((runs / 'review.json').read_text(encoding='utf8'))
    assert packet['summary']['latest_completed_cases'] == 19
    assert packet['summary']['completed_generation_attempts_including_superseded'] == 20
    assert packet['summary']['human_acceptance_passed'] is False
    assert packet['rows'][0]['quiz'] is None
