"""Regression: Hebrew summaries must use real words (e.g. zbiory → איסוף), not invented calques."""

from config import SYSTEM_PROMPT


def test_system_prompt_rejects_invented_zbiory_calque():
    """WNP / RMF wires on regulated snail harvest used pseudo-Hebrew 'זבירות' (non-word)."""
    assert "זבירות" in SYSTEM_PROMPT
    assert "zbiory" in SYSTEM_PROMPT.lower() or "zbiór" in SYSTEM_PROMPT.lower()
    assert "איסוף" in SYSTEM_PROMPT


def test_system_prompt_gdansk_latin_not_hebrew_begeda():
    """Onet Gdańsk Easter procession was summarized as בגדה—confusing / Israel-adjacent misread."""
    assert "Gdańsk" in SYSTEM_PROMPT
    assert "בגדה" in SYSTEM_PROMPT
    assert "ב-Gdańsk" in SYSTEM_PROMPT


def test_system_prompt_country_is_polin_not_polska():
    """Avoid 'ב-Polska' hybrid; country should be פולין in Hebrew."""
    assert "פולין" in SYSTEM_PROMPT
    assert "ב-Polska" in SYSTEM_PROMPT
