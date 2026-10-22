"""Authoritative verification metadata for performance reports; statistics stay unchanged."""
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
        def strings(value):
            if isinstance(value, str): yield value
            elif isinstance(value, dict):
                for item in value.values(): yield from strings(item)
            elif isinstance(value, (list, tuple)):
                for item in value: yield from strings(item)
        # Match verification assertions, not technical topics such as "已掌握验证模型".
        claim = re.compile(r'已(?!经?(?:掌握|了解|理解|学会|学习|熟悉|认识|练习|巩固|记住|懂得)).{0,4}(?:核实|核验|证实|验证)'
                           r'|联网.{0,4}(?:证明|确认|证实|核实|核验)')
        denial = re.compile(r'(?:尚未|并未|未曾|未|没有|无法|不能|不得)$'
                            r'|(?:不代表|不意味着|不能认为|不能说明|并非|不等于)[^，。；！？\n]{0,16}$')
        value = result.model_dump() if hasattr(result, 'model_dump') else result
        for text in strings(value):
            for clause in re.split(r'[，。；！？\n]', text):
                for match in claim.finditer(clause):
                    if not denial.search(clause[:match.start()]):
                        raise AppError('MODEL_INVALID_OUTPUT', '复盘不能把未核实知识改写为已核实', 502)
