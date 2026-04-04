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


def test_de_reiche_fuel_welt_bild_hebrew_summaries_merge():
    """Reiche/CDU fuel & Tempolimit row; Hebrew uses different words for pump relief."""
    w = timedelta(hours=8)
    welt = _article(
        "TOPNEWS - WELT | 04.04.2026 05:39",
        "שרת הכלכלה קתרינה רייכה מה-CDU דחתה הצעות לסבסוד בנזין והגבלת מהירות בגרמניה. "
        "היא ציינה כי הפחתות במדינות שכנות לא הובילו להורדת מחירים. במקום זאת, היא מציעה להגביר את פיצוי "
        "הנסיעות ולהפחית את מס החשמל.",
        "welt-reiche",
    )
    bild = _article(
        "BILD - Home | 04.04.2026 15:11",
        "שר הכלכלה קתרינה רייכה (CDU) מתנגדת להקלות מס בתחנות הדלק ומעדיפה להגדיל את הקצבת הנסיעות "
        "ולהפחית את מס החשמל. שר האוצר לארס קלינגבייל (SPD) דורש מס רווחי יתר על רמה אירופית.",
        "bild-reiche",
    )
    dup, detail = _is_near_duplicate(welt, bild, w)
    assert dup is True
    assert "topic-tag" in detail
    assert "de_reiche_fuel_policy" in detail


def test_baltic_whale_spiegel_bild_hebrew_summaries_merge():
    """Same stranding beat: Hebrew uses different species wording; shared tag + Wismar."""
    w = timedelta(hours=8)
    spiegel = _article(
        "DER SPIEGEL - Schlagzeilen | 04.04.2026 14:06",
        "לוויתן גדול סנפיר נתקע ליד Wismar ושרד לילה נוסף במים הרדודים מול אי Poel. "
        "המומחים מתכננים לבדוק את מצבו לאחר חג הפסחא. מומחי הסביבה משמרים את בריאותו.",
        "spiegel-wal",
    )
    bild = _article(
        "BILD - Home | 04.04.2026 11:33",
        "בעיר Wismar שבגרמניה מתמודדים עם מצב רגיש של לוויתן גבנוני אירופי בשם טימי שנסחף לחוף. "
        "אמצעים כמו מערכות הרטבה נוספות הופעלו כדי להקל על סבלו.",
        "bild-wal",
    )
    dup, detail = _is_near_duplicate(spiegel, bild, w)
    assert dup is True
    assert "topic-tag" in detail
    assert "baltic_whale_stranding" in detail
