import re
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from ..content import check_content
from ..errors import AppError
from ..materials.api import operation_key
from ..materials.parsers import validate_url
from .models import PrepareRequest, Preparation
from .snapshots import GroundingModel
from .preparation import process_preparation


router = APIRouter(prefix='/api/v1/quiz/preparations')


class MaterialEntryHint(GroundingModel):
    kind: Literal['material_entry'] = 'material_entry'
    url: str
    learning_instruction: str | None = None
    message: str = '请读取指定网页并确认材料范围'


class PreparationEnvelope(GroundingModel):
    code: Literal[0] = 0
    message: str = 'ok'
    data: Preparation | MaterialEntryHint


def split_url_input(text):
    matches = list(re.finditer(r'https?://[^\s<>"\u3000]+', text, flags=re.IGNORECASE))
    if not matches:
        return None
    if len(matches) != 1:
        raise AppError('MULTIPLE_URLS_NOT_SUPPORTED', '请每次提交一个网页网址', 422)
    match = matches[0]
    url = match.group().rstrip('，。；！？）)]}')
    instruction = (text[:match.start()] + ' ' + text[match.end():]).strip(' \n\t，。；：:')
    return url, instruction or None


@router.post('', response_model=PreparationEnvelope)
async def create(body: PrepareRequest, request: Request, background: BackgroundTasks):
    check_content(body.text)
    page = split_url_input(body.text)
    if page:
        url, instruction = page
        url = await run_in_threadpool(validate_url, url)
        return PreparationEnvelope(data=MaterialEntryHint(url=url, learning_instruction=instruction))
    state, uid = request.app.state, request.state.user_id
    result, fresh = await run_in_threadpool(state.grounding.create, uid, operation_key(request), body.text)
    if fresh:
        background.add_task(process_preparation, state, uid, result['id'])
    return PreparationEnvelope(data=Preparation.model_validate(result))


@router.get('/{pid}', response_model=PreparationEnvelope)
def get(pid: str, request: Request):
    return PreparationEnvelope(data=Preparation.model_validate(request.app.state.grounding.get(request.state.user_id, pid)))


@router.post('/{pid}/cancel', response_model=PreparationEnvelope)
def cancel(pid: str, request: Request):
    return PreparationEnvelope(data=Preparation.model_validate(request.app.state.grounding.cancel(request.state.user_id, pid)))
