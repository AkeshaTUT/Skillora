"""
Udemy fast search via search results page.

Udemy embeds course data as JSON in the __NEXT_DATA__ script tag on their
search results page — the same technique that already works for topic pages.
This is ~3-5x faster than scraping individual topic pages.

Response time: ~2-5 seconds (vs 10-60s for multi-topic scraping).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from curl_cffi import requests as cfrequests

logger = logging.getLogger("collector.udemy_api")

_BASE = "https://www.udemy.com"

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.udemy.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


def _extract_next_data(html: str) -> dict | None:
    """Extract JSON from __NEXT_DATA__ script tag."""
    m = re.search(
        r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _extract_window_initial_state(html: str) -> dict | None:
    """Extract UD.serverSideProps or window.__initialState__ JSON."""
    for pattern in [
        r'window\.__initialState__\s*=\s*(\{.*?\});\s*</script>',
        r'"courseList"\s*:\s*(\[.*?\])',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    return None


def _normalise_search_result(item: dict) -> dict:
    """Convert a raw Udemy search result item to our standard format."""
    instructors = item.get("visible_instructors") or []
    instructor = None
    if instructors:
        first = instructors[0]
        instructor = (
            first.get("display_name")
            if isinstance(first, dict)
            else None
        )

    url = item.get("url") or item.get("learn_url") or ""
    if url and not url.startswith("http"):
        url = f"{_BASE}{url}"

    return {
        "title": item.get("title") or "",
        "description": item.get("headline") or "",
        "course_url": url,
        "platform": "udemy",
        "rating": item.get("avg_rating_recent") or item.get("avg_rating"),
        "reviews_count": item.get("num_reviews") or 0,
        "subscribers_count": item.get("num_subscribers") or 0,
        "instructor": instructor,
        "image_url": item.get("image_240x135") or item.get("image_100x100"),
        "level": item.get("instructional_level_simple"),
        "is_paid": item.get("is_paid"),
        "content_length": item.get("content_info_short") or item.get("content_info"),
        "source": "live",
    }


def _courses_from_next_data(data: dict) -> list[dict]:
    """Walk __NEXT_DATA__ structure and collect course items."""
    courses: list[dict] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, list):
            for el in obj:
                _walk(el)
        elif isinstance(obj, dict):
            # Looks like a course item
            if obj.get("title") and obj.get("url") and (
                obj.get("avg_rating") is not None
                or obj.get("avg_rating_recent") is not None
                or obj.get("num_reviews") is not None
            ):
                courses.append(obj)
                return
            for v in obj.values():
                _walk(v)

    _walk(data)
    return courses


def search_udemy_api(query: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """
    Search Udemy via the search results page's embedded JSON.

    Returns a list of normalised course dicts, or [] on failure.
    """
    if not query or not query.strip():
        return []

    q_enc = query.strip().replace(" ", "%20")
    url = f"{_BASE}/courses/search/?q={q_enc}&sort=relevance&lang=en"

    try:
        resp = cfrequests.get(
            url,
            headers=_HEADERS,
            impersonate="chrome",
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(
                f"Udemy search page returned {resp.status_code} for '{query}'"
            )
            return []

        html = resp.text

    except Exception as exc:
        logger.warning(f"Udemy search page error for '{query}': {exc}")
        return []

    # Try __NEXT_DATA__ first
    next_data = _extract_next_data(html)
    raw_courses: list[dict] = []

    if next_data:
        raw_courses = _courses_from_next_data(next_data)

    # Fallback: look for JSON arrays in script tags
    if not raw_courses:
        for block in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
            if '"avg_rating"' not in block and '"num_reviews"' not in block:
                continue
            if len(block) < 500:
                continue
            # Find array start
            m = re.search(r'(\[{"id":\d+.*?\}])', block, re.DOTALL)
            if m:
                try:
                    raw_courses = json.loads(m.group(1))
                    break
                except json.JSONDecodeError:
                    continue

    if not raw_courses:
        logger.warning(
            f"Udemy: no course JSON found in search page for '{query}'"
        )
        return []

    results = [_normalise_search_result(c) for c in raw_courses[:limit]]
    logger.info(f"Udemy search page: '{query}' → {len(results)} results")
    return results
