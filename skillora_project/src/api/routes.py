"""
REST API routes — Weeks 7 & 8
==============================

* GET endpoints for courses, tags, authors, stats
* Pagination (page / page_size)
* Basic filtering (level, is_paid, min_rating, tag, author)
* Advanced filtering (min_reviews, min_subscribers)
* Full-text search (``?search=…``)
* Sorting (``?sort_by=rating&sort_order=desc``)
* Swagger UI auto-docs at ``/docs``
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.api import crud
from src.api.security import require_auth
from src.api.schemas import (
    AuthorOut,
    CourseListOut,
    CourseOut,
    PaginatedResponse,
    StatsOut,
    TagOut,
)
from src.collector.udemyscraper import collector_job
from src.collector.udemyscraper import scrape_udemy_query
from src.collector.udemy_api import search_udemy_api
from src.collector.coursera_search import search_coursera
from src.database import get_db
from src.services.cache import delete_key, get_json, set_json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# In-memory search result cache (TTL = 5 minutes)
# ---------------------------------------------------------------------------
_SEARCH_CACHE: dict[str, tuple[float, list]] = {}  # key -> (expires_ts, items)
_SEARCH_TTL = 300  # seconds


def _cache_get(key: str) -> list | None:
    entry = _SEARCH_CACHE.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def _cache_set(key: str, items: list) -> None:
    # Keep cache from growing unbounded (max 200 keys)
    if len(_SEARCH_CACHE) >= 200:
        oldest = min(_SEARCH_CACHE, key=lambda k: _SEARCH_CACHE[k][0])
        _SEARCH_CACHE.pop(oldest, None)
    _SEARCH_CACHE[key] = (time.monotonic() + _SEARCH_TTL, items)

router = APIRouter()


# ===================================================================
#  COURSES
# ===================================================================


@router.get(
    "/courses",
    response_model=PaginatedResponse,
    summary="List courses",
    description=(
        "Returns a paginated list of courses with optional filtering, "
        "sorting, and full-text search."
    ),
    tags=["Courses"],
)
def list_courses(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    # basic filters
    level: Optional[str] = Query(
        None,
        description="Filter by level: Beginner, Intermediate, Advanced, All Levels",
    ),
    is_paid: Optional[bool] = Query(None, description="Filter paid/free courses"),
    min_rating: Optional[float] = Query(None, ge=0, le=5, description="Minimum rating"),
    max_rating: Optional[float] = Query(None, ge=0, le=5, description="Maximum rating"),
    tag: Optional[str] = Query(None, description="Filter by tag name (partial match)"),
    author: Optional[str] = Query(None, description="Filter by author name (partial match)"),
    # advanced filters
    min_reviews: Optional[int] = Query(None, ge=0, description="Minimum number of reviews"),
    min_subscribers: Optional[int] = Query(None, ge=0, description="Minimum subscribers"),
    # sorting
    sort_by: str = Query(
        "rating",
        description="Sort field: rating, reviews, subscribers, title, created, lectures",
    ),
    sort_order: str = Query("desc", description="Sort direction: asc or desc"),
    # search
    search: Optional[str] = Query(
        None, min_length=1, max_length=200,
        description="Full-text search across title and description",
    ),
    db: Session = Depends(get_db),
):
    courses, total = crud.get_courses(
        db,
        page=page,
        page_size=page_size,
        level=level,
        is_paid=is_paid,
        min_rating=min_rating,
        max_rating=max_rating,
        tag=tag,
        author=author,
        min_reviews=min_reviews,
        min_subscribers=min_subscribers,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
    )

    meta = crud.paginate_meta(total, page, page_size)
    items = [CourseListOut.model_validate(c) for c in courses]

    return PaginatedResponse(items=items, **meta)


@router.get(
    "/courses/{course_id}",
    response_model=CourseOut,
    summary="Get course details",
    description="Returns full details for a single course including tags and authors.",
    tags=["Courses"],
)
def get_course(course_id: int, db: Session = Depends(get_db)):
    course = crud.get_course_by_id(db, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return CourseOut.model_validate(course)


# ===================================================================
#  TAGS
# ===================================================================


@router.get(
    "/tags",
    response_model=PaginatedResponse,
    summary="List tags",
    description="Returns a paginated list of tags with optional search.",
    tags=["Tags"],
)
def list_tags(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search tag name"),
    db: Session = Depends(get_db),
):
    tags, total = crud.get_tags(db, page=page, page_size=page_size, search=search)
    meta = crud.paginate_meta(total, page, page_size)
    items = [TagOut.model_validate(t) for t in tags]
    return PaginatedResponse(items=items, **meta)


@router.get(
    "/tags/{tag_id}",
    response_model=TagOut,
    summary="Get tag by ID",
    tags=["Tags"],
)
def get_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = crud.get_tag_by_id(db, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return TagOut.model_validate(tag)


@router.get(
    "/tags/{tag_id}/courses",
    response_model=PaginatedResponse,
    summary="List courses by tag",
    description="Returns courses associated with a specific tag.",
    tags=["Tags"],
)
def list_courses_by_tag(
    tag_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    tag = crud.get_tag_by_id(db, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    courses, total = crud.get_courses(db, page=page, page_size=page_size, tag=tag.name)
    meta = crud.paginate_meta(total, page, page_size)
    items = [CourseListOut.model_validate(c) for c in courses]
    return PaginatedResponse(items=items, **meta)


# ===================================================================
#  AUTHORS
# ===================================================================


@router.get(
    "/authors",
    response_model=PaginatedResponse,
    summary="List authors",
    description="Returns a paginated list of authors with optional search.",
    tags=["Authors"],
)
def list_authors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search author name"),
    db: Session = Depends(get_db),
):
    authors, total = crud.get_authors(db, page=page, page_size=page_size, search=search)
    meta = crud.paginate_meta(total, page, page_size)
    items = [AuthorOut.model_validate(a) for a in authors]
    return PaginatedResponse(items=items, **meta)


@router.get(
    "/authors/{author_id}",
    response_model=AuthorOut,
    summary="Get author by ID",
    tags=["Authors"],
)
def get_author(author_id: int, db: Session = Depends(get_db)):
    author = crud.get_author_by_id(db, author_id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")
    return AuthorOut.model_validate(author)


@router.get(
    "/authors/{author_id}/courses",
    response_model=PaginatedResponse,
    summary="List courses by author",
    description="Returns courses taught by a specific author.",
    tags=["Authors"],
)
def list_courses_by_author(
    author_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    author = crud.get_author_by_id(db, author_id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    courses, total = crud.get_courses(db, page=page, page_size=page_size, author=author.name)
    meta = crud.paginate_meta(total, page, page_size)
    items = [CourseListOut.model_validate(c) for c in courses]
    return PaginatedResponse(items=items, **meta)


# ===================================================================
#  STATS
# ===================================================================


@router.get(
    "/stats",
    response_model=StatsOut,
    summary="Database statistics",
    description="Returns aggregate statistics about the course database.",
    tags=["Stats"],
)
def get_stats(db: Session = Depends(get_db)):
    cache_key = "stats:v1"
    cached = get_json(cache_key)
    if cached:
        return cached

    payload = crud.get_stats(db)
    set_json(cache_key, payload)
    return payload


@router.get(
    "/admin/stats",
    response_model=StatsOut,
    summary="Protected database statistics",
    description="Requires Bearer JWT token.",
    tags=["Admin"],
)
def get_stats_protected(
    db: Session = Depends(get_db),
    _user=Depends(require_auth),
):
    cache_key = "stats:v1"
    cached = get_json(cache_key)
    if cached:
        return cached
    payload = crud.get_stats(db)
    set_json(cache_key, payload)
    return payload


@router.post(
    "/admin/collect-now",
    summary="Run collector in background",
    description="Requires Bearer JWT token. Triggers scraper + DB update in background.",
    tags=["Admin"],
)
def collect_now(
    background_tasks: BackgroundTasks,
    _user=Depends(require_auth),
):
    background_tasks.add_task(collector_job)
    delete_key("stats:v1")
    return {"status": "queued", "message": "Collector job started in background"}


@router.get(
    "/external/udemy/search",
    summary="Live Udemy search by query",
    description="Searches Udemy via topic-backed query mode.",
    tags=["Courses"],
)
def live_search_udemy(
    query: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(20, ge=1, le=100),
):
    items = scrape_udemy_query(query, limit=limit)
    return {"platform": "udemy", "query": query, "count": len(items), "items": items}


@router.get(
    "/external/coursera/search",
    summary="Live Coursera search by query",
    description="Searches Coursera public search page and extracts course links.",
    tags=["Courses"],
)
def live_search_coursera(
    query: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(20, ge=1, le=100),
):
    items = search_coursera(query, limit=limit)
    return {"platform": "coursera", "query": query, "count": len(items), "items": items}


@router.get(
    "/external/search",
    summary="Competence Booster unified search",
    description=(
        "Searches the local DB of crawled courses first (fast, ~50ms). "
        "Falls back to live Udemy API + Coursera API in parallel (~1-3s). "
        "Results are cached in-memory for 5 minutes."
    ),
    tags=["Courses"],
)
def live_search_all(
    query: str = Query(..., min_length=2, max_length=120),
    source: str = Query("all", description="all|udemy|coursera"),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from src.models import RawCourse

    source_l = source.lower()
    cache_key = f"search:{source_l}:{query.lower().strip()}:{limit}"

    # ----------------------------------------------------------------
    # 1. Check in-memory cache first
    # ----------------------------------------------------------------
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"query": query, "source": source_l, "count": len(cached), "items": cached, "cached": True}

    # ----------------------------------------------------------------
    # 2. Search local DB (raw_courses from mass crawl)
    # ----------------------------------------------------------------
    pattern = f"%{query}%"
    q = db.query(RawCourse)
    if source_l == "udemy":
        q = q.filter(RawCourse.platform == "udemy")
    elif source_l == "coursera":
        q = q.filter(RawCourse.platform == "coursera")

    q = q.filter(
        or_(
            RawCourse.title.ilike(pattern),
            RawCourse.headline.ilike(pattern),
            RawCourse.topic.ilike(pattern),
            RawCourse.instructor.ilike(pattern),
        )
    )
    q = q.order_by(
        RawCourse.rating.desc().nullslast(),
        RawCourse.num_reviews.desc().nullslast(),
    )
    db_results = q.limit(limit).all()

    if db_results:
        items = [
            {
                "title": r.title,
                "description": r.headline or "",
                "course_url": r.url,
                "platform": r.platform or "unknown",
                "rating": r.rating,
                "reviews_count": r.num_reviews or 0,
                "subscribers_count": r.num_subscribers or 0,
                "instructor": r.instructor,
                "image_url": r.image_url,
                "level": r.level,
                "is_paid": r.is_paid,
                "content_length": r.content_length,
                "source": "db",
            }
            for r in db_results
        ]
        _cache_set(cache_key, items)
        return {"query": query, "source": source_l, "count": len(items), "items": items}

    # ----------------------------------------------------------------
    # 3. Fallback: live API calls — Udemy API + Coursera in parallel
    # ----------------------------------------------------------------
    out: list[dict] = []

    def _fetch_udemy() -> list[dict]:
        return search_udemy_api(query, limit=limit)

    def _fetch_coursera() -> list[dict]:
        return search_coursera(query, limit=limit)

    tasks: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        if source_l in {"all", "udemy"}:
            tasks["udemy"] = pool.submit(_fetch_udemy)
        if source_l in {"all", "coursera"}:
            tasks["coursera"] = pool.submit(_fetch_coursera)

        for name, future in tasks.items():
            try:
                result = future.result(timeout=12)
                out.extend(result)
            except Exception as exc:
                import logging
                logging.getLogger("routes").warning(f"{name} live fetch failed: {exc}")

    # Sort combined results: DB-quality score (rating * log(reviews+1))
    import math
    def _score(item: dict) -> float:
        rating = item.get("rating") or 0
        reviews = item.get("reviews_count") or 0
        return (rating or 0) * math.log(reviews + 2)

    out.sort(key=_score, reverse=True)
    out = out[:limit]

    _cache_set(cache_key, out)
    return {"query": query, "source": source_l, "count": len(out), "items": out}

