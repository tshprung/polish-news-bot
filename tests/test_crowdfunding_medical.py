"""Private medical zbiórka / donation appeals — not national news."""

from config import (
    crowdfunding_medical_skip_reason,
    should_skip_private_medical_fundraiser_blob,
    should_skip_private_medical_fundraiser_teaser,
    skip_admin_notify_for_reason,
)


def test_skips_family_fundraiser_for_treatment():
    title = "Najstarsze dziecko w Polsce z tą chorobą. Adaś walczy o życie"
    summary = (
        "Rodzina zbiera na leczenie genetyczne w USA. Potrzebują ponad 11 milionów złotych; koszt terapii to 3,7 mln dolarów."
    )
    assert should_skip_private_medical_fundraiser_teaser(title, summary)
    assert should_skip_private_medical_fundraiser_blob(title + "\n" + summary)


def test_skips_zbiorka_na_leczenie():
    assert should_skip_private_medical_fundraiser_teaser(
        "Zbiórka na leczenie małego Pawła",
        "Fundacja prosi o wsparcie — na koncie brakuje jeszcze 200 tys. zł.",
    )


def test_allows_nfz_policy_news():
    blob = (
        "NFZ ogłasza refundację leku na dystrofię. Ministerstwo Zdrowia przewiduje program w 2026; "
        "rząd przeznaczy budżet na terapię genetyczną."
    )
    assert not should_skip_private_medical_fundraiser_blob(blob)


def test_allows_accident_without_fundraiser():
    assert not should_skip_private_medical_fundraiser_teaser(
        "Wypadek na A4. Pięć osób rannych",
        "Służby na miejscu; droga zablokowana. Dwie osoby w szpitalu w Krakowie.",
    )


def test_skip_reason_notify_exempt():
    assert skip_admin_notify_for_reason(crowdfunding_medical_skip_reason())
