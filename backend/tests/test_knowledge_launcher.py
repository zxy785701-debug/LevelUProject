import json
from pathlib import Path
import subprocess
import sys
import pytest
from tests.test_knowledge_repository import repo


def test_cli_check_does_not_open_index_or_require_optional_credentials(repo,monkeypatch,capsys):
    from app.knowledge import worker
    monkeypatch.setattr('app.knowledge.config.load_settings',lambda:(repo.config,None))
    assert worker.main(['--check']) == 0
    state = json.loads(capsys.readouterr().out)
    assert state['enabled'] is False and state['start_worker'] is False
    assert not repo.config.storage_root.exists()
    repo.config.enabled = True
    assert worker.main(['--check']) == 0
    assert json.loads(capsys.readouterr().out)['reason_code'] == 'EMBEDDING_NOT_CONFIGURED'


def test_cli_enabled_and_disabled_process_smoke_uses_only_test_storage(repo):
    from app.knowledge.files import FileStore
    FileStore(repo.config.storage_root,create=True)
    script = '''
import sys
from app.knowledge import worker
from app.knowledge.config import KnowledgeSettings
import app.knowledge.config
config=KnowledgeSettings(_env_file=None,enabled=sys.argv[2]=='enabled',storage_root=sys.argv[1])
app.knowledge.config.load_settings=lambda:(config,None)
sys.exit(worker.main(['--test','--run-for','0.2']))
'''
    for enabled in ('enabled','disabled'):
        process = subprocess.run([sys.executable,'-c',script,str(repo.config.storage_root),enabled],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=45)
        assert process.returncode == 0, process.stderr
        assert 'worker_stopped' in process.stderr


def test_launcher_starts_and_stops_only_its_worker():
    root = Path(__file__).resolve().parents[2]
    script = root/'scripts/tests/knowledge-launcher.ps1'
    process = subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],
                            cwd=root,capture_output=True,text=True,timeout=30)
    assert process.returncode == 0, process.stderr
    assert '"passed":  true' in process.stdout


def test_optional_worker_exit_keeps_required_development_processes_alive():
    root = Path(__file__).resolve().parents[2]
    process = subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'scripts/tests/knowledge-optional.ps1')],
        cwd=root,capture_output=True,text=True,timeout=30)
    assert process.returncode==0,process.stderr
    assert '"passed":  true' in process.stdout
