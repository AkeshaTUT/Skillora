"""
Udemy course scraper — Weeks 4 & 5
===================================

Features
--------
* Scrapes course metadata from Udemy topic pages via embedded JSON.
* Bypasses Cloudflare with ``curl_cffi`` (Chrome TLS fingerprint).
* **Anti-blocking**: rotating User-Agents, configurable proxy, random delay.
* **Error handling**: retries with exponential back-off, per-topic isolation.
* **Database storage**: saves raw records into ``raw_courses`` via SQLAlchemy.
* **Scheduler**: ``APScheduler`` runs the job every N hours automatically.

Usage
-----
::

    # one-shot run
    python -m src.collector.udemyscraper

    # with scheduler (runs every SCHEDULER_INTERVAL_HOURS)
    python -m src.collector.udemyscraper --schedule
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

from curl_cffi import requests as cfrequests

# ---------------------------------------------------------------------------
# Ensure the project root is importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.config import DATA_DIR, SCHEDULER_INTERVAL_HOURS
from src.database import SessionLocal, init_db
from src.models import RawCourse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("collector.udemy")

# ---------------------------------------------------------------------------
# Anti-blocking — rotating User-Agent pool
# ---------------------------------------------------------------------------
USER_AGENTS: list[str] = [
    # Chrome (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Chrome (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Firefox (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 "
    "Firefox/132.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    # Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = "https://www.udemy.com"

TOPICS: list[str] = [
    "python", "javascript", "java", "web-development", "data-science",
    "machine-learning", "react", "sql", "aws-certification", "cyber-security",
    "docker", "deep-learning", "unity", "excel", "angular",
    "typescript", "django", "go-programming-language", "kubernetes",
    "c-sharp", "node-js", "rust", "devops", "linux",
]

# Retry / delay settings
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds; doubles on each retry
MIN_DELAY = 1.5            # random delay range between pages (seconds)
MAX_DELAY = 4.0

# Proxy (optional, set via env var SCRAPER_PROXY, e.g. "http://user:pass@host:port")
PROXY = os.getenv("SCRAPER_PROXY", "")

CSV_COLUMNS = [
    "id", "title", "url", "headline", "instructor", "rating",
    "num_reviews", "num_subscribers", "num_lectures", "content_length",
    "level", "is_paid", "last_update", "published_time", "image", "topic",
]


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_embedded_json(html: str) -> dict[str, Any] | None:
    """Return the pageProps dict from the __NEXT_DATA__ script tag."""
    m = re.search(
        r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if m:
        try:
            return json.loads(m.group(1)).get("props", {}).get("pageProps")
        except json.JSONDecodeError:
            pass

    for block in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        if len(block) < 10_000:
            continue
        try:
            data = json.loads(block)
            pp = data.get("props", {}).get("pageProps")
            if pp:
                return pp
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def _extract_courses(page_props: dict, topic: str) -> list[dict]:
    courses: list[dict] = []
    for unit in page_props.get("staticDiscoveryUnits", []):
        for item in unit.get("items", []):
            courses.append(_normalise(item, topic))
    for item in page_props.get("genericTopicBundleCourses", []):
        courses.append(_normalise(item, topic))
    return courses


def _normalise(item: dict, topic: str) -> dict:
    instructors = item.get("visible_instructors", [])
    instructor = (
        instructors[0].get("display_name")
        if instructors
        else item.get("instructor_name")
    )
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "url": f"{BASE_URL}{item.get('url', '')}",
        "headline": item.get("headline"),
        "instructor": instructor,
        "rating": item.get("avg_rating_recent") or item.get("avg_rating"),
        "num_reviews": item.get("num_reviews"),
        "num_subscribers": item.get("num_subscribers"),
        "num_lectures": item.get("num_published_lectures"),
        "content_length": item.get("content_info_short") or item.get("content_info"),
        "level": item.get("instructional_level_simple"),
        "is_paid": item.get("is_paid"),
        "last_update": item.get("last_update_date"),
        "published_time": item.get("published_time"),
        "image": item.get("image_240x135"),
        "topic": topic,
    }


# ---------------------------------------------------------------------------
# HTTP helpers (retries, anti-blocking)
# ---------------------------------------------------------------------------

def _build_session() -> cfrequests.Session:
    """Create a curl_cffi session with optional proxy."""
    proxies = {}
    if PROXY:
        proxies = {"http": PROXY, "https": PROXY}
        logger.info(f"Using proxy: {PROXY}")

    session = cfrequests.Session(
        impersonate="chrome",
        proxies=proxies or None,
    )
    return session


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _fetch_with_retry(
    session: cfrequests.Session,
    url: str,
    *,
    max_retries: int = MAX_RETRIES,
) -> cfrequests.Response | None:
    """GET with exponential back-off retries and rotating UA."""
    headers = {
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": _random_ua(),
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers=headers, timeout=15)

            if resp.status_code == 200:
                return resp

            if resp.status_code == 429:
                wait = RETRY_BACKOFF * (2 ** attempt) + random.uniform(0, 2)
                logger.warning(
                    f"  429 Too Many Requests — waiting {wait:.1f}s "
                    f"(attempt {attempt}/{max_retries})"
                )
                time.sleep(wait)
                headers["User-Agent"] = _random_ua()  # rotate UA
                continue

            if resp.status_code in (403, 503):
                wait = RETRY_BACKOFF * attempt + random.uniform(0, 1)
                logger.warning(
                    f"  {resp.status_code} — retrying in {wait:.1f}s "
                    f"(attempt {attempt}/{max_retries})"
                )
                time.sleep(wait)
                headers["User-Agent"] = _random_ua()
                continue

            logger.warning(f"  Unexpected status {resp.status_code}")
            return None

        except cfrequests.errors.RequestsError as exc:
            logger.error(f"  Connection error: {exc}")
            if attempt < max_retries:
                wait = RETRY_BACKOFF * attempt
                logger.info(f"  Retrying in {wait}s (attempt {attempt}/{max_retries})")
                time.sleep(wait)
            else:
                logger.error(f"  All {max_retries} retries exhausted for {url}")
                return None

        except Exception as exc:
            logger.error(f"  Unexpected error: {exc}")
            return None

    return None


# ---------------------------------------------------------------------------
# Core scraper
# ---------------------------------------------------------------------------

def scrape_udemy_topics(
    topics: list[str] | None = None,
) -> list[dict]:
    """
    Visit each topic page, extract embedded course data, de-duplicate by
    course id, and return a flat list of course dicts.
    """
    topics = topics or TOPICS
    session = _build_session()

    seen_ids: set[int] = set()
    all_courses: list[dict] = []
    errors: int = 0

    for i, topic in enumerate(topics, 1):
        url = f"{BASE_URL}/topic/{topic}/"
        logger.info(f"[{i}/{len(topics)}] {url}")

        resp = _fetch_with_retry(session, url)

        if resp is None:
            errors += 1
            continue

        page_props = _extract_embedded_json(resp.text)
        if not page_props:
            logger.warning("  No embedded JSON — skipping")
            errors += 1
            continue

        courses = _extract_courses(page_props, topic)
        new = 0
        for c in courses:
            cid = c.get("id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                all_courses.append(c)
                new += 1

        logger.info(
            f"  {len(courses)} courses, {new} new  (total: {len(all_courses)})"
        )

        # Anti-blocking: random delay between requests
        if i < len(topics):
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            time.sleep(delay)

    logger.info(
        f"Scraping complete: {len(all_courses)} unique courses, "
        f"{errors} topic errors"
    )
    return all_courses


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------

def save_to_db(courses: list[dict]) -> int:
    """
    Upsert scraped courses into the ``raw_courses`` table.

    Returns the number of new rows inserted.
    """
    if not courses:
        logger.warning("No courses to save to DB.")
        return 0

    init_db()
    session = SessionLocal()
    inserted = 0

    try:
        for c in courses:
            # Check if this exact URL already exists
            exists = (
                session.query(RawCourse.id)
                .filter(RawCourse.url == c["url"])
                .first()
            )
            if exists:
                # Update existing record
                session.query(RawCourse).filter(
                    RawCourse.url == c["url"]
                ).update({
                    "title": c.get("title"),
                    "headline": c.get("headline"),
                    "instructor": c.get("instructor"),
                    "rating": c.get("rating"),
                    "num_reviews": c.get("num_reviews"),
                    "num_subscribers": c.get("num_subscribers"),
                    "num_lectures": c.get("num_lectures"),
                    "content_length": c.get("content_length"),
                    "level": c.get("level"),
                    "is_paid": c.get("is_paid"),
                    "last_update": c.get("last_update"),
                    "published_time": c.get("published_time"),
                    "image_url": c.get("image"),
                    "topic": c.get("topic"),
                    "scraped_at": datetime.now(timezone.utc),
                })
            else:
                row = RawCourse(
                    external_id=c.get("id"),
                    platform="udemy",
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
                )
                session.add(row)
                inserted += 1

        session.commit()
        logger.info(
            f"DB: {inserted} new rows inserted, "
            f"{len(courses) - inserted} existing updated"
        )
    except Exception as exc:
        session.rollback()
        logger.error(f"DB save failed: {exc}")
        raise
    finally:
        session.close()

    return inserted


# ---------------------------------------------------------------------------
# CSV export (optional, kept for convenience)
# ---------------------------------------------------------------------------

def save_to_csv(courses: list[dict], path: str) -> None:
    if not courses:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(courses)
    logger.info(f"CSV: {len(courses)} courses → {path}")


# ---------------------------------------------------------------------------
# Scheduled job wrapper
# ---------------------------------------------------------------------------

def collector_job() -> None:
    """Single scraping + DB-save run (used by the scheduler)."""
    logger.info("=" * 60)
    logger.info("Starting scheduled collection run")
    logger.info("=" * 60)

    courses = scrape_udemy_topics()

    # Save to DB
    save_to_db(courses)

    # Also save CSV snapshot
    csv_path = str(DATA_DIR / "udemy_courses.csv")
    save_to_csv(courses, csv_path)

    logger.info(f"Run finished — {len(courses)} courses collected.\n")


def run_scheduler() -> None:
    """Start APScheduler to run the collector on an interval."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.error(
            "APScheduler is not installed. "
            "Run: pip install apscheduler"
        )
        sys.exit(1)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        collector_job,
        trigger=IntervalTrigger(hours=SCHEDULER_INTERVAL_HOURS),
        id="udemy_collector",
        name=f"Udemy collector (every {SCHEDULER_INTERVAL_HOURS}h)",
        next_run_time=datetime.now(timezone.utc),  # run immediately on start
        max_instances=1,
        misfire_grace_time=3600,
    )

    logger.info(
        f"Scheduler started — interval: every {SCHEDULER_INTERVAL_HOURS} hours. "
        "Press Ctrl+C to stop."
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
        scheduler.shutdown()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Udemy course collector")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run on a repeating schedule (APScheduler)",
    )
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Save to CSV only (skip DB)",
    )
    args = parser.parse_args()

    if args.schedule:
        run_scheduler()
    else:
        courses = scrape_udemy_topics()

        if not args.csv_only:
            save_to_db(courses)

        csv_path = os.path.normpath(
            os.path.join(_PROJECT_ROOT, "..", "udemy_courses.csv")
        )
        save_to_csv(courses, csv_path)

        # Summary
        print(f"\n{'=' * 70}")
        print(f" Scraped {len(courses)} unique courses across {len(TOPICS)} topics")
        print(f"{'=' * 70}")
        for c in courses[:10]:
            stars = f"{c['rating']:.1f}" if c.get("rating") else "N/A"
            print(f"  [{c['topic']:>18}]  {stars}★  {c['title']}")


if __name__ == "__main__":
    main()

