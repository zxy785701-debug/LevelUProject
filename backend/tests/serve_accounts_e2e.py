"""Explicit isolated H5 test server. Never imported by the normal app."""
import uvicorn
from app.config import Settings
from app.main import create_app
from app.accounts.database import Database
from app.accounts.repository import Accounts
from tests.test_mysql_accounts import WeChatStub
from tests.helpers import quiz_payload, REPORT, grounding_payload

class ScenarioGateway:
    async def generate(self, schema, prompt, check=None):
        grounding = grounding_payload(schema, prompt)
        if grounding is not None:
            result = schema.model_validate(grounding)
            if check: check(result)
            return result
        if schema.__name__ in ('MaterialSummary', 'PeriodNarrative'):
            from tests.test_multisource_accounts import FeatureGateway
            return await FeatureGateway().generate(schema, prompt, check)
        result = REPORT if schema.__name__ == 'ReportContent' else quiz_payload(5 if '出 5 道' in prompt else 3)
        if schema.__name__ == 'QuizContent' and '分段：' in prompt:
            for q in result['questions']: q['source_ids'] = ['s1']
        parsed = schema.model_validate(result)
        if check: check(parsed)
        return parsed

if __name__ == '__main__':
    settings = Settings(database_testing=True, wechat_app_id='isolated-e2e', identity_hash_secret='isolated-e2e-secret-not-for-production', ai_minute_limit=1000, login_minute_limit=10000, tavily_api_key='')
    database = Database(settings)
    database.migrate()
    app = create_app(settings, ScenarioGateway(), accounts=Accounts(settings, database), wechat=WeChatStub())
    import os
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('LEVELUP_E2E_PORT', '8001')), access_log=False)
