"""Title filter: shopping listicles, savings tips, sponsored markers."""

from config import should_skip_commercial_clickbait_title


def test_skips_german_shopping_tips_example():
    assert should_skip_commercial_clickbait_title(
        "10 Tipps, wie Sie beim Einkaufen clever sparen"
    )


def test_skips_numbered_tips_and_savings():
    assert should_skip_commercial_clickbait_title("5 ways to save money this winter")
    assert should_skip_commercial_clickbait_title("7 tricks for smarter shopping")
    assert should_skip_commercial_clickbait_title("10 rad, jak taniej kupować online")


def test_skips_wie_sie_consumer():
    assert should_skip_commercial_clickbait_title(
        "Experten: wie Sie 500 Euro beim Strom sparen"
    )


def test_skips_sponsored_markers():
    assert should_skip_commercial_clickbait_title("Nowa oferta (reklama)")
    assert should_skip_commercial_clickbait_title("Article title — sponsored")


def test_allows_normal_news_titles():
    assert not should_skip_commercial_clickbait_title("")
    assert not should_skip_commercial_clickbait_title("   ")
    assert not should_skip_commercial_clickbait_title(
        "Sejm przyjął ustawę o podatkach"
    )
    assert not should_skip_commercial_clickbait_title(
        "12 osób rannych w wypadku na A4"
    )
    assert not should_skip_commercial_clickbait_title(
        "Trump: NATO musi więcej wydawać na obronę"
    )


def test_allows_sport_exclusion_is_separate():
    # Commercial filter must not fire on unrelated headlines
    assert not should_skip_commercial_clickbait_title(
        "Mecz Legii przełożony z powodu śniegu"
    )
