from datetime import date, datetime
from types import SimpleNamespace
from app.analytics import analytics_rows
from tests.helpers import quiz_payload


def test_analytics_weights_questions_instead_of_round_percentages():
    rounds = []
    for count, rights in ((3,3),(5,2)):
        quiz = quiz_payload(count)
        answers = [{'question_id': q['id'], 'selected': q['answers'] if i < rights else ['D'] if q['type'] != 'judge' else ['B'], 'elapsed_ms':1000} for i,q in enumerate(quiz['questions'])]
        rounds.append(SimpleNamespace(id=str(count),quiz_id=str(count),quiz=quiz,answers=answers,completed_at=datetime(2026,1,2)))
    result = analytics_rows(rounds, date(2026,1,2), date(2026,1,2))
    assert result['totals']['total'] == 8
    assert result['totals']['correct'] == 5
    assert result['totals']['accuracy'] == 63
    assert result['totals']['duration_ms'] == 8000
    assert result['types'][0]['total'] == 4


def test_no_data_is_not_zero_accuracy_and_duplicate_quizzes_do_not_inflate_totals():
    result = analytics_rows([], date(2026,1,1), date(2026,1,7))
    assert result['totals']['accuracy'] is None and len(result['trend']) == 7
    assert all(v['accuracy'] is None for v in result['trend'])
    quiz = quiz_payload()
    a = SimpleNamespace(id='one',quiz_id='same',quiz=quiz,answers=[{'question_id':q['id'],'selected':q['answers'],'elapsed_ms':0} for q in quiz['questions']],completed_at=datetime(2026,1,2))
    assert analytics_rows([a,a], date(2026,1,1), date(2026,1,7))['totals']['total'] == 3
