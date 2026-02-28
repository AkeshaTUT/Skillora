"""
Database query helpers (CRUD layer) for the API.
"""

from __future__ import annotations

import math
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from src.models import Author, Course, Platform, Tag, course_tags


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def get_courses(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    # basic filters
    level: Optional[str] = None,
    is_paid: Optional[bool] = None,
    min_rating: Optional[float] = None,
    max_rating: Optional[float] = None,
    tag: Optional[str] = None,
    author: Optional[str] = None,
    # advanced filters
    min_reviews: Optional[int] = None,
    min_subscribers: Optional[int] = None,
    # sorting
    sort_by: str = "rating",
    sort_order: str = "desc",
    # full-text search
    search: Optional[str] = None,
) -> tuple[list[Course], int]:
    """
    Return a page of courses plus total count.

    Supports filtering, sorting and full-text search.
    """
    q = db.query(Course).options(
        joinedload(Course.tags),
        joinedload(Course.authors),
        joinedload(Course.platform),
    )

    # --- Filters ---
    if level:
        q = q.filter(Course.level == level)

    if is_paid is not None:
        q = q.filter(Course.is_paid == is_paid)

    if min_rating is not None:
        q = q.filter(Course.rating >= min_rating)

    if max_rating is not None:
        q = q.filter(Course.rating <= max_rating)

    if min_reviews is not None:
        q = q.filter(Course.reviews_count >= min_reviews)

    if min_subscribers is not None:
        q = q.filter(Course.subscribers_count >= min_subscribers)

    if tag:
        q = q.join(Course.tags).filter(Tag.name.ilike(f"%{tag}%"))

    if author:
        q = q.join(Course.authors).filter(Author.name.ilike(f"%{author}%"))

    # --- Full-text search (title + description) ---
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            or_(
                Course.title.ilike(pattern),
                Course.title_clean.ilike(pattern),
                Course.description.ilike(pattern),
            )
        )

    # --- Count (before pagination) ---
    # Use a subquery for count to avoid issues with joinedload
    count_q = q.with_entities(Course.id).distinct()
    total = count_q.count()

    # --- Sorting ---
    sort_column = {
        "rating": Course.rating,
        "reviews": Course.reviews_count,
        "subscribers": Course.subscribers_count,
        "title": Course.title_clean,
        "created": Course.created_at,
        "lectures": Course.lectures_count,
    }.get(sort_by, Course.rating)

    if sort_order == "asc":
        q = q.order_by(sort_column.asc().nullslast())
    else:
        q = q.order_by(sort_column.desc().nullslast())

    # --- Pagination ---
    offset = (page - 1) * page_size
    courses = q.offset(offset).limit(page_size).all()

    # De-duplicate (joinedload can cause dupes)
    seen = set()
    unique: list[Course] = []
    for c in courses:
        if c.id not in seen:
            seen.add(c.id)
            unique.append(c)

    return unique, total


def get_course_by_id(db: Session, course_id: int) -> Course | None:
    return (
        db.query(Course)
        .options(
            joinedload(Course.tags),
            joinedload(Course.authors),
            joinedload(Course.platform),
        )
        .filter(Course.id == course_id)
        .first()
    )


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def get_tags(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
) -> tuple[list[Tag], int]:
    q = db.query(Tag)
    if search:
        q = q.filter(Tag.name.ilike(f"%{search}%"))
    total = q.count()
    tags = q.order_by(Tag.name).offset((page - 1) * page_size).limit(page_size).all()
    return tags, total


def get_tag_by_id(db: Session, tag_id: int) -> Tag | None:
    return db.query(Tag).filter(Tag.id == tag_id).first()


# ---------------------------------------------------------------------------
# Authors
# ---------------------------------------------------------------------------

def get_authors(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
) -> tuple[list[Author], int]:
    q = db.query(Author)
    if search:
        q = q.filter(Author.name.ilike(f"%{search}%"))
    total = q.count()
    authors = q.order_by(Author.name).offset((page - 1) * page_size).limit(page_size).all()
    return authors, total


def get_author_by_id(db: Session, author_id: int) -> Author | None:
    return db.query(Author).filter(Author.id == author_id).first()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats(db: Session) -> dict:
    total_courses = db.query(Course).count()
    total_authors = db.query(Author).count()
    total_tags = db.query(Tag).count()
    total_platforms = db.query(Platform).count()

    avg_rating = db.query(func.avg(Course.rating)).scalar()

    # Level distribution
    levels = (
        db.query(Course.level, func.count())
        .group_by(Course.level)
        .all()
    )

    return {
        "total_courses": total_courses,
        "total_authors": total_authors,
        "total_tags": total_tags,
        "total_platforms": total_platforms,
        "avg_rating": round(avg_rating, 2) if avg_rating else None,
        "levels": {lvl: cnt for lvl, cnt in levels if lvl},
    }


def paginate_meta(total: int, page: int, page_size: int) -> dict:
    """Helper to build pagination metadata."""
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if page_size else 0,
    }
