"""Opt-in real Tavily/DeepSeek acceptance, with explicit scope confirmation.

Uses only the dedicated test database. Never stores bearer tokens or secrets,
never clears tables and never counts fixtures or unverified fallback as online
success. Each completed case retains source snapshots for a separate human check.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys
import time

import httpx
from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.main import create_app
from app.accounts.database import Database, Operation, Attempt, TopicPreparation
from app.accounts.repository import Accounts
from app.quiz_grounding.models import ScopeContent
from app.models import Quiz

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name('grounding_eval_cases.json')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf8')


class UsageRecorder(logging.Handler):
    def __init__(self):
        super().__init__(); self.records = []

    def emit(self, record):
        if record.msg == 'model_response operation=%s attempt=%s usage=%s':
            operation, attempt, usage = record.args
            self.records.append({'operation': operation, 'attempt': attempt, 'tokens': usage})


def confirmed_selection(prepared, case, selections, interactive):
    """Only an explicitly supplied exact selection can submit a generation.

    Evaluation operators are recorded separately from final human reviewers.
    """
    scope = ScopeContent.model_validate(prepared['content'])
    selected = selections.get(case['id'])
    if selected is None and interactive:
        print(json.dumps({'case': case, 'preparation_id': prepared['id'], 'scope': prepared['content']}, ensure_ascii=False, indent=2), flush=True)
        print('确认领域/方向后输入 candidate_id focus_id point_id1,point_id2；输入 skip 跳过。', flush=True)
        try: value = input().strip().split()
        except EOFError: return None
        if len(value) == 3:
            selected = {'confirmed': True, 'preparation_id': prepared['id'], 'scope_version': prepared['version'], 'candidate_id': value[0], 'focus_id': value[1], 'scope_point_ids': value[2].split(',')}
    if not selected or selected.get('confirmed') is not True:
        return None
    if selected.get('preparation_id') != prepared['id'] or selected.get('scope_version') != prepared['version']:
        raise ValueError('Selection is for a different preparation/version')
    scope.selected(selected['candidate_id'], selected['focus_id'], selected['scope_point_ids'])
    return {'preparation_id': prepared['id'], 'scope_version': prepared['version'],
            'candidate_id': selected['candidate_id'], 'focus_id': selected['focus_id'],
            'scope_point_ids': selected['scope_point_ids'], 'question_count': 3, 'difficulty': 'easy'}


async def payload(client, method, path, body=None, key=None):
    started = time.monotonic()
    response = await client.request(method, '/api/v1' + path, json=body,
                                    headers={'Idempotency-Key': key} if key else None)
    if hasattr(client, 'grounding_timings'):
        client.grounding_timings.append({'method': method, 'path': path, 'status': response.status_code,
                                        'seconds': round(time.monotonic() - started, 3)})
    data = response.json()
    if response.status_code != 200 or data.get('code') != 0:
        raise RuntimeError(str(data.get('code', 'HTTP_ERROR')))
    return data['data']


def snapshots(database, uid):
    with database.session() as transaction:
        operations = transaction.scalars(select(Operation).where(Operation.user_id == uid)).all()
        return [{'key': op.key, 'kind': op.kind, 'status': op.status, 'stage': op.stage,
                 'model_calls': op.model_calls, 'tool_calls': op.tool_calls,
                 'page_attempts': op.page_attempts, 'charged': op.charged,
                 'retrieval': op.retrieval_log, 'error_code': op.error_code} for op in operations]


def assess(directory, cases):
    """Require a separate human verdict; do not infer truth from model approval."""
    rows = []
    for case in cases:
        path = directory / (case['id'] + '.json')
        record = json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
        quiz = record.get('quiz') or {}
        try:
            valid_quiz = Quiz.model_validate(quiz)
            structure = len(valid_quiz.questions) == 3 and sorted(q.type for q in valid_quiz.questions) == ['judge', 'multi', 'single']
        except ValueError:
            structure = False
        review = record.get('human_review') or {}
        questions = review.get('questions') or []
        complete = structure and len(questions) == len(quiz.get('questions', [])) and review.get('scope_matches_intent') in (True, False)
        complete = complete and all(q.get('in_scope') in (True, False) and q.get('contradicts') in (True, False)
            and (q.get('status') != 'source_backed' or q.get('supported_by_cited_text') in (True, False))
            and (not case.get('expect_meme_majority') or q.get('meme_substantive') in (True, False)) for q in questions)
        source_ids = {s['id'] for s in (quiz.get('source') or {}).get('segments', [])}
        ids_exist = all((q.get('grounding') or {}).get('status') != 'source_backed' or bool(q.get('source_ids')) and set(q['source_ids']) <= source_ids for q in quiz.get('questions', []))
        supported = complete and ids_exist and all(q.get('status') != 'source_backed' or q.get('supported_by_cited_text') is True for q in questions)
        in_scope = complete and review.get('scope_matches_intent') is True and all(q.get('in_scope') is True and q.get('contradicts') is False for q in questions)
        memes = not case.get('expect_meme_majority') or complete and sum(q.get('meme_substantive') is True for q in questions) >= 2
        rows.append({'id': case['id'], 'generated': bool(quiz), 'human_review_complete': complete,
                     'scope_passed': in_scope, 'citations_supported': supported, 'meme_coverage_passed': memes,
                     'online_success': bool(quiz) and (quiz.get('grounding') or {}).get('status') == 'source_backed'})
    passed = len(rows) >= 20 and all(r['human_review_complete'] for r in rows) and sum(r['scope_passed'] for r in rows) >= 18
    passed = passed and all(r['citations_supported'] and r['meme_coverage_passed'] for r in rows)
    result = {'passed': passed, 'required': '20 complete runs; >=18 valid scopes; all source-backed questions checked; >=2 substantive memes in meme-majority cases',
              'online_successes': sum(r['online_success'] for r in rows), 'cases': rows}
    write(directory / 'assessment.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if passed else 1


async def run(args):
    cases = json.loads(CASES.read_text(encoding='utf8'))
    interactive = sys.stdin.isatty() and not getattr(args, 'non_interactive', False)
    if getattr(args, 'failure_probes', False):
        cases += json.loads(CASES.with_name('grounding_eval_failure_cases.json').read_text(encoding='utf8'))
    if args.case:
        cases = [case for case in cases if case['id'] in args.case]
        if not cases: raise ValueError('Unknown case id')
    # Restrict the output to a named child of this workspace's acceptance folder.
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.run_id):
        raise ValueError('run-id must use letters, digits, hyphen or underscore')
    directory = ROOT / 'docs/quiz-grounding/live-runs' / args.run_id
    if args.assess: return assess(directory, cases)
    settings = Settings(database_testing=True)
    configured = {'tavily': bool(settings.tavily_api_key.get_secret_value()), 'deepseek': bool(settings.deepseek_api_key.get_secret_value())}
    manifest = {'run_id': args.run_id, 'providers': ['Tavily official LangChain Search/Extract', 'existing DeepSeek model'],
                'configured': configured, 'database': settings.mysql_test_database,
                'model': settings.deepseek_model, 'minute_limit': settings.ai_minute_limit,
                'preparation_deadline_seconds': settings.topic_prepare_timeout_seconds,
                'generation_deadline_seconds': settings.grounded_generation_timeout_seconds,
                'cases': cases, 'executed': False, 'blocked_reason': None}
    if not all(configured.values()) and not args.cleanup:
        manifest['blocked_reason'] = 'PROVIDER_NOT_CONFIGURED'
        write(directory / 'preflight.json', manifest)
        if not (directory / 'manifest.json').exists(): write(directory / 'manifest.json', manifest)
        print('真实评测未执行：请在 backend/.env 配置所需服务；未调用模型，未连接测试库。', flush=True)
        return 2
    if not args.run and not args.cleanup:
        write(directory / 'preflight.json', manifest)
        if not (directory / 'manifest.json').exists(): write(directory / 'manifest.json', manifest)
        print('配置检查通过。使用 --run 开始真实评测（会产生服务调用费用）。', flush=True)
        return 0
    database = Database(settings)
    assert settings.database_testing and settings.mysql_test_database.endswith('_test') and settings.mysql_test_database != settings.mysql_database
    with database.engine.connect() as connection:
        actual_database = connection.scalar(text('SELECT DATABASE()'))
        assert actual_database == settings.mysql_test_database and actual_database != settings.mysql_database
    database.migrate()
    accounts = Accounts(settings, database)
    class EvaluationWeChat:
        async def exchange(self, code):
            return {'openid': code, 'unionid': None}
    app = create_app(settings, accounts=accounts, wechat=EvaluationWeChat())
    recorder = UsageRecorder()
    logger = logging.getLogger('app.llm'); old_level = logger.level
    logger.setLevel(logging.INFO); logger.addHandler(recorder)
    manifest['executed'] = bool(args.run); write(directory / 'manifest.json', manifest)
    incomplete = False
    try:
        for case in cases:
            record_path = directory / (case['id'] + '.json')
            old = json.loads(record_path.read_text(encoding='utf8')) if record_path.exists() else {}
            if old.get('quiz') and not args.cleanup:
                continue  # Resume never repeats a completed paid generation.
            if args.cleanup and old.get('account_deleted'):
                continue
            identity = {'openid': 'grounding-eval-' + args.run_id + '-' + case['id'], 'unionid': None}
            begin = time.monotonic(); usage_start = len(recorder.records); uid = None
            record = {**old, 'case': case, 'error_code': None, 'status': 'preparing'}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', timeout=360) as client:
                client.grounding_timings = []
                try:
                    login = await payload(client, 'POST', '/auth/wechat', {'code': identity['openid'], 'agreement_version': '2026-10-12'})
                    uid = login['user']['id']; client.headers['Authorization'] = 'Bearer ' + login['token']
                    if args.cleanup:
                        record['status'] = 'cleaned'; continue
                    entry = await payload(client, 'POST', '/quiz/preparations', {'text': case['text']}, 'prepare-' + case['id'])
                    if entry.get('kind') == 'material_entry':
                        job = await payload(client, 'POST', '/materials/web', {'url': entry['url'], 'learning_instruction': entry.get('learning_instruction')}, 'page-' + case['id'])
                        job = await payload(client, 'GET', '/material-jobs/' + job['id'])
                        record['material_job'] = job
                        if job.get('preparation_id'):
                            prepared = await payload(client, 'GET', '/quiz/preparations/' + job['preparation_id'])
                        elif job.get('material_id'):
                            material = await payload(client, 'GET', '/materials/' + job['material_id'])
                            record['material'] = material; write(record_path, record)
                            selection = json.loads(Path(args.selections).read_text(encoding='utf8')).get(case['id']) if args.selections else None
                            if selection is None and interactive:
                                print(json.dumps({'case': case, 'material': material}, ensure_ascii=False, indent=2), flush=True)
                                print('确认指定材料范围后输入所选 segment_id（逗号分隔）；skip 跳过。', flush=True)
                                try: value = input().strip()
                                except EOFError: value = 'skip'
                                if value and value != 'skip': selection = {'confirmed': True, 'material_id': material['id'], 'point_ids': value.split(','), 'supplement': False}
                            if not selection or selection.get('confirmed') is not True:
                                record['status'] = 'awaiting_scope_confirmation'; incomplete = True; continue
                            if selection.get('material_id') != material['id']: raise ValueError('Selection is for a different material')
                            body = {'material_id': material['id'], 'point_ids': selection['point_ids'], 'supplement': selection.get('supplement', False), 'question_count': 3, 'difficulty': 'easy', 'execution': 'background'}
                            prepared = None
                        else: raise RuntimeError(job.get('error_code') or 'PAGE_UNREADABLE')
                    else: prepared = await payload(client, 'GET', '/quiz/preparations/' + entry['id'])
                    if prepared is not None:
                        record['preparation'] = prepared; write(record_path, record)
                        if prepared['status'] != 'ready': raise RuntimeError(prepared.get('error_code') or 'PREPARATION_FAILED')
                        selections = json.loads(Path(args.selections).read_text(encoding='utf8')) if args.selections else {}
                        body = confirmed_selection(prepared, case, selections, interactive)
                        if body is None:
                            record['status'] = 'awaiting_scope_confirmation'; incomplete = True; continue
                    record['confirmed_selection'] = body
                    operation = await payload(client, 'POST', '/quiz/generate', body, 'generate-' + case['id'])
                    operation = await payload(client, 'GET', '/operations/' + operation['key'])
                    record['operation'] = operation
                    if operation['status'] != 'succeeded': raise RuntimeError(operation.get('error_code') or 'GENERATION_FAILED')
                    with database.session() as transaction:
                        record['quiz'] = transaction.get(Attempt, operation['result']['id']).quiz
                    quiz = record['quiz']
                    record['human_review'] = {'scope_matches_intent': None, 'notes': '', 'questions': [
                        {'id': q['id'], 'status': (q.get('grounding') or {}).get('status', 'unknown'),
                         'source_ids': q.get('source_ids', []), 'supported_by_cited_text': None,
                         'contradicts': None, 'in_scope': None, 'meme_substantive': None, 'notes': ''}
                        for q in quiz['questions']]}
                    record['status'] = 'awaiting_human_evidence_review'
                except Exception as exc:
                    # Provider exception messages may contain request metadata. Only
                    # allow fixed uppercase application codes into exported evidence.
                    code = str(exc)
                    record['error_code'] = code if code and len(code) <= 64 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for c in code) else type(exc).__name__
                    record['status'] = 'failed'; incomplete = True
                finally:
                    record['wall_attempt_seconds'] = old.get('wall_attempt_seconds', []) + [round(time.monotonic() - begin, 3)]
                    record['elapsed_seconds'] = round(sum(record['wall_attempt_seconds']), 3)
                    record['api_timings'] = old.get('api_timings', []) + client.grounding_timings
                    record['structured_model_usage'] = old.get('structured_model_usage', []) + recorder.records[usage_start:]
                    if uid:
                        record['operations'] = snapshots(database, uid)
                        with database.session() as transaction:
                            preparations = transaction.scalars(select(TopicPreparation).where(TopicPreparation.user_id == uid)).all()
                            record['retrieval_preparations'] = [p.content for p in preparations]
                        if record.get('quiz') or args.cleanup:
                            accounts.delete_account(uid, identity)
                            record['account_deleted'] = True
                    write(record_path, record)
                    print(case['id'] + ': ' + record['status'], flush=True)
    finally:
        logger.removeHandler(recorder); logger.setLevel(old_level); database.engine.dispose()
    return 1 if incomplete else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='acceptance-20261014')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--case', action='append')
    parser.add_argument('--failure-probes', action='store_true', help='Also run explicit unreadable-page and sparse-evidence probes')
    parser.add_argument('--non-interactive', action='store_true', help='Save prepared scopes without prompting when exact selections are not provided')
    parser.add_argument('--selections', help='Explicit evaluation-operator selections, keyed by case id')
    parser.add_argument('--assess', action='store_true')
    parser.add_argument('--cleanup', action='store_true', help='Delete only this run own test accounts')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
