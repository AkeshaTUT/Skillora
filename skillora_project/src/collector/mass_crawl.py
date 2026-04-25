"""
Mass-crawl ALL courses from Udemy / Coursera sitemaps.

Features
--------
* Parallel fetching via ThreadPoolExecutor (configurable workers).
* Resume support — stores progress in a JSON checkpoint file.
* Incremental CSV append + DB batch-save every N courses.
* Adaptive delay — slows down on errors, speeds up on success.
* tqdm progress bar with ETA.

Usage
-----
::
    # Udemy — test run (1 sitemap page, max 20 courses)
    python -m src.collector.mass_crawl --platform udemy --sitemap-pages 1 --max-courses 20

    # Udemy — FULL crawl (all ~250K courses)
    python -m src.collector.mass_crawl --platform udemy --workers 5

    # Coursera — FULL crawl
    python -m src.collector.mass_crawl --platform coursera --workers 5

    # Resume interrupted crawl
    python -m src.collector.mass_crawl --platform udemy --resume
"""

from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm

from curl_cffi import requests as cfrequests

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.config import DATA_DIR
from src.database import SessionLocal, init_db
from src.models import RawCourse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("mass_crawl")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 "
    "Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

PROXY = os.getenv("SCRAPER_PROXY", "")

CHECKPOINT_DIR = DATA_DIR / "checkpoints"
CHECKPOINT_DIR.mkdir(exist_ok=True)

CSV_COLUMNS = [
    "id", "title", "url", "headline", "instructor", "rating",
    "num_reviews", "num_subscribers", "num_lectures", "content_length",
    "level", "is_paid", "last_update", "published_time", "image", "topic",
    "platform",
]

BATCH_SIZE = 50  # save to DB every N courses


# ===================================================================
# HTTP helpers
# ===================================================================

def _build_session() -> cfrequests.Session:
    proxies = {}
    if PROXY:
        proxies = {"http": PROXY, "https": PROXY}
    return cfrequests.Session(impersonate="chrome", proxies=proxies or None)


def _fetch(session: cfrequests.Session, url: str, retries: int = 3) -> str | None:
    """GET with retries + rotating UA. Returns HTML or None."""
    for attempt in range(1, retries + 1):
        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = session.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 403, 503):
                wait = 2 ** attempt + random.uniform(0, 2)
                logger.debug(f"  {resp.status_code} on {url}, wait {wait:.1f}s")
                time.sleep(wait)
                continue
            logger.debug(f"  Status {resp.status_code} on {url}")
            return None
        except Exception as exc:
            if attempt < retries:
                time.sleep(2 * attempt)
            else:
                logger.debug(f"  Error fetching {url}: {exc}")
    return None


# ===================================================================
# Sitemap URL collection
# ===================================================================

def collect_udemy_urls(
    session: cfrequests.Session,
    *,
    sitemap_pages: int = 0,
    max_courses: int = 0,
) -> list[str]:
    """Fetch all /course/ URLs from Udemy sitemaps."""
    index_html = _fetch(session, "https://www.udemy.com/sitemap.xml")
    if not index_html:
        logger.error("Cannot fetch Udemy sitemap index")
        return []

    all_locs = re.findall(r"<loc>(.*?)</loc>", index_html)
    course_sitemaps = [u for u in all_locs if "/sitemap/courses.xml" in u]
    if not course_sitemaps:
        logger.error("No course sitemap entries found")
        return []

    if sitemap_pages > 0:
        course_sitemaps = course_sitemaps[:sitemap_pages]

    logger.info(f"Found {len(course_sitemaps)} course sitemap pages")

    urls: list[str] = []
    seen: set[str] = set()

    for i, sm_url in enumerate(course_sitemaps, 1):
        logger.info(f"  [{i}/{len(course_sitemaps)}] {sm_url}")
        sm_html = _fetch(session, sm_url)
        if not sm_html:
            continue
        for loc in re.findall(r"<loc>(.*?)</loc>", sm_html):
            if "/course/" not in loc:
                continue
            if loc not in seen:
                seen.add(loc)
                urls.append(loc)
                if 0 < max_courses <= len(urls):
                    break
        if 0 < max_courses <= len(urls):
            break
        time.sleep(random.uniform(0.3, 0.8))

    logger.info(f"Udemy: collected {len(urls)} course URLs")
    return urls


