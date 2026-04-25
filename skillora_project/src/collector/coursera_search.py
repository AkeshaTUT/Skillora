"""
Coursera search helper.

Uses Coursera's internal search API (same endpoint the website uses) for
fast, structured JSON results. Falls back to HTML slug-extraction if the
API call fails.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from curl_cffi import requests as cfrequests

logger = logging.getLogger("collector.coursera")

COURSE_BASE = "https://www.coursera.org"

_SEARCH_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.coursera.org/",
    "Origin": "https://www.coursera.org",
}


def _slug_to_title(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-"))


def _api_search(query: str, limit: int) -> list[dict[str, Any]]:
    """Try Coursera's internal search endpoint (returns JSON)."""
    url = (
        f"{COURSE_BASE}/api/courses.v1"
        f"?q=search&query={query.replace(' ', '%20')}"
        f"&includes=instructorIds,partnerIds"
        f"&fields=name,slug,photoUrl,avgProductRating,courseStatus,productType"
        f"&limit={min(limit, 100)}&start=0"
        f"&language=en&index=prod_all_products_term_optimization"
    )
    try:
        resp = cfrequests.get(
            url,
            headers=_SEARCH_HEADERS,
            impersonate="chrome",
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        elements = data.get("elements") or []
        results: list[dict[str, Any]] = []
        for el in elements[:limit]:
            slug = el.get("slug") or ""
            name = el.get("name") or _slug_to_title(slug)
            rating = el.get("avgProductRating")
            results.append(
                {
                    "platform": "coursera",
                    "title": name,
                    "course_url": f"{COURSE_BASE}/learn/{slug}" if slug else "",
                    "description": "",
                    "rating": float(rating) if rating else None,
                    "reviews_count": 0,
                    "image_url": el.get("photoUrl"),
                    "level": None,
                    "is_paid": True,
                    "source": "live",
                }
            )
        return results
    except Exception as exc:
        logger.warning(f"Coursera API error: {exc}")
        return []


def _html_search(query: str, limit: int) -> list[dict[str, Any]]:
    """Fallback: scrape HTML and extract /learn/<slug> links."""
    url = f"{COURSE_BASE}/search?query={query.replace(' ', '%20')}"
    try:
        resp = cfrequests.get(url, impersonate="chrome", timeout=12)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    slugs = re.findall(r"/learn/([a-zA-Z0-9-]+)", resp.text)
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)
        results.append(
            {
                "platform": "coursera",
                "title": _slug_to_title(slug),
                "course_url": f"{COURSE_BASE}/learn/{slug}",
                "description": "",
                "rating": None,
                "reviews_count": 0,
                "level": None,
                "is_paid": True,
                "source": "live",
            }
        )
        if len(results) >= limit:
            break
    return results


def search_coursera(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    results = _api_search(q, limit)
    if not results:
        logger.info(f"Coursera API empty for '{q}', trying HTML fallback")
        results = _html_search(q, limit)

    logger.info(f"Coursera: '{q}' → {len(results)} results")
    return results
