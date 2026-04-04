"""BILD Unterhaltung / MayWay-style guest listings — no OpenAI."""

from config import (
    entertainment_chat_skip_reason,
    should_skip_entertainment_politician_chat_teaser,
)


def test_bild_mayway_spahn_hebrew_teaser_skipped():
    title = "BILD - Home | 04.04.2026 20:01"
    summary = (
        "תוכנית של BILD עם טניה מאיי אירחה את יו\"ר סיעת CDUCSU בבונדסטאג, Jens Spahn."
    )
    link = "https://www.bild.de/unterhaltung/mayway-mit-jens-spahn-ich-hab-kein-twitter-69b93109e371598814461946"
    assert should_skip_entertainment_politician_chat_teaser(title, summary, link) is True


def test_bild_unterhaltung_not_skipped_when_decision_in_teaser():
    title = "BILD Unterhaltung"
    summary = (
        "Der Bundestag beschloss heute mit klarer Mehrheit eine Novelle; "
        "Gast im Studio war Jens Spahn."
    )
    link = "https://www.bild.de/unterhaltung/mayway-talk-123"
    assert should_skip_entertainment_politician_chat_teaser(title, summary, link) is False


def test_non_bild_not_skipped():
    assert (
        should_skip_entertainment_politician_chat_teaser(
            "X", "תוכנית אירחה פוליטיקאי", "https://example.org/show",
        )
        is False
    )


def test_skip_reason_exempt():
    assert entertainment_chat_skip_reason().lower().startswith("rss teaser:")