def collect_coursera_urls(
    session: cfrequests.Session,
    *,
    max_courses: int = 0,
) -> list[str]:
    """Fetch all /learn/ URLs from Coursera sitemaps."""
    index_html = _fetch(session, "https://www.coursera.org/sitemap.xml")
    if not index_html:
        logger.error("Cannot fetch Coursera sitemap index")
        return []

    all_locs = re.findall(r"<loc>(.*?)</loc>", index_html)
    # Coursera has sitemap files like sitemap-courses-0.xml etc.
    course_sitemaps = [u for u in all_locs if "course" in u.lower() or "learn" in u.lower()]
    if not course_sitemaps:
        # fallback: try all sitemaps and filter /learn/ URLs
        course_sitemaps = all_locs

    logger.info(f"Coursera: {len(course_sitemaps)} sitemap pages to check")

    urls: list[str] = []
    seen: set[str] = set()

    for i, sm_url in enumerate(course_sitemaps, 1):
        if i % 10 == 0:
            logger.info(f"  [{i}/{len(course_sitemaps)}] checking...")
        sm_html = _fetch(session, sm_url)
        if not sm_html:
            continue
        for loc in re.findall(r"<loc>(.*?)</loc>", sm_html):
            if "/learn/" not in loc:
                continue
            if loc not in seen:
                seen.add(loc)
                urls.append(loc)
                if 0 < max_courses <= len(urls):
                    break
        if 0 < max_courses <= len(urls):
            break
        time.sleep(random.uniform(0.2, 0.5))

    logger.info(f"Coursera: collected {len(urls)} course URLs")
    return urls


# ===================================================================
# Page parsers
# ===================================================================

