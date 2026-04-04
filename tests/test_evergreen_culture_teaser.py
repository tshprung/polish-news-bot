"""Skip ZEIT-style anthem / podcast history with no news decision in teaser."""

from unittest.mock import MagicMock

from config import evergreen_culture_skip_reason, should_skip_evergreen_culture_teaser
from summarize import summarize_in_hebrew


def test_zeit_german_anthem_hebrew_summary_skipped():
    title = "DIE ZEIT | Nachrichten, News, Hintergründe und Debatten | 04.04.2026 15:46"
    summary = (
        "הממלכה הגרמנית חששה מחילוקי דעות על ההמנון הלאומי, תוך שהיסטוריית הלחץ סביבו נבחנת. "
        "לאחר איחוד גרמניה, המחלוקות המשיכו להתקיים סביב קסמי המוזיקה והמסרים של המנון זה."
    )
    link = (
        "https://www.zeit.de/wissen/2026-04/deutsche-nationalhymne-lied-der-deutschen-geschichte-podcast"
    )
    assert should_skip_evergreen_culture_teaser(title, summary, link) is True


def test_anthem_with_bundestag_decision_not_skipped():
    text = (
        "Der Bundestag beschloss heute eine neue Regelung zum Deutschlandlied; "
        "die Abstimmung fiel klar aus."
    )
    assert should_skip_evergreen_culture_teaser("Titel", text, "") is False


def test_skip_reason_uses_exempt_prefix():
    assert evergreen_culture_skip_reason().lower().startswith("rss teaser:")


def test_summarize_early_exit_no_fetch(monkeypatch):
    monkeypatch.setattr(
        "summarize.fetch_article_body",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no fetch")),
    )
    article = {
        "link": "https://www.zeit.de/wissen/2026-04/deutsche-nationalhymne-geschichte-podcast",
        "title": "ZEIT",
        "summary": "המנון לאומי, מחלוקות היסטוריות סביב מילותיו ומנגינתו לאחר האיחוד.",
    }
    out, reason = summarize_in_hebrew(MagicMock(), MagicMock(), (1, 2), article)
    assert out is None
    assert reason and "evergreen" in reason
