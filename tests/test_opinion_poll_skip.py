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


def test_wp_nowy_sondaz_slug_skipped_with_generic_rss_title():
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości z kraju i ze świata - wszystko co ważne - WP",
        "",
        "https://wiadomosci.wp.pl/tak-polacy-oceniaja-tuska-nowy-sondaz-mowi-wszystko-7282218236745792a",
    )

def test_onet_nowy_sondaz_partyjny_opinia24_slug_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości wiadomosci.onet.pl",
        "",
        "https://wiadomosci.onet.pl/kraj/nowy-sondaz-partyjny-oto-rozklad-sil-w-sejmie-tusk-bez-szans-na-wiekszosc/t1jv0ez",
    )


def test_onet_polacy_zabrali_glos_trump_us_troops_slug_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości wiadomosci.onet.pl",
        "",
        "https://wiadomosci.onet.pl/kraj/donald-trump-moze-wycofac-zolnierzy-usa-z-naszego-kraju-polacy-zabrali-glos/31kv19p",
    )


def test_onet_wyborach_sondaz_ko_lewica_slug_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości wiadomosci.onet.pl",
        "",
        "https://wiadomosci.onet.pl/kraj/wspolna-lista-ko-i-lewicy-w-wyborach-sondaz-daje-wskazowke-tuskowi-i-czarzastemu/v2w1vbs",
    )


def test_sw_research_hyphen_for_onet_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości wiadomosci.onet.pl",
        "SW-Research dla Onet: 40,7 proc. Polaków uważa, że Trump może wycofać część wojsk.",
        "",
    )


def test_ogb_ogolnopolska_grupa_badawcza_with_percents_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Rząd w oczach Polaków",
        "Badanie Ogólnopolskiej Grupy Badawczej: 51,1 proc. negatywnie, 29,4 proc. pozytywnie.",
        "",
    )


def test_sample_size_prob_osob_with_percents_skipped():
    assert should_skip_public_opinion_poll_teaser(
        "Rząd. Podsumowanie",
        "Wyniki: 40 proc. za. Na próbie 1000 osób w kwietniu 2026.",
        "",
    )


def test_gazeta_zapytalismy_o_slug_skipped_without_sondaz_or_percent_in_teaser():
    """Gazeta reader poll URLs use zapytalismy-o-… slugs; RSS title is often generic."""
    assert should_skip_public_opinion_poll_teaser(
        "RSS Wiadomosci.gazeta.pl",
        "",
        "https://wiadomosci.gazeta.pl/polska/7,198072,32761493,zapytalismy-o-finansowanie-partii-przez-sympatykow-jedna-odpowiedz.html?utm_source=RSS",
    )


def test_gazeta_zapytalismy_europoslow_immunitety_url_skipped():
    """Eurodeputy immunity reader poll; slug ends with tak-oceniono.html."""
    assert should_skip_public_opinion_poll_teaser(
        "RSS Wiadomosci.gazeta.pl",
        "",
        "https://wiadomosci.gazeta.pl/polska/7,198072,32767377,zapytalismy-o-europoslow-po-uchyleniu-immunitetow-tak-oceniono.html?utm_source=RSS",
    )


def test_zapytalismy_czytelnikow_teaser_skipped_without_percent_in_rss():
    assert should_skip_public_opinion_poll_teaser(
        "Wiadomości",
        "Zapytaliśmy czytelników, jak oceniają pracę europosłów. Byli surowi.",
        "",
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


def test_opinia24_user_example():
    title = "Wspólny start KO i Lewicy? Wiadomo, kto na tym najwięcej skorzysta"
    summary = (
        "Polska scena polityczna przygotowuje się na wybory w 2027 r. "
        "Każda z partii, mniej lub bardziej, myśli już o potencjalnych sojuszach i programach, "
        "które miałyby zapewnić jesienny triumf. Szczególnie twardy orzech do zgryzienia ma koalicja rządząca. "
        "Sondaż Opinia24 wykazał, że ze wspólną listą KO i Lewica otrzymałyby 35,7 proc. głosów."
    )
    link = "https://wiadomosci.wp.pl/wspolny-start-ko-i-lewicy-wiadomo-kto-na-tym-najwiecej-skorzysta-7283220789245984a"
    assert should_skip_public_opinion_poll_teaser(title, summary, link)


def test_opinia24_long_distance():
    title = "Analiza szans wyborczych KO i Lewicy"
    # Lookahead distance check (920 characters in regex)
    summary_800 = (
        "W najnowszym badaniu Opinia24 sprawdzono nastroje przed wyborami. "
        + "A" * 800
        + " Wynik to 35,7 proc. poparcia."
    )
    assert should_skip_public_opinion_poll_teaser(title, summary_800)


def test_hebrew_summary_rejection_in_blob():
    """If for some reason a Hebrew summary of a poll is checked, it should be caught."""
    blob = "המפלגות בפולין כבר מתכוננות לבחירות לפרלמנט ב-2027. הסקר שערכה Opinia24 הראה שעם רשימה משותפת, KO ו-Lewica יקבלו 35.7% מהקולות."
    from config import should_skip_public_opinion_poll_blob
    assert should_skip_public_opinion_poll_blob(blob)
