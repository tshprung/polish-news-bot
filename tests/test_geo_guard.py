from summarize import (
    _hebrew_mentions_major_israeli_city,
    _source_suggests_warsaw_area_not_israel,
)


def test_syrenka_warsaw_source_flags_tel_aviv_hebrew():
    pl = "Zniszczyły pomnik Syrenki jest wyrok sądu Warszawa"
    he = "על פסל בתל אביב נידונו לעבודות שירות"
    assert _source_suggests_warsaw_area_not_israel(pl) is True
    assert _hebrew_mentions_major_israeli_city(he) is True


def test_israel_story_in_polish_not_flagged_for_warsaw():
    pl = "Ambasada Polski w Izraelu Tel Awiw spotkanie"
    assert _source_suggests_warsaw_area_not_israel(pl) is False


def test_krakow_only_no_warsaw_marker():
    pl = "Kraków festiwal kultury"
    assert _source_suggests_warsaw_area_not_israel(pl) is False
