"""Regression: national-channel scope prompts gate foreign wires without a domestic tie."""

from config import CLASSIFY_PROMPT, SYSTEM_PROMPT


def test_classify_poland_national_channel():
    assert "SKIP" in CLASSIFY_PROMPT
    assert "Poland" in CLASSIFY_PROMPT
    assert "national news" in CLASSIFY_PROMPT


def test_system_poland_direct_tie_scope():
    assert "direct Poland tie" in SYSTEM_PROMPT or "directly" in SYSTEM_PROMPT
    assert "SKIP" in SYSTEM_PROMPT


def test_system_skips_foreign_without_pl_stake():
    assert "another country's" in SYSTEM_PROMPT and "purely domestic" in SYSTEM_PROMPT


def test_system_brussels_generic_eu_examples():
    assert "Brussels" in SYSTEM_PROMPT
    assert "bloc-wide" in SYSTEM_PROMPT or "Commission" in SYSTEM_PROMPT
