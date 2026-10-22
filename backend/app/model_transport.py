"""Opt-in transport ownership for synchronous workers running async model jobs."""
import asyncio
from contextvars import ContextVar
import httpx

_async_client = ContextVar('levelup_job_model_client',default=None)


def current_async_model_client():
    return _async_client.get()


def run_model_job(operation):
    async def execute():
        # LangChain's default async HTTP clients may be cached across instances.
        # A worker creates a new event loop for each job; its connections must be
        # closed before that loop ends, including cancellation and failed jobs.
        async with httpx.AsyncClient() as client:
            token=_async_client.set(client)
            try: return await operation()
            finally: _async_client.reset(token)
    return asyncio.run(execute())
