"""Skip Baltic whale/dolphin wires with no Poland hook (świat syndication)."""

from config import (
    baltic_marine_wildlife_no_poland_skip_reason,
    should_skip_baltic_marine_wildlife_without_poland_blob,
)


def test_gazeta_humbak_baltyk_without_poland_skipped():
    blob = """
Dramatyczne wieści ws. humbaka uwięzionego na Bałtyku
Nieudane próby ratowania wieloryba; zwierzę padło.
https://wiadomosci.gazeta.pl/swiat/7,198076,32713028,dramatyczne-wiesci-ws-humbaka-uwiezionego-na-baltyku-wieloryb.html
Niemieckie służby kończą akcję. Zwierzę było w odległości od wybrzeży Szwecji.
    """.strip()
    assert should_skip_baltic_marine_wildlife_without_poland_blob(blob) is True


def test_baltic_whale_with_gdynia_not_skipped():
    blob = """
Humbak uwięziony w Zatoce Gdańskiej
Polscy ratownicy z Gdyni prowadzą akcję na Bałtyku.
https://example.com/a
    """.strip()
    assert should_skip_baltic_marine_wildlife_without_poland_blob(blob) is False


def test_baltic_only_no_cetacean_not_skipped():
    blob = """
Zanieczyszczenie Bałtyku. Eksperci apelują.
Brak zwierząt w tytule.
    """.strip()
    assert should_skip_baltic_marine_wildlife_without_poland_blob(blob) is False


def test_skip_reason_prefix():
    assert baltic_marine_wildlife_no_poland_skip_reason().lower().startswith("rss teaser:")
