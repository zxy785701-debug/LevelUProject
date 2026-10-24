"""Read-only, sanitized evidence for explicit cloud acceptance (test DB only)."""
import argparse
import json
from pathlib import Path
from sqlalchemy import select
from app.accounts.database import Database,Operation,Attempt
from app.config import Settings
from app.question_images.config import ImageSettings
from app.question_images.database import ImageCall,ImagePlan
from tests.knowledge_support import assert_database


def audit(output,database_name=None,user_id=None):
    extra={'mysql_test_database':database_name} if database_name else {}
    settings=Settings(database_testing=True,**extra)
    database=Database(settings)
    with database.engine.connect() as connection:assert_database(settings,connection)
    report={'users':[],'topic_failure':None}
    with database.session() as session:
        query=select(ImageCall).where(ImageCall.image_url.startswith(ImageSettings().public_base_url))
        if user_id:query=query.where(ImageCall.user_id==user_id)
        calls=list(session.scalars(query))
        for uid in sorted({call.user_id for call in calls}):
            own=list(session.scalars(select(ImageCall).where(ImageCall.user_id==uid)))
            plans=list(session.scalars(select(ImagePlan).where(ImagePlan.user_id==uid)))
            operations=list(session.scalars(select(Operation).where(Operation.user_id==uid)))
            attempts=list(session.scalars(select(Attempt).where(Attempt.user_id==uid)))
            report['users'].append({'user_id':uid,
                'images':[{'question_id':c.question_id,'status':c.status,'object_key':c.object_key,'image_url':c.image_url} for c in own],
                'plans':[{'status':p.status,'scenes':p.scenes} for p in plans],
                'operations':[{'kind':o.kind,'status':o.status,'model_calls':o.model_calls,'error_code':o.error_code} for o in operations],
                'attempts':[{'id':a.id,'mode':a.mode,'completed':a.completed_at is not None,
                    'image_urls':[q.get('image_url') for q in a.quiz['questions']]} for a in attempts]})
        failed=session.scalar(select(Operation).where(Operation.id=='7dbad105-2a79-4b71-8380-3a1f11d87348'))
        if failed:
            report['topic_failure']={'operation_id':failed.id,'status':failed.status,
                'error_code':failed.error_code,'model_calls':failed.model_calls,
                'image_calls':len(list(session.scalars(select(ImageCall).where(ImageCall.user_id==failed.user_id))))}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'real_users':len(report['users']),'successful_images':len(calls),'topic_failure':report['topic_failure']}))
    database.engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--database')
    parser.add_argument('--user-id')
    args=parser.parse_args()
    audit(args.output,args.database,args.user_id)