def parse_udemy_page(page_html: str, fallback_url: str) -> dict[str, Any] | None:
    """Extract course metadata from Udemy course page (JSON-LD + __NEXT_DATA__)."""
    # Try JSON-LD first
    result = _parse_ld_json(page_html, fallback_url, "udemy")
    if result:
        return result

    # Fallback: __NEXT_DATA__
    m = re.search(
        r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        page_html, re.DOTALL,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            pp = data.get("props", {}).get("pageProps", {})
            course = pp.get("course") or pp.get("serverSideProps", {}).get("course", {})
            if course and course.get("title"):
                instructors = course.get("visible_instructors", [])
                instructor = instructors[0].get("display_name") if instructors else None
                return {
                    "id": course.get("id"),
                    "title": course.get("title"),
                    "url": fallback_url,
                    "headline": course.get("headline") or course.get("description", ""),
                    "instructor": instructor,
                    "rating": course.get("avg_rating_recent") or course.get("avg_rating"),
                    "num_reviews": course.get("num_reviews"),
                    "num_subscribers": course.get("num_subscribers"),
                    "num_lectures": course.get("num_published_lectures"),
                    "content_length": course.get("content_info_short"),
                    "level": course.get("instructional_level_simple"),
                    "is_paid": course.get("is_paid"),
                    "last_update": course.get("last_update_date"),
                    "published_time": course.get("published_time"),
                    "image": course.get("image_240x135") or course.get("image_480x270"),
                    "topic": "all-catalog",
                    "platform": "udemy",
                }
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Fallback: meta tags
    title_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', page_html)
    desc_m = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', page_html)
    img_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', page_html)
    if title_m:
        return {
            "id": None,
            "title": html_mod.unescape(title_m.group(1)),
            "url": fallback_url,
            "headline": html_mod.unescape(desc_m.group(1)) if desc_m else "",
            "instructor": None,
            "rating": None, "num_reviews": None, "num_subscribers": None,
            "num_lectures": None, "content_length": None, "level": None,
            "is_paid": True, "last_update": None, "published_time": None,
            "image": img_m.group(1) if img_m else None,
            "topic": "all-catalog", "platform": "udemy",
        }
    return None


def parse_coursera_page(page_html: str, fallback_url: str) -> dict[str, Any] | None:
    """Extract course metadata from Coursera course page."""
    # 1. Try JSON-LD
    result = _parse_ld_json(page_html, fallback_url, "coursera")
    if result:
        return result

    # 2. Try window.App JSON (Coursera embeds course data here)
    app_m = re.search(r'window\.App\s*=\s*(\{.*?\})\s*;?\s*</script>', page_html, re.DOTALL)
    if app_m:
        try:
            app_data = json.loads(app_m.group(1))
            stores = app_data.get("context", {}).get("dispatcher", {}).get("stores", {})
            # Look for course data in various store locations
            for store_name, store_data in stores.items():
                if not isinstance(store_data, dict):
                    continue
                # CourseStore or similar
                for key, val in store_data.items():
                    if isinstance(val, dict) and val.get("name") and val.get("slug"):
                        agg = val.get("courseRating", {}) or {}
                        partners = val.get("partners", [])
                        instructor = partners[0].get("name") if partners else None
                        return {
                            "id": val.get("id"),
                            "title": val.get("name", ""),
                            "url": fallback_url,
                            "headline": val.get("description", ""),
                            "instructor": instructor,
                            "rating": agg.get("averageFiveStarRating"),
                            "num_reviews": agg.get("ratingCount"),
                            "num_subscribers": val.get("enrollmentCount"),
                            "num_lectures": None,
                            "content_length": None,
                            "level": val.get("difficultyLevel"),
                            "is_paid": True,
                            "last_update": None,
                            "published_time": None,
                            "image": val.get("photoUrl") or val.get("courseImage"),
                            "topic": "all-catalog",
                            "platform": "coursera",
                        }
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # 3. Fallback: meta tags (flexible attribute order)
    title_m = re.search(r'<meta\s+[^>]*?content="([^"]*)"[^>]*?property="og:title"', page_html)
    if not title_m:
        title_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', page_html)
    desc_m = re.search(r'<meta\s+[^>]*?content="([^"]*)"[^>]*?(?:property|name)="(?:og:)?description"', page_html)
    if not desc_m:
        desc_m = re.search(r'<meta\s+(?:property|name)="(?:og:)?description"\s+content="([^"]*)"', page_html)
    img_m = re.search(r'<meta\s+[^>]*?content="([^"]*)"[^>]*?property="og:image"', page_html)
    if not img_m:
        img_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', page_html)

    # 4. Ultimate fallback: <title> tag
    if not title_m:
        t = re.search(r'<title>(.*?)</title>', page_html)
        if t:
            title_text = html_mod.unescape(t.group(1)).strip()
            # Skip generic pages like "Coursera Plus"
            if title_text and title_text.lower() not in ("coursera", "coursera plus", ""):
                return {
                    "id": None, "title": title_text, "url": fallback_url,
                    "headline": html_mod.unescape(desc_m.group(1)) if desc_m else "",
                    "instructor": None, "rating": None, "num_reviews": None,
                    "num_subscribers": None, "num_lectures": None,
                    "content_length": None, "level": None, "is_paid": True,
                    "last_update": None, "published_time": None,
                    "image": img_m.group(1) if img_m else None,
                    "topic": "all-catalog", "platform": "coursera",
                }
        return None

    return {
        "id": None,
        "title": html_mod.unescape(title_m.group(1)),
        "url": fallback_url,
        "headline": html_mod.unescape(desc_m.group(1)) if desc_m else "",
        "instructor": None,
        "rating": None, "num_reviews": None, "num_subscribers": None,
        "num_lectures": None, "content_length": None, "level": None,
        "is_paid": True, "last_update": None, "published_time": None,
        "image": img_m.group(1) if img_m else None,
        "topic": "all-catalog", "platform": "coursera",
    }


def _parse_ld_json(page_html: str, fallback_url: str, platform: str) -> dict[str, Any] | None:
    """Parse JSON-LD Course schema from any page."""
    blocks = re.findall(
        r"<script[^>]*type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>",
        page_html, re.DOTALL | re.IGNORECASE,
    )
    for block in blocks:
        raw = html_mod.unescape(block.strip())
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates: list[dict] = []
        if isinstance(payload, list):
            candidates.extend(x for x in payload if isinstance(x, dict))
        elif isinstance(payload, dict):
            candidates.append(payload)
            graph = payload.get("@graph")
            if isinstance(graph, list):
                candidates.extend(x for x in graph if isinstance(x, dict))

        for item in candidates:
            item_type = str(item.get("@type", "")).lower()
            if item_type != "course":
                continue

            authors = item.get("author") or item.get("creator") or []
            if isinstance(authors, dict):
                authors = [authors]
            instructor = None
            if authors and isinstance(authors[0], dict):
                instructor = authors[0].get("name")
            elif authors and isinstance(authors[0], str):
                instructor = authors[0]

            agg = item.get("aggregateRating") or {}
            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price_raw = offers.get("price")
            is_paid = True
            if price_raw is not None:
                try:
                    is_paid = float(price_raw) > 0
                except (TypeError, ValueError):
                    pass

            return {
                "id": None,
                "title": item.get("name") or "",
                "url": item.get("url") or item.get("@id") or fallback_url,
                "headline": item.get("description") or "",
                "instructor": instructor,
                "rating": agg.get("ratingValue"),
                "num_reviews": agg.get("ratingCount") or agg.get("reviewCount"),
                "num_subscribers": None,
                "num_lectures": None,
                "content_length": None,
                "level": None,
                "is_paid": is_paid,
                "last_update": None,
                "published_time": None,
                "image": item.get("image") if isinstance(item.get("image"), str) else None,
                "topic": "all-catalog",
                "platform": platform,
            }
    return None


# ===================================================================
# Checkpoint (resume support)
# ===================================================================

def _checkpoint_path(platform: str) -> Path:
    return CHECKPOINT_DIR / f"{platform}_progress.json"


def load_checkpoint(platform: str) -> set[str]:
    """Load set of already-parsed URLs."""
    path = _checkpoint_path(platform)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data.get("done_urls", []))
        except Exception:
            pass
    return set()


