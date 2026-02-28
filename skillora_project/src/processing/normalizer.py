"""
Data cleaning, normalisation, and entity extraction.
=====================================================

Week 6: takes raw scraper records from ``raw_courses`` and produces
clean, normalised rows in ``courses`` / ``authors`` / ``tags`` / ``platforms``.

Usage::

    python -m src.processing.normalizer          # one-shot
    python -m src.processing.normalizer --stats   # show stats after
"""

from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Importable from project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy.orm import Session

from src.database import SessionLocal, init_db
from src.models import (
    Author,
    Course,
    Platform,
    RawCourse,
    Tag,
    course_authors,
    course_tags,
)

logger = logging.getLogger("processing.normalizer")

# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

# Common "noise" patterns in course titles
_NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\[[\d]{4}\s*(Edition|Update)\]", re.I),
    re.compile(r"\([\d]{4}\s*(Edition|Update)\)", re.I),
    re.compile(r"™|®|©"),
    re.compile(r"\s{2,}"),                 # collapse multiple spaces
]


def clean_text(text: str | None) -> str:
    """Strip noise from a title / headline string."""
    if not text:
        return ""
    # Normalise unicode (e.g. fancy quotes → ASCII)
    text = unicodedata.normalize("NFKD", text)
    for pat in _NOISE_PATTERNS:
        text = pat.sub(" ", text)
    text = text.strip()
    # Capitalise first letter if all-lower
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def clean_url(url: str | None) -> str:
    """Normalise course URL (strip query params / trailing junk)."""
    if not url:
        return ""
    url = url.split("?")[0].rstrip("/")
    return url


def normalise_level(raw: str | None) -> str:
    """Map free-form level strings to a controlled vocabulary."""
    if not raw:
        return "All Levels"
    low = raw.strip().lower()
    if "begin" in low:
        return "Beginner"
    if "inter" in low:
        return "Intermediate"
    if "expert" in low or "advanc" in low:
        return "Advanced"
    return "All Levels"


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

# Known technology / skill tags to look for in titles + headlines
_TAG_KEYWORDS: list[str] = [
    "Python", "JavaScript", "TypeScript", "Java", "C#", "C++", "Go",
    "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Dart", "Scala", "R",
    "SQL", "NoSQL", "MongoDB", "PostgreSQL", "MySQL", "Redis",
    "HTML", "CSS", "React", "Angular", "Vue", "Node.js", "Next.js",
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot",
    "Docker", "Kubernetes", "AWS", "Azure", "GCP", "DevOps", "CI/CD",
    "Machine Learning", "Deep Learning", "AI", "NLP", "Computer Vision",
    "Data Science", "Data Analysis", "Data Engineering",
    "TensorFlow", "PyTorch", "Pandas", "NumPy", "Scikit-learn",
    "Unity", "Unreal Engine", "Blender", "Game Development",
    "Linux", "Git", "REST API", "GraphQL", "Microservices",
    "Cybersecurity", "Ethical Hacking", "Penetration Testing",
    "Excel", "Power BI", "Tableau",
    "Flutter", "React Native", "Android", "iOS",
    "Agile", "Scrum", "Project Management",
    "Blockchain", "Web3", "Solidity",
    "ChatGPT", "LLM", "Generative AI", "Prompt Engineering",
]

# Pre-compile tag patterns (word-boundary match, case-insensitive)
_TAG_REGEXES: list[tuple[str, re.Pattern]] = [
    (tag, re.compile(rf"\b{re.escape(tag)}\b", re.I))
    for tag in _TAG_KEYWORDS
]


def extract_tags(title: str, headline: str | None = None) -> list[str]:
    """Return a de-duplicated list of matching skill/tech tags."""
    combined = f"{title} {headline or ''}"
    found: list[str] = []
    seen: set[str] = set()
    for canonical, pattern in _TAG_REGEXES:
        if pattern.search(combined) and canonical.lower() not in seen:
            found.append(canonical)
            seen.add(canonical.lower())
    return found


def extract_instructor(raw_name: str | None) -> str:
    """Clean up instructor name."""
    if not raw_name:
        return "Unknown"
    name = raw_name.strip()
    # Remove trailing commas / dots
    name = name.rstrip(",.")
    return name or "Unknown"


# ---------------------------------------------------------------------------
# Core normalisation pipeline
# ---------------------------------------------------------------------------

def _get_or_create_platform(db: Session, name: str, base_url: str) -> Platform:
    obj = db.query(Platform).filter(Platform.name == name).first()
    if not obj:
        obj = Platform(name=name, base_url=base_url)
        db.add(obj)
        db.flush()
    return obj


def _get_or_create_author(db: Session, name: str) -> Author:
    clean = extract_instructor(name)
    obj = db.query(Author).filter(Author.name == clean).first()
    if not obj:
        obj = Author(name=clean)
        db.add(obj)
        db.flush()
    return obj


