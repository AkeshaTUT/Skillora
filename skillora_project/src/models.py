from sqlalchemy import (
    Boolean, Column, Integer, String, Float,
    ForeignKey, Table, DateTime, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.database import Base

# ---------------------------------------------------------------------------
# Association tables
# ---------------------------------------------------------------------------

course_authors = Table(
    "course_authors",
    Base.metadata,
    Column("course_id", Integer, ForeignKey("courses.id"), primary_key=True),
    Column("author_id", Integer, ForeignKey("authors.id"), primary_key=True),
)

course_tags = Table(
    "course_tags",
    Base.metadata,
    Column("course_id", Integer, ForeignKey("courses.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Raw (staging) table — holds unprocessed scraper output
# ---------------------------------------------------------------------------

class RawCourse(Base):
    """Stores every scraped record exactly as-is before normalisation."""

    __tablename__ = "raw_courses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(Integer, index=True, comment="Course ID on the source platform")
    platform = Column(String(50), nullable=False, default="udemy")
    title = Column(String(500), nullable=False)
    url = Column(String(500), nullable=False, index=True)
    headline = Column(Text, nullable=True)
    instructor = Column(String(300), nullable=True)
    rating = Column(Float, nullable=True)
    num_reviews = Column(Integer, nullable=True)
    num_subscribers = Column(Integer, nullable=True)
    num_lectures = Column(Integer, nullable=True)
    content_length = Column(String(100), nullable=True)
    level = Column(String(50), nullable=True)
    is_paid = Column(Boolean, nullable=True)
    last_update = Column(String(30), nullable=True)
    published_time = Column(String(50), nullable=True)
    image_url = Column(String(500), nullable=True)
    topic = Column(String(100), nullable=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RawCourse(id={self.id}, title='{self.title[:40]}…')>"


# ---------------------------------------------------------------------------
# Normalised / production tables
# ---------------------------------------------------------------------------

class Platform(Base):
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    base_url = Column(String(255), nullable=False)
    courses = relationship("Course", back_populates="platform")


class Author(Base):
    __tablename__ = "authors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True)
    courses = relationship("Course", secondary=course_authors, back_populates="authors")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    courses = relationship("Course", secondary=course_tags, back_populates="tags")


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, index=True, comment="ID on the source platform")
    title = Column(String(500), nullable=False)
    title_clean = Column(String(500), nullable=True, comment="Title after cleaning")
    description = Column(Text, nullable=True)
    course_url = Column(String(500), unique=True, nullable=False, index=True)
    image_url = Column(String(500), nullable=True)
    price = Column(Float, default=0.0)
    is_paid = Column(Boolean, default=True)
    rating = Column(Float, nullable=True)
    reviews_count = Column(Integer, default=0)
    subscribers_count = Column(Integer, default=0)
    lectures_count = Column(Integer, default=0)
    content_length = Column(String(100), nullable=True)
    level = Column(String(50), nullable=True)
    last_update = Column(String(30), nullable=True)
    published_time = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    platform_id = Column(Integer, ForeignKey("platforms.id"))
    platform = relationship("Platform", back_populates="courses")
    authors = relationship("Author", secondary=course_authors, back_populates="courses")
    tags = relationship("Tag", secondary=course_tags, back_populates="courses")
