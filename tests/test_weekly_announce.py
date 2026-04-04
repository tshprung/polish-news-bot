"""Weekly announce helpers (no Telegram calls)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import weekly_announce as wa


def test_iso_week_key_matches_isocalendar():
    dt = datetime(2026, 4, 5, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    y, w, _ = dt.isocalendar()
    assert wa.iso_week_key(dt) == f"{y}-W{w:02d}"
    assert dt.weekday() == 6


def test_should_run_weekday_and_hour():
    tz = ZoneInfo("Asia/Jerusalem")
    sunday_18 = datetime(2026, 4, 5, 18, 0, tzinfo=tz)
    monday_18 = datetime(2026, 4, 6, 18, 0, tzinfo=tz)
    sunday_17 = datetime(2026, 4, 5, 17, 0, tzinfo=tz)
    assert wa.should_run(sunday_18, 6, 18) is True
    assert wa.should_run(monday_18, 6, 18) is False
    assert wa.should_run(sunday_17, 6, 18) is False


def test_build_weekly_announce_html_has_links():
    html_msg = wa.build_weekly_announce_html()
    assert "tshprung@gmail.com" in html_msg
    assert "ko-fi.com" in html_msg
    assert "<a href=" in html_msg
