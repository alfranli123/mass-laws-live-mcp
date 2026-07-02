"""Test harness for mass-laws-live MCP server. Spawns server via stdio, calls every tool."""
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

BASE = os.path.dirname(os.path.abspath(__file__))


def extract(result) -> object:
    items = []
    for c in result.content:
        if hasattr(c, "text"):
            try:
                items.append(json.loads(c.text))
            except Exception:
                items.append(c.text)
    return items[0] if len(items) == 1 else items


def ok(data) -> bool:
    if isinstance(data, dict):
        return "error" not in data
    if isinstance(data, list):
        return len(data) > 0 and not (isinstance(data[0], dict) and "error" in data[0])
    return bool(data)


async def main() -> None:
    params = StdioServerParameters(command=f"{BASE}/.venv/bin/python", args=[f"{BASE}/server.py"])
    tests = [
        ("list_parts", {}),
        ("get_part", {"part_code": "I"}),
        ("get_chapter", {"chapter_code": "265"}),
        ("get_section", {"chapter_code": "265", "section_code": "1"}),
        ("get_section", {"chapter_code": "90", "section_code": "24"}),
        ("search_chapter", {"chapter_code": "265", "query": "murder"}),
        ("get_session_law", {"year": 2023, "chapter_number": 1}),
        ("get_bill", {"bill_number": "H1234"}),
    ]
    passed = failed = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for name, args in tests:
                try:
                    r = await session.call_tool(name, args)
                    data = extract(r)
                    if ok(data):
                        passed += 1
                        print(f"PASS {name}({args}) -> {json.dumps(data)[:160]}")
                    else:
                        failed += 1
                        print(f"FAIL {name}({args}) -> {json.dumps(data)[:300]}")
                except Exception as e:
                    failed += 1
                    print(f"FAIL {name}({args}) -> exception: {e}")
    print(f"\nResults: {passed} PASS / {failed} FAIL / {passed+failed} total")


if __name__ == "__main__":
    asyncio.run(main())
