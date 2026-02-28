# Skillora

Course aggregator that scrapes online courses from Udemy and exposes them via a REST API.

## Features

- **Collector**: Scrapes Udemy courses using curl_cffi with Cloudflare bypass (Chrome TLS fingerprint)
- **Normalizer**: Cleans and normalizes raw data, extracts tags and authors
- **REST API**: FastAPI with pagination, filtering, full-text search, and Swagger UI

## Quick Start

```bash
cd skillora_project
pip install -r requirements.txt

# Run scraper
python -m src.collector.udemyscraper

# Run normalizer
python -m src.processing.normalizer

# Start API server
python -m uvicorn src.api.main:app --port 8080
```

## API Docs

- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc
