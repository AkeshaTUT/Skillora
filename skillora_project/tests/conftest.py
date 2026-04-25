from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.api.main import app
from src.database import Base, get_db
from src.models import Author, Course, Platform, Tag


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()

    platform = Platform(name="Udemy", base_url="https://www.udemy.com")
    author = Author(name="Test Author")
    tag = Tag(name="Python")
    course = Course(
        external_id=1001,
        title="Python API Course",
        title_clean="Python API Course",
        description="Learn FastAPI and JWT",
        course_url="https://www.udemy.com/course/python-api-course",
        image_url="https://img.example/1.jpg",
        is_paid=True,
        rating=4.8,
        reviews_count=120,
        subscribers_count=5000,
        lectures_count=50,
        content_length="10 hours",
        level="Beginner",
        platform=platform,
    )
    course.authors.append(author)
    course.tags.append(tag)

    session.add_all([platform, author, tag, course])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