def _get_or_create_tag(db: Session, name: str) -> Tag:
    obj = db.query(Tag).filter(Tag.name == name).first()
    if not obj:
        obj = Tag(name=name)
        db.add(obj)
        db.flush()
    return obj


def normalise_raw_courses(db: Session | None = None) -> dict:
    """
    Read all ``raw_courses``, clean and normalise, then upsert into
    ``courses`` + related tables.

    Returns a stats dict.
    """
    own_session = db is None
    if own_session:
        init_db()
        db = SessionLocal()

    stats = {"processed": 0, "inserted": 0, "updated": 0, "tags_created": 0, "authors_created": 0}

    try:
        raw_rows: list[RawCourse] = db.query(RawCourse).all()
        if not raw_rows:
            logger.warning("No raw courses to normalise.")
            return stats

        platform = _get_or_create_platform(db, "Udemy", "https://www.udemy.com")

        existing_authors = db.query(Author).count()
        existing_tags = db.query(Tag).count()

        for raw in raw_rows:
            stats["processed"] += 1

            title_clean = clean_text(raw.title)
            url_clean = clean_url(raw.url)
            level_clean = normalise_level(raw.level)

            # Upsert course
            course = db.query(Course).filter(Course.course_url == url_clean).first()
            if course:
                course.title = raw.title
                course.title_clean = title_clean
                course.description = raw.headline
                course.image_url = raw.image_url
                course.rating = round(raw.rating, 2) if raw.rating else None
                course.reviews_count = raw.num_reviews or 0
                course.subscribers_count = raw.num_subscribers or 0
                course.lectures_count = raw.num_lectures or 0
                course.content_length = raw.content_length
                course.level = level_clean
                course.is_paid = raw.is_paid if raw.is_paid is not None else True
                course.last_update = raw.last_update
                course.published_time = raw.published_time
                course.external_id = raw.external_id
                stats["updated"] += 1
            else:
                course = Course(
                    external_id=raw.external_id,
                    title=raw.title,
                    title_clean=title_clean,
                    description=raw.headline,
                    course_url=url_clean,
                    image_url=raw.image_url,
                    price=0.0,
                    is_paid=raw.is_paid if raw.is_paid is not None else True,
                    rating=round(raw.rating, 2) if raw.rating else None,
                    reviews_count=raw.num_reviews or 0,
                    subscribers_count=raw.num_subscribers or 0,
                    lectures_count=raw.num_lectures or 0,
                    content_length=raw.content_length,
                    level=level_clean,
                    last_update=raw.last_update,
                    published_time=raw.published_time,
                    platform_id=platform.id,
                )
                db.add(course)
                db.flush()
                stats["inserted"] += 1

            # --- Authors ---
            author = _get_or_create_author(db, raw.instructor)
            if author not in course.authors:
                course.authors.append(author)

            # --- Tags ---
            tags = extract_tags(raw.title, raw.headline)
            # Also add topic as a tag if not empty
            if raw.topic and raw.topic not in [t.lower() for t in tags]:
                tags.append(raw.topic.replace("-", " ").title())

            for tag_name in tags:
                tag = _get_or_create_tag(db, tag_name)
                if tag not in course.tags:
                    course.tags.append(tag)

        db.commit()

        stats["authors_created"] = db.query(Author).count() - existing_authors
        stats["tags_created"] = db.query(Tag).count() - existing_tags

        logger.info(
            f"Normalisation done: {stats['processed']} processed, "
            f"{stats['inserted']} new, {stats['updated']} updated, "
            f"{stats['tags_created']} new tags, {stats['authors_created']} new authors"
        )

    except Exception as exc:
        db.rollback()
        logger.error(f"Normalisation failed: {exc}")
        raise
    finally:
        if own_session:
            db.close()

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    )

    parser = argparse.ArgumentParser(description="Normalise raw course data")
    parser.add_argument("--stats", action="store_true", help="Print DB stats after")
    args = parser.parse_args()

    stats = normalise_raw_courses()

    print(f"\n{'=' * 60}")
    print(f" Processed : {stats['processed']}")
    print(f" Inserted  : {stats['inserted']}")
    print(f" Updated   : {stats['updated']}")
    print(f" New tags  : {stats['tags_created']}")
    print(f" New authors: {stats['authors_created']}")
    print(f"{'=' * 60}")

    if args.stats:
        db = SessionLocal()
        print(f"\n DB stats:")
        print(f"   courses : {db.query(Course).count()}")
        print(f"   authors : {db.query(Author).count()}")
        print(f"   tags    : {db.query(Tag).count()}")
        print(f"   platforms: {db.query(Platform).count()}")

        # Show a few sample courses with their tags
        samples = db.query(Course).limit(5).all()
        for c in samples:
            tag_names = ", ".join(t.name for t in c.tags[:6])
            author_names = ", ".join(a.name for a in c.authors)
            print(
                f"   [{c.level:>12}] {c.rating or 0:.1f}★  "
                f"{c.title_clean[:50]}  |  {author_names}  |  tags: {tag_names}"
            )
        db.close()


if __name__ == "__main__":
    main()
