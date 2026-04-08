"""Skip evergreen Baltic whale ‘human history’ wires (ZEIT-style), not live strandings."""

from unittest.mock import MagicMock

from config import (
    baltic_wildlife_history_skip_reason,
    should_skip_baltic_wildlife_history_teaser,
)
from summarize import summarize_in_hebrew


def test_zeit_ostsee_wale_jahrhundert_slug_skipped():
    title = "DIE ZEIT | Nachrichten, News, Hintergründe und Debatten | 08.04.2026 05:30"
    summary = (
        "Im Norden waren Wale schon vor Jahrhunderten in Kirchenkunst und Alltag präsent — "
        "ein Essay über Menschen und Meeressäuger."
    )
    link = (
        "https://www.zeit.de/news/2026-04/08/"
        "ostsee-wale-bewegten-schon-vor-jahrhunderten-die-menschen"
    )
    assert should_skip_baltic_wildlife_history_teaser(title, summary, link) is True


def test_stranding_teaser_not_skipped_even_near_baltic():
    title = "Notfall an der Ostsee"
    summary = "Ein Wal ist bei Wismar gestrandet; Rettungskräfte sind im Einsatz."
    link = "https://example.com/news/wal-wismar"
    assert should_skip_baltic_wildlife_history_teaser(title, summary, link) is False


def test_teaser_history_framing_skipped_without_url_slug():
    title = "ZEIT"
    summary = (
        "In Greifswald, essay on how whales shaped public life for centuries — "
        "church art to early science."
    )
    assert should_skip_baltic_wildlife_history_teaser(title, summary, "") is True


def test_skip_reason_teaser_prefix():
    assert baltic_wildlife_history_skip_reason().lower().startswith("rss teaser:")


def test_summarize_early_exit_no_fetch(monkeypatch):
    monkeypatch.setattr(
        "summarize.fetch_article_body",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no fetch")),
    )
    article = {
        "link": (
            "https://www.zeit.de/news/2026-04/08/"
            "ostsee-wale-bewegten-schon-vor-jahrhunderten-die-menschen"
        ),
        "title": "DIE ZEIT | Nachrichten | 08.04.2026 05:30",
        "summary": "Kurzer Vorspann ohne Eilmeldung.",
    }
    out, reason = summarize_in_hebrew(MagicMock(), MagicMock(), (1, 2), article)
    assert out is None
    assert reason and "wildlife history" in reason
