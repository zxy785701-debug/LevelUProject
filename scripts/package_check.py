from pathlib import Path
import json
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import Settings
secret=Settings().deepseek_api_key.get_secret_value()
result={}
artifacts=ROOT/'artifacts'
artifacts.mkdir(exist_ok=True)
for name,folder in [('weapp','dist'),('h5','dist-h5')]:
    base=ROOT/'frontend'/folder
    files=list(base.rglob('*'))
    files=[p for p in files if p.is_file()]
    leaked=any(secret.encode() in p.read_bytes() for p in files) if secret else False
    size=sum(p.stat().st_size for p in files)
    result[name]={'files':len(files),'bytes':size,'mib':round(size/1024/1024,3),'secret_in_build':leaked}
    with zipfile.ZipFile(artifacts/f'levelup-{name}.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in files:archive.write(p,p.relative_to(base))
result['weapp']['under_2_mib']=result['weapp']['bytes']<2*1024*1024
(ROOT/'docs/implementation/package-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
if any(v['secret_in_build'] for v in result.values()) or not result['weapp']['under_2_mib']:sys.exit(1)
