"""Isolated browser harness: real MySQL; zero paid/cloud image requests."""
import uvicorn
from app.config import Settings
from app.main import create_app
from app.accounts.database import Database
from app.accounts.repository import Accounts
from app.question_images.service import QuestionImages
from tests.serve_accounts_e2e import ScenarioGateway
from tests.test_mysql_accounts import WeChatStub
from tests.test_question_images_transport import config, png
from tests.test_question_images_service import Provider, Storage, Planner


if __name__=='__main__':
    settings=Settings(database_testing=True,wechat_app_id='isolated-image-e2e',
        identity_hash_secret='isolated-image-e2e-secret-for-test-only',ai_minute_limit=1000,login_minute_limit=10000,tavily_api_key='')
    database=Database(settings)
    with database.engine.connect() as connection:
        from tests.knowledge_support import assert_database
        assert_database(settings,connection)
    database.migrate()
    accounts=Accounts(settings,database)
    app=create_app(settings,ScenarioGateway(),accounts=accounts,wechat=WeChatStub())
    app.state.image_config=config()
    app.state.images=QuestionImages(accounts,app.state.image_config,provider=Provider(),storage=Storage(),download=lambda u,c:png(),planner=Planner())
    uvicorn.run(app,host='127.0.0.1',port=18001,access_log=False)
