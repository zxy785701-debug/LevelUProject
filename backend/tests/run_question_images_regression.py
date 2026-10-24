"""Sequential full-suite batches; fresh processes bound real-index test overhead."""
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def verify(output):
    cases=(output/'cases.txt').read_text(encoding='utf-8').splitlines()
    expected=set()
    for node in cases:
        file,_,name=node.partition('::')
        expected.add((file[:-3].replace('/','.'),name))
    results={}
    initial_failures=[]
    for file in sorted(output.glob('batch-*.xml')):
        for case in ET.parse(file).iter('testcase'):
            key=(case.get('classname'),case.get('name'))
            if key in results:raise RuntimeError('Duplicate original test evidence')
            passed=not any(case.find(tag) is not None for tag in ('failure','error','skipped'))
            results[key]=passed
            if not passed:initial_failures.append('::'.join(key))
    if set(results)!=expected:raise RuntimeError('Incomplete full regression evidence')
    reruns=[]
    for file in sorted(output.glob('*rerun.xml')):
        for case in ET.parse(file).iter('testcase'):
            key=(case.get('classname'),case.get('name'))
            if key not in results or results[key]:raise RuntimeError('Unexpected rerun')
            passed=not any(case.find(tag) is not None for tag in ('failure','error','skipped'))
            results[key]=passed
            reruns.append({'case':'::'.join(key),'passed':passed,'evidence':file.name})
    if not all(results.values()):raise RuntimeError('Unresolved regression failure')
    report={'collected':len(cases),'verified_unique':len(results),'all_final_outcomes_passed':True,
        'initial_failures':initial_failures,'reruns':reruns,
        'illustration_cases':sum('test_question_images_' in node for node in cases)}
    (output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


def main():
    root=Path(__file__).resolve().parents[1]
    output=root.parent/'docs/quiz-images/live-20261024/regression'
    output.mkdir(parents=True,exist_ok=True)
    collected=subprocess.run([sys.executable,'-m','pytest','--collect-only','-q'],cwd=root,
        capture_output=True,text=True,encoding='utf-8')
    if collected.returncode:raise RuntimeError('Test collection failed')
    cases=[line.strip() for line in collected.stdout.splitlines() if line.startswith('tests/') and '::' in line]
    if not cases or len(cases)!=len(set(cases)):raise RuntimeError('Invalid full test inventory')
    (output/'cases.txt').write_text('\n'.join(cases)+'\n',encoding='utf-8')
    print(f'Collected {len(cases)} unique tests; running sequential batches.',flush=True)
    outcomes=[]
    for offset in range(0,len(cases),150):
        number=offset//150+1
        batch=cases[offset:offset+150]
        argument=output/f'batch-{number}.args'
        argument.write_text('\n'.join(batch)+'\n',encoding='utf-8')
        command=[sys.executable,'-u','-m','pytest','-q','--tb=short',f'--junitxml={output/f"batch-{number}.xml"}',f'@{argument}']
        print(f'Batch {number}: {len(batch)} tests',flush=True)
        with (output/f'batch-{number}.txt').open('w',encoding='utf-8') as log:
            process=subprocess.Popen(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
            for line in process.stdout:
                log.write(line);log.flush();print(line,end='',flush=True)
            code=process.wait()
        outcomes.append({'batch':number,'tests':len(batch),'exit_code':code})
        if code:return code
    actual=[]
    for file in sorted(output.glob('batch-*.xml')):
        for case in ET.parse(file).iter('testcase'):
            if case.find('failure') is not None or case.find('error') is not None:raise RuntimeError('Failed test in results')
            actual.append((case.get('classname'),case.get('name')))
    if len(actual)!=len(cases) or len(set(actual))!=len(cases):raise RuntimeError('Incomplete or duplicate test evidence')
    report={'collected':len(cases),'verified_unique':len(set(actual)),'batches':outcomes,'all_passed':True}
    (output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    return 0


if __name__=='__main__':
    if '--verify-only' in sys.argv:
        verify(Path(__file__).resolve().parents[2]/'docs/quiz-images/live-20261024/regression')
    else:sys.exit(main())
