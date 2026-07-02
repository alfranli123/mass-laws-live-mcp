"""
MCP server for Massachusetts General Laws (MGL) — queries live from the
official malegislature.gov REST API.
"""

import asyncio
import time
from typing import Any

from mcp.server.fastmcp import FastMCP
import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE = "https://malegislature.gov/api"
CACHE_TTL = 86400  # seconds (24 h) — statutes rarely change
USER_AGENT = "mass-laws-live-mcp/0.1"
HTTP_TIMEOUT = 20.0
SEARCH_SEMAPHORE_LIMIT = 8
TEXT_TRUNCATE = 12000
SNIPPET_CHARS = 300

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "mass-laws-live",
    instructions=(
        "MCP server for querying Massachusetts General Laws (MGL) live from "
        "the official malegislature.gov REST API. All tools are read-only and "
        "require no authentication. Large text responses are truncated at "
        "12 000 characters."
    ),
)

# ---------------------------------------------------------------------------
# Lazy singleton HTTP client
# ---------------------------------------------------------------------------
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > CACHE_TTL:
        del _cache[key]
        return None
    return value


def _set_cache(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _api_get(path: str, cache_key: str | None = None) -> dict | list:
    """GET a JSON resource, using cache when a cache_key is provided."""
    if cache_key:
        cached = _cached(cache_key)
        if cached is not None:
            return cached

    client = get_client()
    resp = await client.get(path)
    if resp.status_code == 404:
        return {"error": f"HTTP 404 — resource not found: {path}"}
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code} — {resp.text[:200]}"}
    data = resp.json()

    if cache_key:
        _set_cache(cache_key, data)
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str | None, limit: int = TEXT_TRUNCATE) -> str:
    """Truncate *text* at *limit* chars with a notice."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return (
        text[:limit]
        + f"\n\n[truncated at {limit} chars — {len(text)} total]"
    )


def _strip_html(html: str) -> str:
    """Crude HTML-to-plain-text conversion for session law texts."""
    import re as _re
    # Remove all HTML tags
    text = _re.sub(r"<[^>]+>", "", html)
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    # Collapse whitespace
    text = _re.sub(r"[ \t]+", " ", text)
    text = _re.sub(r"\n\s*\n", "\n\n", text).strip()
    return text


def _find_snippet(text: str, query: str, width: int = SNIPPET_CHARS) -> str:
    """Return a ~*width*-char snippet around the first case-insensitive match
    of *query* in *text*."""
    lower = text.lower()
    q = query.lower()
    pos = lower.find(q)
    if pos == -1:
        return text[:width]
    start = max(0, pos - width // 2)
    end = min(len(text), pos + len(q) + width // 2)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_parts() -> list[dict[str, Any]]:
    """List the 5 parts of the Massachusetts General Laws with their names.

    Fetches /Parts then enriches each entry with the part Name.
    """
    parts_raw = await _api_get("/Parts", cache_key="parts")
    if isinstance(parts_raw, dict) and "error" in parts_raw:
        return [parts_raw]

    results: list[dict[str, Any]] = []
    for p in parts_raw:
        code = p["Code"]
        detail = await _api_get(f"/Parts/{code}", cache_key=f"part_{code}")
        if isinstance(detail, dict) and "error" not in detail:
            results.append({
                "code": code,
                "name": detail.get("Name", ""),
                "first_chapter": detail.get("FirstChapter"),
                "last_chapter": detail.get("LastChapter"),
            })
        else:
            results.append({"code": code, "name": "", "error": str(detail)})
    return results


@mcp.tool()
async def get_part(part_code: str) -> dict[str, Any]:
    """Get details for a single MGL part by its letter code (e.g. 'I', 'II').

    Returns the part name, chapter range, and list of chapter codes.
    """
    detail = await _api_get(f"/Parts/{part_code}", cache_key=f"part_{part_code}")
    if isinstance(detail, dict) and "error" in detail:
        return detail
    chapters = [
        c["Code"] for c in detail.get("Chapters", [])
    ]
    return {
        "code": detail.get("Code"),
        "name": detail.get("Name"),
        "first_chapter": detail.get("FirstChapter"),
        "last_chapter": detail.get("LastChapter"),
        "chapter_codes": chapters,
    }


@mcp.tool()
async def get_chapter(chapter_code: str) -> dict[str, Any]:
    """Get details for a single chapter by its numeric code (e.g. '265').

    Returns the chapter name, associated part, repealed flag, and section codes.
    """
    detail = await _api_get(
        f"/Chapters/{chapter_code}", cache_key=f"chapter_{chapter_code}"
    )
    if isinstance(detail, dict) and "error" in detail:
        return detail
    sections = [
        s["Code"] for s in detail.get("Sections", [])
    ]
    part_info = detail.get("Part")
    return {
        "code": detail.get("Code"),
        "name": detail.get("Name"),
        "is_repealed": detail.get("IsRepealed", False),
        "part_code": part_info.get("Code") if part_info else None,
        "part_name": part_info.get("Name") if part_info else None,
        "section_codes": sections,
    }


@mcp.tool()
async def get_section(chapter_code: str, section_code: str) -> dict[str, Any]:
    """Get the full text of a section by chapter and section code.

    Fractional section codes using '/' (e.g. '7D1/2') are automatically
    converted to the API's '~' separator.
    """
    # Convert "/" to "~" for fractional section codes
    safe_section = section_code.replace("/", "~")
    detail = await _api_get(
        f"/Chapters/{chapter_code}/Sections/{safe_section}",
        cache_key=f"section_{chapter_code}_{safe_section}",
    )
    if isinstance(detail, dict) and "error" in detail:
        return detail
    text = detail.get("Text", "")
    return {
        "code": detail.get("Code"),
        "name": detail.get("Name"),
        "is_repealed": detail.get("IsRepealed", False),
        "text": _truncate(text),
    }


@mcp.tool()
async def search_chapter(
    chapter_code: str, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Client-side keyword search within a single chapter.

    Fetches the chapter's section list, then fetches ALL sections
    concurrently (cached).  Large chapters (e.g. Ch 90 with 30+ sections)
    take a few seconds on first call; subsequent calls are fast thanks to
    caching.

    Returns up to *limit* hits with section code, name, a ~300-char
    snippet around the first match, and match count.
    """
    chapter = await _api_get(
        f"/Chapters/{chapter_code}", cache_key=f"chapter_{chapter_code}"
    )
    if isinstance(chapter, dict) and "error" in chapter:
        return [chapter]

    section_infos = chapter.get("Sections", [])
    sem = asyncio.Semaphore(SEARCH_SEMAPHORE_LIMIT)

    async def _fetch_section(sinfo: dict) -> dict | None:
        code = sinfo["Code"]
        safe_code = code.replace("/", "~")
        cache_key = f"section_{chapter_code}_{safe_code}"
        cached = _cached(cache_key)
        if cached is not None:
            data = cached
        else:
            async with sem:
                data = await _api_get(
                    f"/Chapters/{chapter_code}/Sections/{safe_code}",
                    cache_key=cache_key,
                )
        return data

    sections_data = await asyncio.gather(
        *[_fetch_section(s) for s in section_infos], return_exceptions=True
    )

    hits: list[dict[str, Any]] = []
    q_lower = query.lower()
    for data in sections_data:
        if not isinstance(data, dict) or "error" in data:
            continue
        name = data.get("Name", "")
        text = data.get("Text", "")
        code = data.get("Code", "")
        combined = (name + " " + text).lower()
        count = combined.count(q_lower)
        if count > 0:
            snippet = _find_snippet(text if q_lower in text.lower() else name, query)
            hits.append({
                "section_code": code,
                "name": name,
                "snippet": snippet,
                "match_count": count,
            })
            if len(hits) >= limit:
                break

    return hits


