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
