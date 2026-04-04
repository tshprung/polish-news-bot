"""Pan-EU property / energy explainer teasers without PL or DE hook."""

from config import (
    pan_eu_property_guide_skip_reason,
    should_skip_pan_eu_generic_property_guide,
    skip_admin_notify_for_reason,
)


def test_skips_welt_energy_certificate_hebrew_teaser():
    title = "TOPNEWS - WELT"
    summary = (
        "מ-2024, בכל האיחוד האירופי מונפקים תעודות אנרגיה חדשות שעלולות להשפיע על דירוג ושווי נכסי נדל\"ן. "
        "הבעלים עשויים לראות שערך הנכסים שלהם יורד. WELT מסביר כיצד לפעול בתגובה."
    )
    assert should_skip_pan_eu_generic_property_guide(title, summary)


def test_keeps_when_poland_mentioned():
    title = "Unia Europejska"
    summary = (
        "Od 2024 we całej UE obowiązują nowe świadectwa energetyczne; w Polsce Ministerstwo "
        "Wyjaśnia, co powinni wiedzieć właściciele nieruchomości."
    )
    assert not should_skip_pan_eu_generic_property_guide(title, summary)


def test_keeps_when_germany_mentioned():
    title = "Neuer Energieausweis"
    summary = (
        "EU-weit gelten neue Regeln; in Deutschland erklärt der Verband, "
        "wie Eigentümer jetzt handeln sollten."
    )
    assert not should_skip_pan_eu_generic_property_guide(title, summary)


def test_no_match_without_explainer_tone():
    title = "EU climate"
    summary = (
        "W całej UE spadły emisje CO2 według szacunków KE; szczegóły w tekście."
    )
    assert not should_skip_pan_eu_generic_property_guide(title, summary)


def test_skip_reason_is_notify_exempt():
    assert skip_admin_notify_for_reason(pan_eu_property_guide_skip_reason())
    assert skip_admin_notify_for_reason("rss teaser: no extractable facts")
