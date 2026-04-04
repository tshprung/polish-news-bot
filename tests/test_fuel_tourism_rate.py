"""DE–PL border fuel-tourism wires: at most one per FUEL_TOURISM_POST_MIN_INTERVAL_SEC."""

import sqlite3

import database as db_mod
from database import fuel_tourism_post_allowed, record_fuel_tourism_post
from dedup import article_is_de_pl_fuel_tourism_beat


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE channel_rate_limits ("
        "rate_key TEXT PRIMARY KEY, last_sent_epoch INTEGER NOT NULL)"
    )
    return c


def test_hebrew_polsat_fuel_tourism_is_beat():
    article = {
        "title": "Polsat News - Wiadomości | 04.04.2026 16:51",
        "summary": (
            "נהגים גרמנים מגיעים לתחנות דלק בפולין, בעיקר ב-Lubieszyn וסביב Szczecin, "
            "כדי לנצל את מחירי הדלק הנמוכים משמעותית. ההחלטה להפחית את המע\"מ על דלק תרמה לתופעת "
            'ה"תיירות דלק" ההולכת וגוברת בקרב תושבי גרמניה הסמוכים לגבול.'
        ),
    }
    assert article_is_de_pl_fuel_tourism_beat(article) is True


def test_polish_title_kierowcy_z_niemiec_is_beat():
    article = {
        "title": (
            "Turystyka paliwowa kwitnie. Nie ustają przygraniczne kolejki kierowców z Niemiec — Polsat"
        ),
        "summary": "Kolejki na stacjach paliw w Lubieszynie.",
    }
    assert article_is_de_pl_fuel_tourism_beat(article) is True


def test_rate_limits_second_post_within_24h(monkeypatch):
    conn = _conn()
    interval = 24 * 3600
    assert fuel_tourism_post_allowed(conn, interval) is True
    monkeypatch.setattr(db_mod.time, "time", lambda: 2_000_000)
    record_fuel_tourism_post(conn)
    monkeypatch.setattr(db_mod.time, "time", lambda: 2_000_000 + 3600)
    assert fuel_tourism_post_allowed(conn, interval) is False
    monkeypatch.setattr(db_mod.time, "time", lambda: 2_000_000 + interval)
    assert fuel_tourism_post_allowed(conn, interval) is True


def test_unrelated_german_tourists_not_beat():
    article = {
        "title": "Niemcy na wakacjach w Zakopanem",
        "summary": "Turyści z Niemiec wybierają góry i lokalną kuchnię.",
    }
    assert article_is_de_pl_fuel_tourism_beat(article) is False
