"""Skip routine Polish max pump-price tables (benzyna 95/98, diesel caps)."""

from unittest.mock import MagicMock

from config import (
    fuel_price_churn_skip_reason,
    should_skip_fuel_price_churn_blob,
    should_skip_fuel_price_churn_teaser,
    skip_admin_notify_for_reason,
)
from summarize import summarize_in_hebrew


def test_rmf_max_fuel_price_slug_skipped():
    title = "Nowe maksymalne ceny paliw w Polsce. Kosmetyczna zmiana"
    link = (
        "https://www.rmf24.pl/ekonomia/news-nowe-maksymalne-ceny-paliw-w-polsce-"
        "kosmetyczna-zmiana,nId,8089101"
    )
    assert should_skip_fuel_price_churn_teaser(title, "", link) is True


def test_hebrew_fuel_cap_summary_skipped():
    hebrew = (
        "שר האנרגיה בפולין קבע שמחירי הדלק המרביים ב-4 ו-5 ביוני יהיו 5.94 זלוטי לליטר בנזין 95, "
        "6.52 לבנזין 98 ו-6.40 לסולר. המכירה מעל התקרה צפויה לקנס עד מיליון זלוטי, "
        "והפיקוח בידי Krajowa Administracja Skarbowa."
    )
    assert should_skip_fuel_price_churn_blob(hebrew) is True


def test_fuel_shortage_not_skipped():
    blob = "Niedobór paliw na stacjach po awarii rafinerii Orlen w Płocku."
    assert should_skip_fuel_price_churn_blob(blob) is False


def test_fuel_tax_bill_not_skipped():
    blob = "Sejm uchwalił nową ustawę podnoszącą akcyzę od benzyny i diesla."
    assert should_skip_fuel_price_churn_blob(blob) is False


def test_skip_reason_is_admin_notify_exempt():
    assert skip_admin_notify_for_reason(fuel_price_churn_skip_reason())


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


def test_fuel_price_skipped_before_llm(monkeypatch):
    calls = {"fetch": 0}

    def _fetch(*_a, **_k):
        calls["fetch"] += 1
        return "should not fetch"

    monkeypatch.setattr("summarize.fetch_article_body", _fetch)
    article = {
        "link": (
            "https://www.rmf24.pl/ekonomia/news-nowe-maksymalne-ceny-paliw-w-polsce-"
            "kosmetyczna-zmiana,nId,8089101"
        ),
        "title": "Nowe maksymalne ceny paliw w Polsce. Kosmetyczna zmiana",
        "summary": "",
    }
    client = MagicMock()
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason == fuel_price_churn_skip_reason()
    assert calls["fetch"] == 0
    assert client.chat.completions.create.call_count == 0
