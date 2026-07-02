# mass-laws-live MCP server

An MCP (Model Context Protocol) stdio server that queries **Massachusetts General Laws (MGL)**, session laws, and bills live from the official public [malegislature.gov REST API](https://malegislature.gov/api/swagger/index.html?url=/api/swagger/v1/swagger.json). No API key required. Read-only. Results are cached in memory for 24 hours; text over 12,000 characters is truncated with a notice.

## Tools

| Tool | Description |
|---|---|
| `list_parts` | The 5 MGL Parts (I-V) with names and chapter ranges |
| `get_part(part_code)` | Part name, chapter range, chapter codes |
| `get_chapter(chapter_code)` | Chapter name, part, repealed flag, section codes |
| `get_section(chapter_code, section_code)` | Full statute text. Fractional codes like `7D1/2` auto-convert to the API's `~` form |
| `search_chapter(chapter_code, query, limit)` | Client-side keyword search across all sections of a chapter (the API has no search endpoint). Slow on first call for large chapters, cached after |
| `get_session_law(year, chapter_number)` | Enacted session law text, years 1997-2026 |
| `get_bill(bill_number, general_court)` | Bill title, sponsor, and text (current General Court: 194) |

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/alfranli123/mass-laws-live-mcp.git
cd mass-laws-live-mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configure (Hermes example)

```yaml
mcp_servers:
  mass-laws-live:
    command: "/path/to/mass-laws-live-mcp/.venv/bin/python"
    args: ["/path/to/mass-laws-live-mcp/server.py"]
```

Any MCP client that supports stdio transport works the same way: run `server.py` with the venv's Python.

## Test

Two harnesses spawn the server over stdio and call every tool against the live API:

```bash
.venv/bin/python test_client.py   # happy-path: 8 cases
.venv/bin/python ext_test.py      # edge cases: 11 cases (errors, fractional codes, truncation, cache)
```

## Notes

- The malegislature.gov API has **no full-text search endpoint**; `search_chapter` fetches every section of one chapter concurrently and matches client-side.
- Not legal advice. Statute text comes from the state API as-is.

## License

MIT
