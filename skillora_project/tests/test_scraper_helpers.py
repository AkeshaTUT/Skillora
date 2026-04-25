from __future__ import annotations

from src.collector.udemyscraper import _extract_embedded_json, _normalise


def test_extract_embedded_json_from_next_data():
    html = (
        '<html><head></head><body>'
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props": {"pageProps": {"staticDiscoveryUnits": []}}}'
        "</script></body></html>"
    )

    payload = _extract_embedded_json(html)
    assert payload is not None
    assert "staticDiscoveryUnits" in payload


def test_normalise_maps_expected_fields():
    raw = {
        "id": 123,
        "title": "Python Basics",
        "url": "/course/python-basics/",
        "headline": "Learn python fast",
        "visible_instructors": [{"display_name": "Jane Doe"}],
        "avg_rating_recent": 4.7,
        "num_reviews": 42,
        "num_subscribers": 999,
        "num_published_lectures": 25,
        "content_info_short": "5 hours",
        "instructional_level_simple": "Beginner",
        "is_paid": True,
        "last_update_date": "2026-01-01",
        "published_time": "2026-01-01T00:00:00Z",
        "image_240x135": "https://img.example/123.jpg",
    }

    item = _normalise(raw, "python")
    assert item["id"] == 123
    assert item["url"].startswith("https://www.udemy.com")
    assert item["instructor"] == "Jane Doe"
    assert item["topic"] == "python"
