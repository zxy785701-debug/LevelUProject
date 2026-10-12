"""Explicit isolated H5 test server. Never imported by the normal app."""
import uvicorn
from app.config import Settings
from app.main import create_app
from app.accounts.database import Database
from app.accounts.repository import Accounts
from tests.test_mysql_accounts import WeChatStub
from tests.helpers import quiz_payload, REPORT

class ScenarioGateway:
    async def generate(self, schema, prompt, check=None):
        result = REPORT if schema.__name__ == 'ReportContent' else quiz_payload(5 if '出 5 道' in prompt else 3)
        parsed = schema.model_validate(result)
        if check: check(parsed)
        return parsed

if __name__ == '__main__':
    settings = Settings(database_testing=True, wechat_app_id='isolated-e2e', identity_hash_secret='isolated-e2e-secret-not-for-production', ai_minute_limit=1000, login_minute_limit=10000)
    database = Database(settings)
    database.migrate()
    app = create_app(settings, ScenarioGateway(), accounts=Accounts(settings, database), wechat=WeChatStub())
    uvicorn.run(app, host='127.0.0.1', port=8001, access_log=False)
