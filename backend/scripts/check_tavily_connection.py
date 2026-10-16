"""Probe the official async tool and print only safe connection metadata."""
import asyncio
import argparse
import json
from pathlib import Path
import re
import sys
import os
from dotenv import dotenv_values
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from langchain_tavily import TavilySearch, TavilyExtract


async def main(extract_url=None):
    settings = Settings()
    tool = TavilyExtract(tavily_api_key=settings.tavily_api_key.get_secret_value(), format='markdown', include_usage=True, handle_tool_error=False) if extract_url else TavilySearch(tavily_api_key=settings.tavily_api_key.get_secret_value(), max_results=1, include_answer=False, include_raw_content=False, include_usage=True, handle_tool_error=False)
    wrapper = tool.apiwrapper if extract_url else tool.api_wrapper
    configured = settings.tavily_api_key.get_secret_value()
    file_value = dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('TAVILY_API_KEY')
    metadata = {'sdk_key_matches_config': wrapper.tavily_api_key.get_secret_value() == configured,
                'environment_variable_present': 'TAVILY_API_KEY' in os.environ,
                'config_matches_dotenv': file_value == configured,
                'key_has_outer_whitespace': configured != configured.strip(),
                'key_has_expected_prefix': configured.startswith('tvly-')}
    try:
        async with asyncio.timeout(20):
            result = await tool.ainvoke({'urls': [extract_url], 'extract_depth': 'basic'} if extract_url else {'query': 'Harness engineering coding agents', 'search_depth': 'basic'})
        if isinstance(result, dict) and 'error' not in result and result.get('results'):
            report = {'success': True, 'result_count': len(result.get('results', [])), 'usage': result.get('usage')}
        else:
            error = result.get('error') if isinstance(result, dict) else result
            status = re.search(r'\bError (\d{3})\b', str(error))
            report = {'success': False, 'error_type': type(error).__name__, 'http_status': int(status[1]) if status else None}
    except Exception as error:
        report = {'success': False, 'error_type': type(error).__name__}
    report = {'tool': 'tavily_extract' if extract_url else 'tavily_search', **report, **metadata}
    print(json.dumps(report), flush=True)
    path = Path(__file__).resolve().parents[2] / 'docs/quiz-grounding' / ('tavily-extract-smoke.json' if extract_url else 'tavily-search-smoke.json')
    path.write_text(json.dumps(report, indent=2), encoding='utf8')
    return 0 if report['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.extract)))
