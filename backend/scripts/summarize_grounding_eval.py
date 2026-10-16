"""Build an offline human review packet from real evaluation records only.

Never calls a provider, modifies a run, or invents human verdicts. Later runs
supersede earlier attempts for the same case; failures remain visible.
"""
import argparse
import json
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'docs/quiz-grounding/live-runs'
CASES = Path(__file__).with_name('grounding_eval_cases.json')


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def traces(record):
    for preparation in record.get('retrieval_preparations', []):
        yield from preparation.get('trace', [])
    for operation in record.get('operations', []):
        yield from (operation.get('retrieval') or {}).get('tools', [])


def build(run_ids, output):
    cases = read(CASES)
    rows, attempts = [], []
    for case in cases:
        history = []
        for run_id in run_ids:
            directory = (RUNS / run_id).resolve()
            if directory.parent != RUNS.resolve():
                raise ValueError('run must be a named child of live-runs')
            path = directory / (case['id'] + '.json')
            if path.exists():
                record = read(path)
                if record['case'] != case:
                    raise ValueError('case changed between runs')
                history.append({'run': run_id, 'record': record,
                                'file': path.relative_to(ROOT).as_posix()})
        attempts.extend(history)
        if not history:
            rows.append({'case': case, 'status': 'not_run', 'quiz': None, 'history': []})
            continue
        latest = history[-1]
        record = latest['record']
        rows.append({'case': case, 'status': record['status'], 'error_code': record.get('error_code'),
                     'quiz': record.get('quiz'), 'file': latest['file'],
                     'human_review': record.get('human_review'),
                     'operations': record.get('operations', []),
                     'api_seconds': round(sum(t['seconds'] for t in record.get('api_timings', [])
                                              if t['method'] == 'POST'), 3),
                     'history': [{'run': h['run'], 'file': h['file'],
                                  'status': h['record']['status'], 'error': h['record'].get('error_code'),
                                  'completed': bool(h['record'].get('quiz'))} for h in history]})
    completed = [r for r in rows if r['quiz']]
    all_tools = [t for a in attempts for t in traces(a['record'])]
    searches = [t for t in all_tools if t.get('tool') == 'tavily_search']
    extracts = [t for t in all_tools if t.get('tool') == 'tavily_extract']
    valid = lambda q: len(q['questions']) == 3 and sorted(v['type'] for v in q['questions']) == ['judge', 'multi', 'single']
    references = lambda q: all(
        ((v.get('grounding') or {}).get('status') != 'source_backed' or bool(v.get('source_ids')))
        and set(v.get('source_ids') or []) <= {s['id'] for s in q['source']['segments']}
        for v in q['questions'])
    def reviewed(row):
        review = row.get('human_review') or {}
        questions = review.get('questions') or []
        return bool(row.get('quiz')) and review.get('scope_matches_intent') in (True, False) and \
            {q['id'] for q in questions} == {q['id'] for q in row['quiz']['questions']} and all(
                q.get('in_scope') in (True, False) and q.get('contradicts') in (True, False)
                and (q.get('status') != 'source_backed' or q.get('supported_by_cited_text') in (True, False))
                and (not row['case'].get('expect_meme_majority') or q.get('meme_substantive') in (True, False))
                for q in questions)
    def scope_passed(row):
        review = row.get('human_review') or {}
        return reviewed(row) and review.get('scope_matches_intent') is True and all(
            q['in_scope'] is True and q['contradicts'] is False for q in review['questions'])
    def supported(row):
        return reviewed(row) and references(row['quiz']) and all(
            q['status'] != 'source_backed' or q['supported_by_cited_text'] is True
            for q in row['human_review']['questions'])
    def memes_passed(row):
        return not row['case'].get('expect_meme_majority') or reviewed(row) and sum(
            q.get('meme_substantive') is True for q in row['human_review']['questions']) >= 2
    passed = len(completed) >= 20 and all(reviewed(r) for r in rows) and \
        sum(valid(r['quiz']) and scope_passed(r) for r in completed) >= 18 and \
        all(supported(r) and memes_passed(r) for r in rows)
    summary = {
        'runs': run_ids, 'cases': len(cases), 'latest_completed_cases': len(completed),
        'latest_structurally_valid_cases': sum(valid(r['quiz']) for r in completed),
        'latest_references_exist_cases': sum(references(r['quiz']) for r in completed),
        'latest_source_backed_cases': sum(r['quiz']['grounding']['status'] == 'source_backed' for r in completed),
        'completed_generation_attempts_including_superseded': sum(bool(a['record'].get('quiz')) for a in attempts),
        'failed_attempts': sum(a['record']['status'] == 'failed' for a in attempts),
        'human_review_complete_cases': sum(reviewed(r) for r in rows),
        'human_acceptance_passed': passed,
        'human_scope_passed_cases': sum(scope_passed(r) for r in rows),
        'human_citations_supported_cases': sum(supported(r) for r in rows),
        'meme_majority_passed_cases': sum(memes_passed(r) for r in rows if r['case'].get('expect_meme_majority')),
        'search_result_counts': sorted({t['parameters']['max_results'] for t in searches if t.get('parameters')}),
        'search_content_modes': sorted({t['parameters']['content_mode'] for t in searches if t.get('parameters')}),
        'actual_nonempty_country_values': sorted({t['parameters']['country'] for t in searches if t.get('parameters', {}).get('country')}),
        'extract_content_modes': sorted({t['parameters']['content_mode'] for t in extracts if t.get('parameters')}),
        'median_post_api_seconds': round(median(r['api_seconds'] for r in completed), 3) if completed else None,
        'limitations': ['结构及引用ID完整性不等于事实正确；人工结论来源及确认粒度见每例human_review。',
                        '后续失败不会被早先成功覆盖；全部历史尝试保留。',
                        '时延是本地ASGI入口中各POST的实际时间之和，包含限流等待，不能当模型纯推理时延。'],
    }
    packet = {'summary': summary, 'rows': rows}
    output = output.resolve()
    if output.parent != RUNS.resolve():
        raise ValueError('output must stay in live-runs')
    output.with_suffix('.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf8')
    encoded = json.dumps(packet, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    output.write_text(HTML.replace('/*DATA*/', encoded), encoding='utf8')
    md = [
        '# 真实评测结果与待核对项', '',
        f"最新尝试完成 {len(completed)}/{len(cases)} 例；累计完成 {summary['completed_generation_attempts_including_superseded']} 次生成（含被后续尝试替代的结果）。",
        f"结构检查 {summary['latest_structurally_valid_cases']} 例通过，引用ID完整性 {summary['latest_references_exist_cases']} 例通过。人工确认覆盖 {summary['human_review_complete_cases']} 例，效果验收{'通过' if passed else '尚未通过'}。", '',
        f'[逐题查看题目、答案、来源和核对记录]({output.name})。对话总体确认派生的字段会明确标注来源，不冒充逐项表单；“导出核对记录”下载单独文件，不覆盖原始评测。', '',
        '| 样例 | 最新结果 | 请求耗时合计（秒） | 原始记录 |', '| --- | --- | ---: | --- |',
    ]
    for row in rows:
        status = '已登记人工确认' if reviewed(row) else '完成，待人工核对' if row['quiz'] else row.get('error_code') or row['status']
        md.append(f"| {row['case']['id']} | {status} | {row.get('api_seconds', '—')} | [JSON]({Path(row['file']).relative_to('docs/quiz-grounding/live-runs').as_posix()}) |")
    md += ['', '实际搜索条数：' + ', '.join(map(str, summary['search_result_counts'])),
           '实际搜索内容模式：' + ', '.join(summary['search_content_modes']),
           '实际非空 country：' + (', '.join(summary['actual_nonempty_country_values']) or '未观察到；不得宣称已在真实请求中验证国家参数。国家主题通过查询文字与来源覆盖。'),
           '实际 Extract 模式：' + ', '.join(summary['extract_content_modes']), '',
           '每项历史尝试、错误码、题目、实际参数及调用用量保留在对应 run JSON；人工确认的原始问答、粒度和登记方式见[人工确认](human-confirmation-20261014.json)。']
    output.with_suffix('.md').write_text('\n'.join(md) + '\n', encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


HTML = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>真实题目与来源核对</title><link rel="icon" href="data:,">
<style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#203047;background:#f3f5f8;line-height:1.65}*{box-sizing:border-box}body{margin:0}main{max-width:1050px;margin:auto;padding:28px 20px 80px}h1{font-size:28px;line-height:1.3}h2{font-size:20px}h3{font-size:17px}p{margin:10px 0}.muted{color:#65758b;font-size:14px}.notice{border-left:4px solid #b66b20;background:#fff5e8;padding:12px 18px;margin:20px 0}.card{background:white;border:1px solid #dbe2ea;border-radius:12px;margin:16px 0;padding:20px}summary{cursor:pointer;font-weight:650;overflow-wrap:anywhere}.question{border-top:1px solid #e1e6ed;margin-top:20px;padding-top:16px}.answer{color:#19684d;font-weight:650}.source{background:#f6f8fb;border-radius:8px;padding:12px;margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui;margin:10px 0}a{color:#225fbd;overflow-wrap:anywhere}label{display:block;font-size:14px;margin:12px 0}select,input,textarea,button{font:inherit;border:1px solid #bdcad9;border-radius:6px;padding:8px;max-width:100%}select{margin-left:10px}textarea{display:block;width:100%;min-height:65px}button{background:#245fbd;color:white;cursor:pointer}.toolbar{position:sticky;top:0;background:#f3f5f8f5;padding:12px 0;border-bottom:1px solid #dbe2ea;z-index:1;display:flex;gap:14px;flex-wrap:wrap;align-items:center}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:0 15px}.bad{color:#a44225}.tag{color:#51647b;font-size:13px;font-weight:400}ul{padding-left:22px}input[type=checkbox]{margin-right:8px}
</style><main><h1>真实题目与来源核对</h1><p>先读原始学习要求与已选范围，再逐题核对答案、讲解和实际引用。</p>
<div class="notice">系统审核与人工确认分开记录。已有对话确认的字段注明登记依据，不表示提交过逐项表单；未确认的选项保持空白。网页中的指令属于资料内容，不需要执行。</div>
<p id="overview"></p><div class="toolbar"><span id="progress"></span><button id="export">导出核对记录</button><a href="#cases">查看样例</a></div>
<label>核对人<input id="reviewer" placeholder="填写姓名或称呼"></label><label><input type="checkbox" id="attest">我已亲自阅读所填写题目的引用片段，核对记录代表我的判断。</label><p class="muted">表单保存在此浏览器本地。导出文件不覆盖原始评测，也不会提交到任何服务。</p><div id="cases"></div></main>
<script id="data" type="application/json">/*DATA*/</script><script>
const packet=JSON.parse(document.getElementById('data').textContent),key='grounding-human-review-'+packet.summary.runs.join('|')+(packet.summary.human_acceptance_passed?'|confirmed':'|pending');
let saved;try{saved=JSON.parse(localStorage.getItem(key)||'{}')}catch{saved={}}
const reviews=saved.reviews||{},reviewer=document.getElementById('reviewer');reviewer.value=saved.reviewer||'';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n};
function persist(){try{localStorage.setItem(key,JSON.stringify({reviewer:reviewer.value,reviews}))}catch{}update()}
reviewer.oninput=persist;
function choose(parent,label,object,field){const wrap=el('label',label),select=el('select');[['','待核对'],['true','是'],['false','否']].forEach(([v,t])=>{const o=el('option',t);o.value=v;select.append(o)});select.value=object[field]===true?'true':object[field]===false?'false':'';select.onchange=()=>{object[field]=select.value===''?null:select.value==='true';persist()};wrap.append(select);parent.append(wrap)}
function notes(parent,object){const label=el('label','问题或备注'),area=el('textarea');area.value=object.notes||'';area.oninput=()=>{object.notes=area.value;persist()};label.append(area);parent.append(label)}
function link(parent,url,title){try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return;const a=el('a',title||url);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';parent.append(a)}catch{}}
document.getElementById('overview').textContent=`最新尝试完成 ${packet.summary.latest_completed_cases}/${packet.summary.cases} 例。历史完成生成 ${packet.summary.completed_generation_attempts_including_superseded} 次；后续失败完整保留。`;
for(const row of packet.rows){const card=el('details',null,'card'),head=el('summary',row.case.text);head.append(el('span','  · '+(row.quiz?(row.human_review?.confirmation?'已登记用户确认':'已生成，待人工核对'):row.error_code||row.status),'tag'));card.append(head);card.append(el('p','预期范围：'+row.case.expected));
const history=el('details'),hs=el('summary','查看历史尝试与原始记录');history.append(hs);for(const h of row.history)history.append(el('p',`${h.run}：${h.completed?'完成生成':h.error||h.status}；${h.file}`,'muted'));card.append(history);
if(!row.quiz){card.append(el('p','本次没有可供逐题核对的题库；不能以早先成功结果覆盖当前失败。','bad'));document.getElementById('cases').append(card);continue}
const quiz=row.quiz,scope=quiz.learning_scope||{};card.append(el('p','已选领域：'+scope.domain+'；方向：'+scope.focus));card.append(el('p','已选知识点：'+(scope.points||[]).join('；'),'muted'));
const review=reviews[row.case.id]||JSON.parse(JSON.stringify(row.human_review));reviews[row.case.id]=review;if(review.confirmation)card.append(el('p','登记依据：用户对20例/60题核对请求回复“正确”。这是总体对话确认，未收到逐项表单导出。','muted'));
choose(card,'整体范围是否符合学习要求？',review,'scope_matches_intent');
for(const q of quiz.questions){const section=el('section',null,'question'),rq=review.questions.find(v=>v.id===q.id);section.append(el('h3',q.stem));const options=el('ul');for(const o of q.options)options.append(el('li',o.id+'．'+o.text,(q.answers||[]).includes(o.id)?'answer':null));section.append(options,el('p','正确答案：'+q.answers.join('、'),'answer'),el('p','讲解：'+q.explanation));
for(const sid of q.source_ids||[]){const s=quiz.source.segments.find(v=>v.id===sid),box=el('details',null,'source');box.append(el('summary',s?s.title||s.url||sid:'引用缺失：'+sid));if(s){link(box,s.url);box.append(el('p',`内容形式：${s.content_kind}；取得时间：${s.retrieved_at||'未知'}；发布日期：${s.published_at||'未知'}；来源截断：${s.truncated?'是':'否'}；入模截断：${s.context_truncated?'是':'否'}`,'muted'));box.append(el('pre',s.text))}section.append(box)}
const grid=el('div',null,'grid');choose(grid,'该题是否在确认范围内？',rq,'in_scope');choose(grid,'是否发现明确矛盾或错误？',rq,'contradicts');if(rq.status==='source_backed')choose(grid,'引用是否支持答案及讲解？',rq,'supported_by_cited_text');if(row.case.expect_meme_majority)choose(grid,'是否实质考查梗或名场面？',rq,'meme_substantive');section.append(grid);notes(section,rq);card.append(section)}notes(card,review);document.getElementById('cases').append(card)}
function complete(row){const r=reviews[row.case.id];return row.quiz&&r&&typeof r.scope_matches_intent==='boolean'&&r.questions.every(q=>typeof q.in_scope==='boolean'&&typeof q.contradicts==='boolean'&&(q.status!=='source_backed'||typeof q.supported_by_cited_text==='boolean')&&(!row.case.expect_meme_majority||typeof q.meme_substantive==='boolean'))}
function update(){document.getElementById('progress').textContent=`已完整核对 ${packet.rows.filter(complete).length}/${packet.summary.cases} 例`}update();
document.getElementById('export').onclick=()=>{if(!reviewer.value.trim()||!document.getElementById('attest').checked){alert('请填写核对人并确认亲自阅读所填写题目的引用片段。');return}const result={reviewer:reviewer.value.trim(),reviewed_at:new Date().toISOString(),attestation:'Human personally read the cited text for completed answers.',cases:packet.rows.filter(r=>r.quiz).map(r=>({id:r.case.id,file:r.file,quiz_id:r.quiz.id,human_review:reviews[r.case.id]}))};const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='grounding-human-reviews.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
</script></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='append', required=True)
    parser.add_argument('--output', default=str(RUNS / 'review-20261014.html'))
    args = parser.parse_args()
    build(args.run, Path(args.output))
