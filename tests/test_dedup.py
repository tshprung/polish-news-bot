"""Conservative copy matching preserves updates for semantic novelty checking."""
import sqlite3
import time
from dedup import _is_near_duplicate, deduplicate, save_dedup_snapshot, load_dedup_snapshots

def connection():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE dedup_recent (article_id TEXT PRIMARY KEY, title TEXT, summary TEXT, sort_epoch INTEGER)")
    return conn

def test_identical_copy_collapses_across_ids():
    a = {"id": "a", "title": "Sejm przyjął ustawę", "summary": "Nowe zasady od maja"}
    b = dict(a, id="b")
    assert deduplicate(connection(), [a, b]) == [a]

def test_shared_words_do_not_hide_reversal():
    a = {"title": "Tunel kolejowy inwestycja budowa finansowanie termin", "summary": "Projekt zatwierdzony"}
    b = dict(a, summary="Projekt anulowany")
    assert not _is_near_duplicate(a, b)[0]

def test_history_spans_days_but_expires():
    conn = connection()
    epoch = int(time.time())
    save_dedup_snapshot(conn, "yesterday", "Headline", "Facts", epoch - 48*3600)
    save_dedup_snapshot(conn, "old", "Other", "", epoch - 8*24*3600)
    assert [x["id"] for x in load_dedup_snapshots(conn, 7*24)] == ["yesterday"]
    assert not deduplicate(conn, [{"id": "new", "title": "Headline", "summary": "Facts"}])
