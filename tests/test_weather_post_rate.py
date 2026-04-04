"""At most one IMGW / holiday-weather post per WEATHER_POST_MIN_INTERVAL_SEC."""

import sqlite3

import database as db_mod
from config import RATE_LIMIT_KEY_WEATHER
from database import rate_limit_allowed, record_rate_limit_hit, weather_post_allowed
from dedup import article_is_pl_weather_forecast_beat


def _rate_conn():
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE channel_rate_limits ("
        "rate_key TEXT PRIMARY KEY, "
        "last_sent_epoch INTEGER NOT NULL)"
    )
    return c


def test_weather_post_rate_enforces_interval(monkeypatch):
    conn = _rate_conn()
    interval = 24 * 3600
    assert weather_post_allowed(conn, interval) is True
    monkeypatch.setattr(db_mod.time, "time", lambda: 1_000_000)
    record_rate_limit_hit(conn, RATE_LIMIT_KEY_WEATHER)
    monkeypatch.setattr(db_mod.time, "time", lambda: 1_000_000 + 6 * 3600)
    assert rate_limit_allowed(conn, RATE_LIMIT_KEY_WEATHER, interval) is False
    assert weather_post_allowed(conn, interval) is False
    monkeypatch.setattr(db_mod.time, "time", lambda: 1_000_000 + interval)
    assert weather_post_allowed(conn, interval) is True


def test_Hebrew_imgw_warning_is_weather_beat():
    article = {
        "title": "RSS Wiadomosci.gazeta.pl | 04.04.2026 15:16",
        "summary": (
            "המכון המטאורולוגי הפולני (IMGW) הוציא אזהרות לסערות ולהתקררות ניכרת באזורים "
            "הצפוניים של פולין בשל חג הפסחא. האזהרות תקפות עד השבת ב-4 באפריל. "
            "באזורים מסויימים, הרוח עשויה להגיע למהירות של עד 75 קמ\"ש."
        ),
    }
    assert article_is_pl_weather_forecast_beat(article) is True
