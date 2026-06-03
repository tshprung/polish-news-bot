"""Reject Stage 2 output that echoes Polish prose with only a Hebrew prefix."""

from unittest.mock import MagicMock

from summarize import (
    _HEBREW_RETRY_SENTINEL,
    _postprocess_hebrew_summary,
    non_hebrew_prose_leak_reason,
    summarize_in_hebrew,
)


def test_polish_prose_with_hebrew_prefix_is_leak():
    bad = (
        "פולין wstrzymał natychmiast obrót kroplami do oczu Travoprost Timolol Medical Valley, "
        "nr pozwolenia 26262, we wszystkich seriach. Powodem są negatywne badania "
        "Narodowego Instytutu Leków i OMCL: szczelność butelki oraz zanieczyszczenia związane z travoprostem."
    )
    reason = non_hebrew_prose_leak_reason(bad)
    assert reason is not None
    assert "mostly non-Hebrew" in reason or "Polish" in reason or "too few Hebrew letters" in reason


def test_real_hebrew_summary_with_latin_brands_passes():
    good = (
        "פולין הודיעה על עצירת מיידית של מכירת Travoprost Timolol Medical Valley בכל האצוות "
        "לאחר שבדיקות של NIL מצאו ליקויי אטימות וזיהום."
    )
    assert non_hebrew_prose_leak_reason(good) is None


def test_postprocess_rejects_polish_echo():
    bad = "פולין wstrzymał natychmiast obrót kroplami do oczu w seriach z powodu badań jakości."
    out, err = _postprocess_hebrew_summary(bad, "Polska GIF krople")
    assert out is not None
    assert err == _HEBREW_RETRY_SENTINEL


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


def test_polish_echo_retries_then_accepts_hebrew(monkeypatch):
    body = (
        "GIF wstrzymał natychmiast obrót kroplami Travoprost Timolol Medical Valley we wszystkich seriach. "
        "Powodem są negatywne badania NIL."
    )
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: body)
    article = {
        "link": "https://www.polsatnews.pl/wiadomosc/2026-06-02/krople-do-oczu-pod-lupa/",
        "title": "Krople do oczu pod lupą. GIF nie spełniają wymagań jakościowych",
        "summary": "",
    }
    bad = (
        "פולין wstrzymał natychmiast obrót kroplami do oczu Travoprost Timolol Medical Valley, "
        "we wszystkich seriach z powodu negatywnych badań."
    )
    good = (
        "פולין עצרה מיידית את מכירת Travoprost Timolol Medical Valley בכל האצוות "
        "לאחר שבדיקות של NIL מצאו ליקויי איכות."
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _Resp("GO"),
        _Resp(bad),
        _Resp(good),
    ]
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out == good
    assert client.chat.completions.create.call_count == 3


def test_polish_echo_retry_still_bad_is_skipped(monkeypatch):
    body = "GIF wstrzymał obrót kroplami Travoprost we wszystkich seriach."
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: body)
    article = {
        "link": "https://www.polsatnews.pl/wiadomosc/2026-06-02/krople/",
        "title": "Krople do oczu pod lupą",
        "summary": "",
    }
    bad = "פולין wstrzymał natychmiast obrót kroplami do oczu we wszystkich seriach z powodu badań."
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _Resp("GO"),
        _Resp(bad),
        _Resp(bad),
    ]
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason is not None and "non-Hebrew prose" in reason