@mcp.tool()
async def get_session_law(year: int, chapter_number: int) -> dict[str, Any]:
    """Get the text of a session law by year and chapter number.

    Example: year=2023, chapter_number=1 for the first session law of 2023.
    """
    detail = await _api_get(
        f"/SessionLaws/{year}/{chapter_number}",
        cache_key=f"sessionlaw_{year}_{chapter_number}",
    )
    if isinstance(detail, dict) and "error" in detail:
        return detail
    # Session laws may have ChapterText (HTML) or Text or DocumentText
    text = detail.get("Text") or detail.get("DocumentText") or detail.get("ChapterText", "")
    if detail.get("ChapterText"):
        text = _strip_html(text)
    return {
        "year": year,
        "chapter_number": chapter_number,
        "name": detail.get("Title", detail.get("Name", "")),
        "text": _truncate(text),
    }


@mcp.tool()
async def get_bill(
    bill_number: str, general_court: int = 194
) -> dict[str, Any]:
    """Get the full text and metadata of a Massachusetts bill.

    Tries /GeneralCourts/{general_court}/Documents/{bill_number} first,
    falls back to /Documents/{bill_number}.  Example: bill_number='H1234'.
    """
    # Primary path with General Court
    path = f"/GeneralCourts/{general_court}/Documents/{bill_number}"
    detail = await _api_get(path, cache_key=f"bill_{general_court}_{bill_number}")

    if isinstance(detail, dict) and "error" in detail:
        # Fallback to /Documents/{bill_number}
        path2 = f"/Documents/{bill_number}"
        detail = await _api_get(
            path2, cache_key=f"bill_nogc_{bill_number}"
        )

    if isinstance(detail, dict) and "error" in detail:
        return detail

    text = detail.get("DocumentText") or detail.get("Text") or ""
    return {
        "bill_number": bill_number,
        "title": detail.get("Title", detail.get("Name", "")),
        "sponsor": detail.get("Sponsor", detail.get("PrimarySponsor", {}).get("Name", "")),
        "general_court": detail.get("GeneralCourtNumber", general_court),
        "document_text": _truncate(text),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
