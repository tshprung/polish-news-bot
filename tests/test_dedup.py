"""Regression tests for near-duplicate logic and cross-run snapshots."""
import sqlite3
from datetime import datetime, timedelta, timezone

from dedup import (
    _is_near_duplicate,
    content_tokens,
    deduplicate,
    load_dedup_snapshots,
    record_sent_snapshot,
)


def _article(title, summary, aid, sort=None):
    if sort is None:
        sort = datetime.now(timezone.utc)
    return {
        "id": aid,
        "title": title,
        "summary": summary or "",
        "link": f"https://ex/{aid}",
        "source": "Test",
        "date": "",
        "sort_key": sort,
    }


def _memory_conn():
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE seen_articles (id TEXT PRIMARY KEY, "
        "sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    c.execute(
        "CREATE TABLE dedup_recent ("
        "article_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
        "summary TEXT NOT NULL, sort_epoch INTEGER NOT NULL)"
    )
    return c


def test_szczucki_cluster_merges():
    w = timedelta(hours=8)
    a = _article(
        "Poseł PiS zawieszony. Podlizuje się tamtej stronie?",
        "Kaczyński zawiesił Krzysztofa Szczuckiego w prawach członka party.",
        "1",
    )
    b = _article(
        "Zawieszony poseł PiS odpowiada na zarzuty i spekulacje",
        "Szczucki odrzuca zarzuty o współpracę z koalicją i kontakty z Żurkiem.",
        "2",
    )
    dup, _ = _is_near_duplicate(a, b, w)
    assert dup is True


def test_topic_tag_requires_lexical_overlap():
    """Shared #cluster alone must not merge (guards unrelated same-hour flukes)."""
    w = timedelta(hours=8)
    a = _article('Alternatywa dla NATO. General widzialby Polske', "Keith Kellogg", "n1")
    b = _article("GDP report", "NATO wspomniane przelotnie bez Polski", "n2")
    ca, cb = content_tokens(a), content_tokens(b)
    topic_shared = ca & cb & {"#nato_us_poland"}
    assert not topic_shared or len((ca & cb) - {"#nato_us_poland"}) < 2
    dup, _ = _is_near_duplicate(a, b, w)
    assert dup is False


def test_tram_lodz_still_merges_with_topic_and_lexical():
    w = timedelta(hours=8)
    a = _article(
        "Poważny wypadek tramwajowy w centrum Łodzi. Są ranni",
        "Opis skrócony.",
        "t1",
    )
    b = _article(
        "Wykolejenie tramwaju w Łodzi. Są ranni i utrudnienia",
        "Utrudnienia.",
        "t2",
    )
    dup, detail = _is_near_duplicate(a, b, w)
    assert dup is True
    assert "topic-tag" in detail or "dice" in detail or "j=" in detail


def test_weather_storm_vs_cold_not_duplicate():
    """Different beats (Easter storms vs wind warning): same tag but no lexical overlap → keep both."""
    w = timedelta(hours=8)
    wx = _article("Grzmoty na Wielkanoc", "Warunki", "w1")
    storm = _article("Wichura nad Polską", "90 km/h wiatr", "w2")
    dup, _ = _is_near_duplicate(wx, storm, w)
    assert dup is False


def test_weather_imgw_holiday_wires_merge():
    w = timedelta(hours=8)
    a = _article(
        "IMGW ostrzega przed przymrozkami",
        "Alerty dla województw temperatura spadnie",
        "wx1",
    )
    b = _article(
        "Burze na Wielkanoc",
        "Warunki w weekend prognoza IMGW",
        "wx2",
    )
    dup, detail = _is_near_duplicate(a, b, w)
    assert dup is True
    assert "topic-tag" in detail
    assert "#pl_weather_forecast" in detail


def test_cross_run_dedup_uses_snapshot():
    conn = _memory_conn()
    now = datetime.now(timezone.utc)
    prior = _article(
        "Wykolejenie tramwaju w Łodzi",
        "Ranni.",
        "sent-earlier",
        sort=now - timedelta(minutes=30),
    )
    record_sent_snapshot(conn, prior)
    conn.commit()

    incoming = _article(
        "Tramwaj wypadek Łódź ranni",
        "Inne podsumowanie RSS.",
        "new-id",
        sort=now,
    )
    kept = deduplicate(conn, [incoming])
    assert kept == []
    row = conn.execute("SELECT 1 FROM seen_articles WHERE id=?", (incoming["id"],)).fetchone()
    assert row is not None


def test_same_batch_first_wins_second_dropped():
    conn = _memory_conn()
    now = datetime.now(timezone.utc)
    a = _article("A headline shared tokens", "Summary alpha beta gamma", "id-a", sort=now)
    b = _article("B headline shared tokens", "Summary alpha beta delta", "id-b", sort=now)
    kept = deduplicate(conn, [a, b])
    assert len(kept) == 1
    assert kept[0]["id"] == "id-a"


def test_load_dedup_snapshots_respects_window():
    conn = _memory_conn()
    old = int((datetime.now(timezone.utc) - timedelta(hours=20)).timestamp())
    conn.execute(
        "INSERT INTO dedup_recent (article_id, title, summary, sort_epoch) VALUES (?,?,?,?)",
        ("old", "t", "s", old),
    )
    conn.commit()
    from config import DEDUP_WINDOW_HOURS

    rows = load_dedup_snapshots(conn, DEDUP_WINDOW_HOURS)
    ids = {r["id"] for r in rows}
    assert "old" not in ids
