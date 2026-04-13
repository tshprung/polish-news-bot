"""Reject stage-2 Hebrew that only states 'no Poland tie' meta (should be SKIP, not posted)."""

from unittest.mock import MagicMock

from config import (
    hebrew_scope_meta_disclaimer_skip_reason,
    hebrew_summary_is_scope_meta_disclaimer,
)
from summarize import summarize_in_hebrew
from tests.test_summarize_stage2 import _client_with_responses


def test_detects_onet_style_disclaimer():
    s = "אין מעורבות פולנית ישירה במידע המסופק."
    assert hebrew_summary_is_scope_meta_disclaimer(s) is True


def test_normal_summary_not_flagged():
    s = (
        "משרד החוץ בוורשה הגיב להצהרות בבריסל ואמר כי פולין תומכת בהארכת הסנקציות על רוסיה."
    )
    assert hebrew_summary_is_scope_meta_disclaimer(s) is False


def test_skip_reason_prefix():
    assert "meta-disclaimer" in hebrew_scope_meta_disclaimer_skip_reason().lower()


def test_summarize_rejects_disclaimer(monkeypatch):
    monkeypatch.setattr(
        "summarize.fetch_article_body",
        lambda *_a, **_k: "Treść artykułu o wydarzeniach za granicą bez Polski.",
    )
    article = {
        "link": "https://wiadomosci.onet.pl/swiat/artykul/test-123",
        "title": "Świat: wydarzenie",
        "summary": "Skrót.",
    }
    bad = "אין מעורבות פולנית ישירה במידע המסופק."
    client = _client_with_responses("GO", bad)
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason and "meta-disclaimer" in reason.lower()
