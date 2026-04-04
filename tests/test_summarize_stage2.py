"""Stage 2 (Hebrew summary) retry ladder and skip reasons — OpenAI is mocked."""

from unittest.mock import MagicMock

from summarize import summarize_in_hebrew


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [_Choice(content, finish_reason)]


def _client_with_responses(*contents_and_reasons):
    """Each item is str or (str, finish_reason)."""
    seq = []
    for item in contents_and_reasons:
        if isinstance(item, tuple):
            seq.append(_Resp(item[0], item[1]))
        else:
            seq.append(_Resp(item))
    client = MagicMock()
    client.chat.completions.create.side_effect = seq
    return client


def test_insufficient_with_body_short_text_stops_after_two_stage2_attempts(monkeypatch):
    """Tier-2 long-body hint applies only when len(article blob) >= 1200."""
    monkeypatch.setattr(
        "summarize.fetch_article_body",
        lambda _session, _url, _to: "Krótki fragment. " * 3,
    )
    article = {
        "link": "https://wiadomosci.onet.pl/kraj/artykul/abc",
        "title": "Krótki tytuł",
        "summary": "",
    }
    client = _client_with_responses(
        "GO",
        "INSUFFICIENT",
        "INSUFFICIENT",
    )
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason == "insufficient content even with full article"
    assert client.chat.completions.create.call_count == 3


def test_insufficient_with_long_body_exhausts_third_hint_tier(monkeypatch):
    """With long text, model may receive standard hint then diplomacy/quote hint before final skip."""
    long_pl = ("Treść wywiadu z cytatami i nazwiskami. " * 80).strip()
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: long_pl)
    article = {
        "link": "https://wiadomosci.onet.pl/tylko-w-onecie/wywiad/x",
        "title": "Europie grożą zamachy — ostrzeżenie byłego szefa wywiadu",
        "summary": "",
    }
    blob_len = len(article["title"] + ". " + long_pl)
    assert blob_len >= 1200

    client = _client_with_responses(
        "GO",
        "INSUFFICIENT",
        "INSUFFICIENT",
        "INSUFFICIENT",
    )
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason == "insufficient content even with full article"
    assert client.chat.completions.create.call_count == 4


def test_insufficient_immediate_when_body_unreachable(monkeypatch):
    """No Stage 2 retries if we never got a body (model cannot be 'wrong' about thin HTML)."""
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: "")
    article = {
        "link": "https://wiadomosci.onet.pl/kraj/artykul/xyz",
        "title": "Tylko nagłówek z RSS",
        "summary": "Lead bez pełnej treści",
    }
    client = _client_with_responses(
        "GO",
        "INSUFFICIENT",
    )
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason == "body not accessible (paywall or blocked)"
    assert client.chat.completions.create.call_count == 2


def test_hebrew_summary_after_two_insufficient_retries(monkeypatch):
    """Regression: hints must not permanently block a summarizable long article."""
    long_pl = ("Konkretny opis wydarzeń z datami i cytatami. " * 80).strip()
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: long_pl)
    article = {
        "link": "https://wiadomosci.onet.pl/swiat/dyplomacja/y",
        "title": "Unia i NATO omawiają bezpieczeństwo wschodniej flanki",
        "summary": "",
    }
    he = "זהו סיכום בעברית שמספיק ארוך ומתאר את העיקרי מהכתבה בפולנית בלי לדלג על עובדות."
    client = _client_with_responses(
        "GO",
        "INSUFFICIENT",
        "INSUFFICIENT",
        he,
    )
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out is not None
    assert "סיכום" in out
    assert client.chat.completions.create.call_count == 4


def test_wp_poll_latin_only_then_hebrew_retry(monkeypatch):
    """Regression: Stage 2 sometimes returns English-only (sondaż / names); must retry with Hebrew note."""
    pl_body = (
        "Sondaż WP wykazał, że większość Polaków pozytywnie oceniła spotkanie "
        "Karola Nawrockiego z Viktorem Orbánem; metodologia badania w treści."
    )
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: pl_body)
    article = {
        "link": "https://wiadomosci.wp.pl/sondaz-wp-polacy-ocenili-spotkanie-nawrockiego-z-orbanem-7270877297015008a",
        "title": "Sondaż WP. Polacy ocenili spotkanie Nawrockiego z Orbánem",
        "summary": "",
    }
    latin_only = (
        "A WP survey found most Poles rated Karol Nawrocki's meeting with Viktor Orbán positively; "
        "methodology is described in the article body."
    )
    hebrew = (
        "סקר של WP מצא כי רוב הפולנים העריכו בחיוב את פגישת נברוקי עם אורבן; "
        "שיטת האיסוף מתוארת בגוף הכתבה."
    )
    client = _client_with_responses("GO", latin_only, hebrew)
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out is not None
    assert "סקר" in out or "נברוקי" in out
    assert client.chat.completions.create.call_count == 3


def test_warsaw_source_geo_mismatch_still_skips(monkeypatch):
    """Regression: extraction/summary fixes must not disable GEO guard for Warsaw-area noise."""
    body = (
        "Pożar przed kościołem na warszawskim Mokotowie; strażacy prowadzą akcję gaśniczą."
        * 15
    )
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: body)
    article = {
        "link": "https://wiadomosci.onet.pl/kraj/pozar/x",
        "title": "Pożar przy świątyni",
        "summary": "",
    }
    bad_he = "דיווח שגוי שמזכיר רק את תל אביב לגמרי בלי קשר לוורשה."
    client = _client_with_responses("GO", bad_he)
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason is not None and "GEO mismatch" in reason
