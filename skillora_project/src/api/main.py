"""
Skillora — FastAPI application entry-point.
=============================================

Run with::

    cd skillora_project
    python -m uvicorn src.api.main:app --reload --port 8000

Swagger UI:  http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router as api_router
from src.database import init_db

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Skillora API",
    description=(
        "REST API for the Skillora course aggregator.\n\n"
        "Features:\n"
        "- Browse and search online courses from multiple platforms\n"
        "- Filter by level, rating, price, tags, authors\n"
        "- Full-text search across titles and descriptions\n"
        "- Pagination and flexible sorting\n"
        "- Aggregate statistics"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "Courses", "description": "Browse, search and filter courses"},
        {"name": "Tags", "description": "Technology / topic tags"},
        {"name": "Authors", "description": "Course instructors"},
        {"name": "Stats", "description": "Aggregate database statistics"},
    ],
)

# ---------------------------------------------------------------------------
# CORS — allow everything during development
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(api_router, prefix="/api")


# ---------------------------------------------------------------------------
# Startup event — ensure tables exist
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    init_db()


# ---------------------------------------------------------------------------
# Health-check (root)
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    return {"service": "Skillora API", "version": "1.0.0", "docs": "/docs"}
