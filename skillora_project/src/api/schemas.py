"""
Pydantic schemas for request validation and response serialisation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared / nested
# ---------------------------------------------------------------------------

class TagOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class AuthorOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class PlatformOut(BaseModel):
    id: int
    name: str
    base_url: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------

class CourseOut(BaseModel):
    """Full course representation returned by the API."""

    id: int
    external_id: Optional[int] = None
    title: str
    title_clean: Optional[str] = None
    description: Optional[str] = None
    course_url: str
    image_url: Optional[str] = None
    price: Optional[float] = 0.0
    is_paid: Optional[bool] = True
    rating: Optional[float] = None
    reviews_count: int = 0
    subscribers_count: int = 0
    lectures_count: int = 0
    content_length: Optional[str] = None
    level: Optional[str] = None
    last_update: Optional[str] = None
    published_time: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    platform: Optional[PlatformOut] = None
    authors: list[AuthorOut] = []
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


class CourseListOut(BaseModel):
    """Compact course in list responses (no nested relations)."""

    id: int
    title: str
    title_clean: Optional[str] = None
    course_url: str
    image_url: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: int = 0
    subscribers_count: int = 0
    level: Optional[str] = None
    is_paid: Optional[bool] = True

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Pagination wrapper
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel):
    """Generic paginated response envelope."""

    total: int = Field(..., description="Total number of matching records")
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    pages: int = Field(..., description="Total number of pages")
    items: list = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class StatsOut(BaseModel):
    total_courses: int
    total_authors: int
    total_tags: int
    total_platforms: int
    avg_rating: Optional[float] = None
    levels: dict[str, int] = {}
