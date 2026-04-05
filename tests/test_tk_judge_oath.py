"""Constitutional Tribunal judge-oath beat: topic dedup and 7d default rate limit."""

import sqlite3
from datetime import timedelta

import database as db_mod
from dedup import (
    _is_near_duplicate,
    article_is_pl_tk_judge_oath_beat,
)
from database import record_tk_judge_oath_post, tk_judge_oath_post_allowed


def test_onet_hebrew_summary_and_slug_gets_beat():
    article = {
        "title": "Wiadomości wiadomosci.onet.pl | 04.04.2026 18:10",
        "summary": (
            "נשיא פולין קיבל את שבועתם של שניים מתוך שישה שופטים שנבחרו לבית המשפט החוקתי, "
            "בעוד המינויים של ארבעת האחרים נותרו בעין הסערה."
        ),
        "link": (
            "https://wiadomosci.onet.pl/nawrocki-mebluje-trybunal-morawiecki-spiskuje"
            "-tusk-ma-oko-na-kosiniaka/lhdxwqj"
        ),
    }
    assert article_is_pl_tk_judge_oath_beat(article) is True


def test_hebrew_summary_merges_polish_title_in_dedup_window():
    a = {
        "id": "1",
        "title": "Nawrocki zaprzysięża sędziów TK",
        "summary": "Komunikat",
        "link": "",
        "sort_key": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    }
    b = {
        "id": "2",
        "title": "Inny naglowek",
        "summary": (
            "נשיא פולין השביע שני שופטים לבית המשפט החוקתי מתוך שישה. "
            "שאר המינויים במחלוקת."
        ),
        "link": "https://example.org/x",
        "sort_key": a["sort_key"],
    }
    dup, detail = _is_near_duplicate(a, b, timedelta(hours=8))
    assert dup is True
    assert "pl_tk_judge_oath_row" in detail


def test_rate_limit_second_post_within_interval(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE channel_rate_limits ("
        "rate_key TEXT PRIMARY KEY, last_sent_epoch INTEGER NOT NULL)"
    )
    interval = 7 * 24 * 3600
    assert tk_judge_oath_post_allowed(conn, interval) is True
    monkeypatch.setattr(db_mod.time, "time", lambda: 5_000_000)
    record_tk_judge_oath_post(conn)
    monkeypatch.setattr(db_mod.time, "time", lambda: 5_000_000 + 3 * 3600)
    assert tk_judge_oath_post_allowed(conn, interval) is False
