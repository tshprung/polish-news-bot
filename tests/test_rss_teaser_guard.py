"""RSS teaser substance: skip profile/interview fluff before fetch/LLM."""

from unittest.mock import MagicMock

from config import (
    should_skip_information_poor_rss_teaser,
    skip_admin_notify_for_reason,
)
from summarize import summarize_in_hebrew


def test_skips_hebrew_oncologist_profile_teaser():
    title = "TOPNEWS - WELT"
    summary = (
        "האונקולוג Thomas Fischer מסכם כמעט 40 שנות עבודה, ומסביר מדוע יש שמדחיקים את נושא הסרטן. "
        "הוא מדבר על השיפורים המשמעותיים בטיפולים, ומציע עצות לחיים בריאים המבוססות על ניסיונו."
    )
    assert should_skip_information_poor_rss_teaser(title, summary)


def test_skips_german_interview_teaser():
    title = "Krebs: Es reicht nicht, Menschen mit 50 zu sagen, sie sollten vernünftig leben"
    summary = (
        "Der Onkologe fasst fast 40 Jahre Erfahrung zusammen und erklärt, warum viele das Thema vermeiden. "
        "Er spricht über bedeutende Fortschritte in der Therapie und gibt Tipps für einen gesunden Lebensstil."
    )
    assert should_skip_information_poor_rss_teaser(title, summary)


def test_allows_news_with_stats_or_crash():
    assert not should_skip_information_poor_rss_teaser(
        "Inflacja",
        "GUS podał, że w marcu inflacja wyniosła 3,2 proc. w ujęciu rocznym; analitycy spodziewali się 3,0 proc.",
    )
    assert not should_skip_information_poor_rss_teaser(
        "Wypadek na A4",
        "12 osób zostało rannych po zderzeniu trzech aut na autostradzie koło Katowic; droga była zablokowana.",
    )


def test_allows_short_teaser_even_if_soft_words():
    """Below length threshold we do not pre-filter (headline-only wires)."""
    assert not should_skip_information_poor_rss_teaser(
        "Wywiad",
        "Krótki lead.",
    )


def test_summarize_returns_early_without_openai_calls(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("fetch should not run")

    monkeypatch.setattr("summarize.fetch_article_body", boom)

    article = {
        "link": "https://www.welt.de/gesundheit/plus/article.html",
        "title": "Gesundheit Plus",
        "summary": (
            "Onkologe Thomas Fischer blickt zurück und gibt Tipps zum gesunden Leben — "
            "über Therapie und Vorsorge ohne konkrete Studienzahlen im Teaser."
        ),
    }
    client = MagicMock()
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason and skip_admin_notify_for_reason(reason)
    client.chat.completions.create.assert_not_called()
