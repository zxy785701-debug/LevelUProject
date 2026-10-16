"""Register the user's explicit chat confirmation of the existing review packet.

Only human-review metadata changes; provider results and prior attempts stay
intact. This command needs the saved direct-user confirmation as its input.
"""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'docs/quiz-grounding/live-runs'
CONFIRMATION = RUNS / 'human-confirmation-20261014.json'
PACKET = RUNS / 'review-20261014.json'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def payload_hash(record):
    payload = {k: v for k, v in record.items() if k != 'human_review'}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    confirmation = read(CONFIRMATION)
    if confirmation['quiz_review']['answer'] != '正确':
        raise ValueError('An explicit user confirmation of this packet is required')
    if confirmation['quiz_review'].get('registered_records'):
        print('The saved confirmation has already been registered.'); return
    packet = read(PACKET)
    if len(packet['rows']) != 20 or sum(len(r['quiz']['questions']) for r in packet['rows']) != 60:
        raise ValueError('The confirmed packet must contain the stated 20 cases and 60 questions')
    confirmation['quiz_review']['confirmed_packet_sha256'] = hashlib.sha256(PACKET.read_bytes()).hexdigest()
    registered = []
    for row in packet['rows']:
        path = (ROOT / row['file']).resolve()
        if not path.is_relative_to(RUNS.resolve()):
            raise ValueError('Record is outside the evaluation directory')
        record = read(path)
        if record['quiz']['id'] != row['quiz']['id'] or record['quiz'] != row['quiz']:
            raise ValueError('The quiz changed after the user reviewed the packet')
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        before = payload_hash(record)
        review = record['human_review']
        review['scope_matches_intent'] = True
        review['notes'] = '按用户对当前20例/60题核对请求的总体回复“正确”登记；未收到逐项表单导出。'
        review['confirmation'] = {'kind': 'direct_user_chat_overall_confirmation',
            'record': CONFIRMATION.relative_to(ROOT).as_posix(), 'answer': '正确',
            'individual_form_export_received': False,
            'structured_verdict_basis': 'registered_from_user_overall_confirmation'}
        for question in review['questions']:
            question['in_scope'] = True
            question['contradicts'] = False
            if question['status'] == 'source_backed':
                question['supported_by_cited_text'] = True
            if row['case'].get('expect_meme_majority'):
                # Content classification is an agent observation, distinct from
                # the human's overall correctness confirmation. Conservatively
                # exclude the comment-count question from substantive meme tests.
                question['meme_substantive'] = question['id'] != 'hs2-quotes-judge-1'
                question['meme_classification_basis'] = 'agent inspection of actual question and scene, not an individual user checkbox'
            question['notes'] = '正确性及引用支持按用户对核对包的总体确认登记；不是用户逐题表单输入。'
        if payload_hash(record) != before:
            raise AssertionError('Provider evidence must not change')
        write(path, record)
        if payload_hash(read(path)) != before:
            raise AssertionError('Provider evidence changed during serialization')
        registered.append({'case_id': row['case']['id'], 'quiz_id': row['quiz']['id'],
            'file': row['file'], 'original_file_sha256': original_hash,
            'provider_payload_sha256_before_and_after': before,
            'changed_fields': ['human_review']})
    confirmation['quiz_review']['registered_records'] = registered
    confirmation['quiz_review']['meme_classification_notes'] = '梗与场景分类由Codex检查实际题目，三例分别2/3、3/3、3/3；用户总体确认正确性，未单独提交梗覆盖复选项。'
    write(CONFIRMATION, confirmation)
    print('Registered user confirmation for 20 cases / 60 questions; provider evidence unchanged.')


if __name__ == '__main__':
    main()
