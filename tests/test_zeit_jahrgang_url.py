"""Skip DIE ZEIT Jahrgang hub URLs (zeit.de/2026), not dated article paths."""

from config import is_zeit_jahrgang_index_url


def test_skips_year_hub_variants():
    assert is_zeit_jahrgang_index_url("https://www.zeit.de/2026")
    assert is_zeit_jahrgang_index_url("https://www.zeit.de/2026/")
    assert is_zeit_jahrgang_index_url("HTTP://WWW.ZEIT.DE/2026?x=1")
    assert is_zeit_jahrgang_index_url("http://zeit.de/2026/issue/foo")


def test_allows_news_date_slug_paths():
    assert not is_zeit_jahrgang_index_url("https://www.zeit.de/news/2026-04/03/foo")
    assert not is_zeit_jahrgang_index_url("")
    assert not is_zeit_jahrgang_index_url(None)
