"""Inspect installed contracts; --live also performs two billed model requests."""
import argparse
import asyncio
import inspect
import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from langchain.agents import create_agent
from langchain_tavily import TavilyExtract, TavilySearch
from app.config import Settings
from app.errors import AppError
from app.quiz_grounding.capability import probe_tool_calling


async def main(live=False):
    settings = Settings()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "versions": {name: version(name) for name in ("langchain-tavily", "langchain", "langchain-core", "langchain-openai", "langgraph", "aiohttp")},
        "create_agent_available": callable(create_agent),
        "tools": {},
        "model": {"status": "not_run"},
    }
    for cls in (TavilySearch, TavilyExtract):
        tool = cls(tavily_api_key="contract-only-placeholder")
        report["tools"][tool.name] = {
            "native_async": inspect.iscoroutinefunction(cls._arun),
            "constructor_fields": sorted(cls.model_fields),
            "invocation_fields": sorted(tool.args_schema.model_fields),
        }
    failed = False
    if live:
        try:
            report["model"] = await probe_tool_calling(settings)
        except AppError as error:
            failed = True
            report["model"] = {"status": "failed", "code": error.code, "model": settings.deepseek_model}
    filename = "dependencies-live.json" if live else "dependencies.json"
    destination = Path(__file__).resolve().parents[1] / "test-results/quiz-grounding" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args().live)))
