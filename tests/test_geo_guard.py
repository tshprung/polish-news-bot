from summarize import (
    _hebrew_mentions_major_israeli_city,
    _strip_erroneous_israel_subject_prefix,
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


def test_strip_erroneous_israel_prefix_when_source_not_israel():
    src = "Microsoft schlägt Alarm: Hacker greifen über WhatsApp Windows-PCs an"
    he = "ישראל ש-Microsoft מזהירים מפני מתקפת סייבר דרך WhatsApp ב-Windows"
    assert _strip_erroneous_israel_subject_prefix(he, src).startswith("Microsoft")


def test_do_not_strip_israel_prefix_when_source_mentions_israel():
    src = "Microsoft warns users in Israel about a campaign"
    he = "ישראל ש-Microsoft מזהירים מפני מתקפת סייבר"
    assert _strip_erroneous_israel_subject_prefix(he, src).startswith("ישראל")
