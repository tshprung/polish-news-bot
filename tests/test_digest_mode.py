"""Hourly digest posting helpers (CHANNEL_POSTING_MODE=digest)."""
from unittest.mock import MagicMock

import main as main_mod
from summarize import merge_digest_bullets


def test_split_telegram_digest_splits_when_over_limit():
    header = main_mod._digest_header()
    bullets = ["שורה קצרה אחת באורך סביר בחדשות."] * 40
    chunks = main_mod.split_telegram_digest(header, bullets, max_chars=900)
    assert len(chunks) >= 2
    assert all(len(c) <= 1100 for c in chunks)  # loose bound (Hebrew width)
    assert "•" in chunks[0]


def test_merge_digest_bullets_single_skips_api():
    client = MagicMock()
    out = merge_digest_bullets(client, [{"title": "t", "hebrew": "אחת שורה."}])
    assert out == ["אחת שורה."]
    client.chat.completions.create.assert_not_called()


def test_merge_digest_bullets_fallback_on_empty_parse(monkeypatch):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=""))]
    client.chat.completions.create.return_value = resp
    items = [
        {"title": "a", "hebrew": "ראשונה."},
        {"title": "b", "hebrew": "שנייה."},
    ]
    out = merge_digest_bullets(client, items)
    assert out == ["ראשונה.", "שנייה."]


def test_filter_digest_window(monkeypatch):
    from datetime import datetime, timedelta, timezone

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=60)
    inside = {
        "id": "1",
        "sort_key": start + timedelta(minutes=30),
    }
    outside = {
        "id": "2",
        "sort_key": start - timedelta(hours=2),
    }

    def fake_window():
        return start, end

    monkeypatch.setattr(main_mod, "_digest_time_window_utc", fake_window)
    out = main_mod._filter_articles_digest_window([inside, outside])
    assert len(out) == 1 and out[0]["id"] == "1"
