"""Regression: UTF-8 HTML without charset must not decode as Latin-1."""
import requests

from article_fetch import _html_text
from summarize import _sanitize_hebrew_summary_line


def test_html_text_prefers_utf8_when_requests_default_is_latin1():
    raw = "<p>Dariusz Matecki — widać mężczyznę</p>".encode("utf-8")
    r = requests.Response()
    r.status_code = 200
    r._content = raw
    r.headers = {"Content-Type": "text/html"}  # no charset → requests often uses ISO-8859-1
    r.encoding = "iso-8859-1"
    text = _html_text(r)
    assert "Matecki" in text
    assert "mężczyznę" in text
    assert "─¥" not in text  # would appear in mojibake


def test_html_numeric_entities_not_turned_into_spurious_34():
    s = "מועצת תורינגיה &#34;שלום ודיפלומטיה&#34; בשלב הבא."
    out = _sanitize_hebrew_summary_line(s)
    assert "34;" not in out
    assert "דיפלומטיה34" not in out
    assert "שלום" in out
