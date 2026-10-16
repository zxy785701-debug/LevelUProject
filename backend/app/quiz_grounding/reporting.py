"""Authoritative verification metadata for performance reports; statistics stay unchanged."""
import json
import re
from collections import Counter

from ..errors import AppError


def verification(quiz):
    states = [(q.get('grounding') or {}).get('status', 'unknown') for q in quiz['questions']]
    counts = dict(Counter(states))
    overall = (quiz.get('grounding') or {}).get('status', 'unknown')
    if counts.get('unverified'):
        overall = 'unverified'
    elif counts.get('unknown'):
        overall = 'unknown'
    return {'status': overall, 'counts': counts,
            'rule': '正确率与知识核实状态不同；未核实和旧题库的未知状态不能升级为已核实。'}


def check_report_claims(result, overview):
    counts = overview['counts']
    if overview['status'] in ('unverified', 'unknown') or counts.get('unverified') or counts.get('unknown'):
        text = json.dumps(result.model_dump() if hasattr(result, 'model_dump') else result, ensure_ascii=False)
        if re.search(r'已.{0,4}(?:核实|核验|证实|验证)|联网.{0,4}(?:证明|确认)', text):
            raise AppError('MODEL_INVALID_OUTPUT', '复盘不能把未核实知识改写为已核实', 502)