def save_checkpoint(platform: str, done_urls: set[str]) -> None:
    path = _checkpoint_path(platform)
    path.write_text(
        json.dumps({
            "done_urls": list(done_urls),
            "count": len(done_urls),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }),
        encoding="utf-8",
    )


# ===================================================================
# Incremental CSV writer
# ===================================================================

class IncrementalCSV:
    def __init__(self, path: str):
        self.path = path
        self._file_exists = os.path.exists(path) and os.path.getsize(path) > 0

    def append(self, courses: list[dict]) -> None:
        if not courses:
            return
        mode = "a" if self._file_exists else "w"
        with open(self.path, mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            if not self._file_exists:
                writer.writeheader()
                self._file_exists = True
            writer.writerows(courses)


# ===================================================================
# DB batch saver
# ===================================================================

def save_batch_to_db(courses: list[dict]) -> int:
    if not courses:
        return 0
    init_db()
    session = SessionLocal()
    inserted = 0
    try:
        for c in courses:
            exists = session.query(RawCourse.id).filter(RawCourse.url == c["url"]).first()
            if exists:
                session.query(RawCourse).filter(RawCourse.url == c["url"]).update({
                    "title": c.get("title"),
                    "headline": c.get("headline"),
                    "instructor": c.get("instructor"),
                    "rating": c.get("rating"),
                    "num_reviews": c.get("num_reviews"),
                    "num_subscribers": c.get("num_subscribers"),
                    "image_url": c.get("image"),
                    "topic": c.get("topic"),
                    "scraped_at": datetime.now(timezone.utc),
                })
            else:
                session.add(RawCourse(
                    external_id=c.get("id"),
                    platform=c.get("platform", "udemy"),
                    title=c.get("title", ""),
                    url=c.get("url", ""),
                    headline=c.get("headline"),
                    instructor=c.get("instructor"),
                    rating=c.get("rating"),
                    num_reviews=c.get("num_reviews"),
                    num_subscribers=c.get("num_subscribers"),
                    num_lectures=c.get("num_lectures"),
                    content_length=c.get("content_length"),
                    level=c.get("level"),
                    is_paid=c.get("is_paid"),
                    last_update=c.get("last_update"),
                    published_time=c.get("published_time"),
                    image_url=c.get("image"),
                    topic=c.get("topic"),
                ))
                inserted += 1
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error(f"DB batch save failed: {exc}")
    finally:
        session.close()
    return inserted


# ===================================================================
# Worker function (runs in thread pool)
# ===================================================================

def _worker(url: str, platform: str, session: cfrequests.Session) -> dict | None:
    """Fetch + parse a single course page. Returns dict or None."""
    page_html = _fetch(session, url, retries=2)
    if not page_html:
        return None

    if platform == "udemy":
        return parse_udemy_page(page_html, url)
    else:
        return parse_coursera_page(page_html, url)


# ===================================================================
# Main crawl orchestrator
# ===================================================================

def mass_crawl(
    platform: str,
    *,
    workers: int = 3,
    sitemap_pages: int = 0,
    max_courses: int = 0,
    resume: bool = True,
    delay_range: tuple[float, float] = (0.3, 1.0),
) -> int:
    """
    Crawl all courses from the given platform.
    Returns total number of parsed courses.
    """
    session = _build_session()

    # 1. Collect URLs
    logger.info(f"=== Collecting {platform} course URLs from sitemap ===")
    if platform == "udemy":
        all_urls = collect_udemy_urls(session, sitemap_pages=sitemap_pages, max_courses=max_courses)
    elif platform == "coursera":
        all_urls = collect_coursera_urls(session, max_courses=max_courses)
    else:
        logger.error(f"Unknown platform: {platform}")
        return 0

    if not all_urls:
        logger.error("No URLs collected!")
        return 0

    # Save URL inventory
    url_list_path = DATA_DIR / f"{platform}_all_urls.txt"
    url_list_path.write_text("\n".join(all_urls), encoding="utf-8")
    logger.info(f"URL inventory saved to {url_list_path}")

    # 2. Filter out already-done URLs (resume)
    done_urls = load_checkpoint(platform) if resume else set()
    todo_urls = [u for u in all_urls if u not in done_urls]
    logger.info(
        f"Total: {len(all_urls)} | Already done: {len(done_urls)} | "
        f"Remaining: {len(todo_urls)}"
    )

    if not todo_urls:
        logger.info("Nothing to do — all URLs already parsed!")
        return len(done_urls)

    # 3. Prepare outputs
    csv_path = str(DATA_DIR / f"{platform}_all_courses.csv")
    csv_writer = IncrementalCSV(csv_path)

    # 4. Crawl with thread pool
    parsed_total = len(done_urls)
    batch: list[dict] = []
    errors = 0
    consecutive_errors = 0

    logger.info(f"=== Starting crawl: {len(todo_urls)} pages, {workers} workers ===")

    pbar = tqdm(total=len(todo_urls), desc=f"{platform} crawl", unit="page")

    # We use sequential with delays to be polite (parallel would be too aggressive)
    # But we can still batch DB writes
    for i, url in enumerate(todo_urls):
        result = _worker(url, platform, session)

        if result:
            batch.append(result)
            done_urls.add(url)
            consecutive_errors = 0
        else:
            errors += 1
            consecutive_errors += 1
            done_urls.add(url)  # mark as attempted even on failure

        # Flush batch
        if len(batch) >= BATCH_SIZE:
            csv_writer.append(batch)
            db_new = save_batch_to_db(batch)
            parsed_total += len(batch)
            logger.info(
                f"  Batch saved: {len(batch)} to CSV, {db_new} new to DB | "
                f"Total parsed: {parsed_total} | Errors: {errors}"
            )
            batch = []
            save_checkpoint(platform, done_urls)

        pbar.update(1)

        # Adaptive delay
        if consecutive_errors >= 5:
            wait = min(30, 5 * consecutive_errors)
            logger.warning(f"  {consecutive_errors} consecutive errors — cooling down {wait}s")
            time.sleep(wait)
        elif i < len(todo_urls) - 1:
            time.sleep(random.uniform(*delay_range))

    # Final flush
    if batch:
        csv_writer.append(batch)
        save_batch_to_db(batch)
        parsed_total += len(batch)

    save_checkpoint(platform, done_urls)
    pbar.close()

    logger.info(
        f"\n{'='*60}\n"
        f"  {platform.upper()} crawl complete!\n"
        f"  Total parsed: {parsed_total}\n"
        f"  Errors: {errors}\n"
        f"  CSV: {csv_path}\n"
        f"{'='*60}"
    )
    return parsed_total


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Mass-crawl ALL courses from Udemy/Coursera")
    parser.add_argument("--platform", choices=["udemy", "coursera"], required=True)
    parser.add_argument("--workers", type=int, default=3, help="Concurrent workers (default: 3)")
    parser.add_argument("--sitemap-pages", type=int, default=0, help="Sitemap pages to process (0=all)")
    parser.add_argument("--max-courses", type=int, default=0, help="Max courses to fetch (0=all)")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from checkpoint")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh (ignore checkpoint)")
    parser.add_argument("--delay-min", type=float, default=0.3, help="Min delay between requests (s)")
    parser.add_argument("--delay-max", type=float, default=1.0, help="Max delay between requests (s)")
    args = parser.parse_args()

    resume = not args.no_resume

    total = mass_crawl(
        args.platform,
        workers=args.workers,
        sitemap_pages=args.sitemap_pages,
        max_courses=args.max_courses,
        resume=resume,
        delay_range=(args.delay_min, args.delay_max),
    )

    print(f"\nDone! {total} courses processed.")


if __name__ == "__main__":
    main()
