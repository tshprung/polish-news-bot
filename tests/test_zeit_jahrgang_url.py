"""Skip DIE ZEIT Jahrgang hub URLs (zeit.de/2026), not dated article paths."""

from config import is_zeit_jahrgang_index_url, skip_admin_notify_for_article


def test_skips_year_hub_variants():
    assert is_zeit_jahrgang_index_url("https://www.zeit.de/2026")
    assert is_zeit_jahrgang_index_url("https://www.zeit.de/2026/")
    assert not is_zeit_jahrgang_index_url("HTTP://WWW.ZEIT.DE/2026?x=1")
    assert not is_zeit_jahrgang_index_url("http://zeit.de/2026/issue/foo")


def test_skips_feed_style_urls():
    assert not is_zeit_jahrgang_index_url("https://m.zeit.de/2026/ausgabe/1")
    assert not is_zeit_jahrgang_index_url("//www.zeit.de/2026/index")
    assert not is_zeit_jahrgang_index_url("zeit.de/2026/foo")
    assert not is_zeit_jahrgang_index_url("www.zeit.de/2026/")


def test_allows_news_date_slug_paths():
    assert not is_zeit_jahrgang_index_url("https://www.zeit.de/news/2026-04/03/foo")
    assert not is_zeit_jahrgang_index_url("")
    assert not is_zeit_jahrgang_index_url(None)


def test_no_admin_dm_for_zeit_hub_even_with_other_skip_reason():
    article = {"link": "https://www.zeit.de/2026/x", "title": "x"}
    assert skip_admin_notify_for_article(article, "body not accessible (paywall or blocked)")


def test_runtime_error_dm_still_for_normal_urls():
    article = {"link": "https://example.com/a", "title": "a"}
    assert not skip_admin_notify_for_article(article)
