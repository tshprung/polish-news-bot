"""Skip public-opinion polls / 'what Poles think' + percentages."""
from config import (
    public_opinion_poll_skip_reason,
    should_skip_public_opinion_poll_teaser,
    skip_admin_notify_for_reason,
)


def test_sondaz_in_title_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "SONDAŻ: PiS traci, KO rośnie. Kto zyskał najwięcej?",
        "Najnowsze badanie przed wyborami.",
    )


def test_cbos_with_proc_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "CBOS o nastrojach",
        "45 proc. Polaków źle ocenia pracę rządu — wynika z badania.",
    )


def test_cbos_decimal_and_hungary_angle_skipped():
    """CBOS + multi-sentence lede before % (Hungary / EU angle); decimals like 41,0 proc."""
    filler = "Lorem ipsum dolor sit amet. " * 25
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości z kraju i ze świata - wszystko co ważne - WP",
        filler
        + "CBOS zapytał Polaków o wybory na Węgrzech. "
        + "41,0 proc. respondentów uważa, że będą korzystne dla Polski.",
    )


def test_decimal_comma_wp_poll_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "KO i PiS. Podział mandatów",
        "31,8 proc. dla KO, 24,5 proc. dla PiS; KO z 192 mandatami w Sejmie.",
    )


def test_wp_sondaz_slug_in_link_skipped_when_title_generic():
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości z kraju i ze świata - wszystko co ważne - WP",
        "Krótki lead bez słowa sondaż.",
        "https://wiadomosci.wp.pl/sondaz-wybory-ko-pis-mandaty-7270877297015008a",
    )


def test_wp_polacy_zabrali_glos_slug_skipped_when_title_generic():
    """WP reader-poll slugs use polacy-zabrali-glos without 'sondaż' in the RSS title."""
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości z kraju i ze świata - wszystko co ważne - WP",
        "",
        "https://wiadomosci.wp.pl/co-jesli-putin-wezmie-udzial-w-szczycie-g20-polacy-zabrali-glos-7280874411100224a",
    )


def test_united_surveys_hyphenated_name_with_percent_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "G20 i Rosja",
        "United-surveys dla WP: tylko 33,9 proc. za bojkotem szczytu.",
        "",
    )


def test_gazeta_zapytalismy_o_slug_skipped_without_sondaz_or_percent_in_teaser():
    """Gazeta reader poll URLs use zapytalismy-o-… slugs; RSS title is often generic."""
    assert should_skip_public_opinion_poll_teaser(
        "RSS Wiadomosci.gazeta.pl",
        "",
        "https://wiadomosci.gazeta.pl/polska/7,198072,32761493,zapytalismy-o-finansowanie-partii-przez-sympatykow-jedna-odpowiedz.html?utm_source=RSS",
    )


def test_zapytalismy_lede_with_decimal_shares_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Finansowanie partii przez sympatyków",
        "Zapytaliśmy o zdanie. 81,49 proc. było przeciw, 10,72 proc. za, a 5,97 proc. częściowo za.",
        "",
    )


def test_sondaz_then_mandaty_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Sondaż WP. Sejm po wyborach",
        "Symulacja: KO 192 mandaty, PiS 143 mandaty w Sejmie.",
    )


def test_ankieta_polacy_percent_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Ankieta wśród mieszkańców",
        "Co sądzą o zmianach? 62 proc. jest przeciwnych.",
    )


def test_gdyby_wybory_without_sondaz_in_title_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Koalicja Obywatelska na czele. PiS traci",
        "Gdyby wybory odbyły się w niedzielę, KO miałoby 32 proc. poparcia.",
    )


def test_przebadano_sample_size_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Notowania partii politycznych",
        "Przebadano 1068 osób uprawnionych do głosowania.",
    )


def test_symulacja_wyborcza_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Rozkład mandatów",
        "Symulacja wyborcza wskazuje na zmiany w klubach.",
    )


def test_normal_law_news_not_skipped():
    assert not should_skip_public_opinion_poll_teaser(
        "Sejm uchwalił nowelizację ustawy o obronie",
        "Zmiany dotyczą zasad powoływania żołnierzy rezerwy.",
    )


def test_skip_reason_is_rss_teaser_exempt():
    assert public_opinion_poll_skip_reason().lower().startswith("rss teaser:")
    assert skip_admin_notify_for_reason(public_opinion_poll_skip_reason())
