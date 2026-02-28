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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api import crud
from src.api.schemas import (
    AuthorOut,
    CourseListOut,
    CourseOut,
    PaginatedResponse,
    StatsOut,
    TagOut,
)
from src.database import get_db

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
    return crud.get_stats(db)
