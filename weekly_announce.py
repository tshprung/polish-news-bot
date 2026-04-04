"""Weekly Hebrew community/support post (via channel in .env; cron ~Sunday 18:00 Jerusalem)."""
from __future__ import annotations

import html
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    WEEKLY_ANNOUNCE_ENABLED,
    WEEKLY_ANNOUNCE_HOUR,
    WEEKLY_ANNOUNCE_KOFI_URL,
    WEEKLY_ANNOUNCE_SUPPORT_EMAIL,
    WEEKLY_ANNOUNCE_TZ,
    WEEKLY_ANNOUNCE_WEEKDAY,
)
from database import init_db
from http_util import make_http_session, request_timeout
from telegram_bot import send_to_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def iso_week_key(now: datetime) -> str:
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def should_run(now: datetime, weekday: int, hour: int) -> bool:
    return now.weekday() == weekday and now.hour == hour


def build_weekly_announce_html() -> str:
    email = WEEKLY_ANNOUNCE_SUPPORT_EMAIL
    kofi = WEEKLY_ANNOUNCE_KOFI_URL
    email_esc = html.escape(email)
    kofi_href = html.escape(kofi, quote=True)
    lines = (
        "היי,",
        "",
        "אני טל שפרונג, ואני מפעיל את הערוץ הזה כתחביב כדי להנגיש חדשות מקומיות בעברית לדוברי עברית בחו״ל.",
        "",
        "המערכת רצה אוטומטית ומשתמשת ב-AI, ויש לזה גם עלויות.",
        "אם יש לכם פידבק או רעיונות לשיפור – אשמח לשמוע:",
        f'<a href="mailto:{email_esc}">{email_esc}</a>',
        "",
        "אם אתם נהנים מהערוץ ורוצים לעזור להמשיך ולהפעיל אותו, אפשר לתמוך כאן:",
        f'<a href="{kofi_href}">ko-fi.com/talshprung</a>',
        "",
        "התמיכה כמובן לא חובה אבל מאוד מוערכת 🙂",
    )
    return "\n".join(lines)


def _already_sent(conn: sqlite3.Connection, week_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM weekly_announce_sent WHERE iso_week = ?", (week_key,)
    ).fetchone()
    return row is not None


def _mark_sent(conn: sqlite3.Connection, week_key: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO weekly_announce_sent (iso_week) VALUES (?)", (week_key,)
    )
    conn.commit()


def main() -> None:
    if not WEEKLY_ANNOUNCE_ENABLED:
        log.info("Weekly announce disabled")
        return

    tz = ZoneInfo(WEEKLY_ANNOUNCE_TZ)
    now = datetime.now(tz)
    if not should_run(now, WEEKLY_ANNOUNCE_WEEKDAY, WEEKLY_ANNOUNCE_HOUR):
        return

    week_key = iso_week_key(now)
    conn = init_db()
    try:
        if _already_sent(conn, week_key):
            log.info("Weekly announce already sent for %s", week_key)
            return
        session = make_http_session()
        to = request_timeout()
        send_to_telegram(session, build_weekly_announce_html(), timeout=to)
        _mark_sent(conn, week_key)
        log.info("Weekly announce sent for %s", week_key)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
