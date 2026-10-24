"""Authenticated feature availability and remaining quota, without cloud requests."""
from fastapi import APIRouter,Request
from sqlalchemy.exc import SQLAlchemyError
from .config import load_settings
from .repository import ImageRepository

router=APIRouter(prefix='/api/v1/quiz/images')


@router.get('/capabilities')
def capabilities(request:Request):
    state=request.app.state
    injected=getattr(state,'image_config',None)
    config,error=(injected,None) if injected is not None else load_settings()
    reason=error or config.unavailable_reason()
    quota={'remaining':0,'daily_limit':config.daily_limit if config else 20}
    if config:
        try:quota=ImageRepository(state.accounts,config).quota(request.state.user_id)
        except SQLAlchemyError:reason=reason or 'IMAGE_MIGRATION_REQUIRED'
    return {'code':0,'message':'ok','data':{'enabled':bool(config and config.enabled),'available':reason is None,
        'reason_code':reason,**quota,'resolution':'512×512',
        'disclosure':'开启后，题目描述发送百炼生成辅助图片；配图通过公开图片链接展示。失败仍可文字学习。'}}
