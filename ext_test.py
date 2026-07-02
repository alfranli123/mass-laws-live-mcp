"""Extended test harness for mass-laws-live MCP server — edge cases."""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

import os

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


PASS = 0
FAIL = 0


def test(name, data, expected_ok=True, extra_checks=None):
    global PASS, FAIL
    status = "PASS" if ok(data) == expected_ok else "FAIL"
    if extra_checks:
        try:
            extra_checks(data)
            # Extra checks passed — override to PASS
            status = "PASS"
        except AssertionError as e:
            status = "FAIL"
            data = {"assertion_error": str(e), "original": data}
    if status == "PASS":
        PASS += 1
    else:
        FAIL += 1
    print(f"{status} {name} -> {json.dumps(data, default=str)[:300]}")


def check_truncated(data):
    """Verify truncation notice is present for a large section."""
    assert "error" not in data, f"unexpected error: {data}"
    text = data.get("text", "")
    assert "[truncated at 12000 chars" in text, f"missing truncation notice in text ({len(text)} chars)"
    # Extract the total length from the notice
    import re
    m = re.search(r"\[truncated at 12000 chars — (\d+) total\]", text)
    assert m, f"could not parse total length from truncation notice"
    total = int(m.group(1))
    assert total > 12000, f"total length {total} should be > 12000"


def check_no_none_type(data):
    """Verify we never got a NoneType-related crash result."""
    assert "error" not in data or "NoneType" not in json.dumps(data), f"NoneType in result: {data}"


def check_empty_list(data):
    """Verify result is an empty list."""
    assert isinstance(data, list), f"expected list, got {type(data)}"
    assert len(data) == 0, f"expected empty list, got {len(data)} items"


async def main():
    global PASS, FAIL
    params = StdioServerParameters(command=f"{BASE}/.venv/bin/python", args=[f"{BASE}/server.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ── Edge case: get_bill H5470 (NoneType regression) ─────────────
            r = await session.call_tool("get_bill", {"bill_number": "H5470"})
            data = extract(r)
            test("get_bill H5470 (NoneType regression)", data,
                 extra_checks=lambda d: (
                     check_no_none_type(d),
                     assert_("error" not in d, f"got error: {d.get('error','')}"),
                     assert_(isinstance(d.get("document_text", None), str) or d.get("document_text") == "",
                             f"document_text should be empty string, got: {repr(d.get('document_text'))}"),
                 ))

            # ── Edge case: fractional section code with "/" ────────────────
            r = await session.call_tool("get_section", {"chapter_code": "90", "section_code": "7D1/2"})
            data = extract(r)
            test("get_section 90/7D1/2 (fractional slash → ~)", data)

            # ── Edge case: nonexistent section ─────────────────────────────
            r = await session.call_tool("get_section", {"chapter_code": "265", "section_code": "9999"})
            data = extract(r)
            test("get_section 265/9999 (nonexistent) → error dict", data, expected_ok=False)

            # ── Edge case: nonexistent chapter ─────────────────────────────
            r = await session.call_tool("get_chapter", {"chapter_code": "9999"})
            data = extract(r)
            test("get_chapter 9999 (nonexistent) → error dict", data, expected_ok=False)

            # ── Edge case: invalid part code ───────────────────────────────
            r = await session.call_tool("get_part", {"part_code": "XX"})
            data = extract(r)
            test("get_part XX (invalid) → error dict", data, expected_ok=False)

            # ── Edge case: unsupported year session law ────────────────────
            r = await session.call_tool("get_session_law", {"year": 1980, "chapter_number": 1})
            data = extract(r)
            test("get_session_law(1980, 1) (unsupported year) → error", data, expected_ok=False)

            # ── Edge case: garbage bill number ─────────────────────────────
            r = await session.call_tool("get_bill", {"bill_number": "ZZZ999"})
            data = extract(r)
            test("get_bill ZZZ999 (garbage) → error dict", data, expected_ok=False)

            # ── Edge case: search_chapter with no-matching query ───────────
            r = await session.call_tool("search_chapter", {"chapter_code": "265", "query": "zzzqqqxxx"})
            data = extract(r)
            test("search_chapter 265 'zzzqqqxxx' (no matches) → empty list", data,
                 extra_checks=check_empty_list)

            # ── Edge case: truncation in large section 90/24 ──────────────
            r = await session.call_tool("get_section", {"chapter_code": "90", "section_code": "24"})
            data = extract(r)
            test("get_section 90/24 (truncation check)", data,
                 extra_checks=check_truncated)

            # ── Edge case: caching — call get_chapter 265 twice ───────────
            r1 = await session.call_tool("get_chapter", {"chapter_code": "265"})
            d1 = extract(r1)
            r2 = await session.call_tool("get_chapter", {"chapter_code": "265"})
            d2 = extract(r2)
            test("get_chapter 265 (first call)", d1)
            test("get_chapter 265 (second call, cached)", d2,
                 extra_checks=lambda d: (
                     assert_("error" not in d, f"second call failed: {d.get('error','')}"),
                     assert_(d.get("code") == "265", f"wrong code on second call"),
                 ))

    print(f"\n=== Extended edge-case results: {PASS} PASS / {FAIL} FAIL / {PASS+FAIL} total ===")
    sys.exit(0 if FAIL == 0 else 1)


def assert_(cond, msg):
    if not cond:
        raise AssertionError(msg)


if __name__ == "__main__":
    asyncio.run(main())
