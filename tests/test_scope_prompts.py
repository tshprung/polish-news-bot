"""Regression: US-only NATO / Congressional wires without PL angle should be gated by prompts."""

from config import CLASSIFY_PROMPT, SYSTEM_PROMPT


def test_classify_allows_skip_for_us_only_transatlantic():
    assert "SKIP" in CLASSIFY_PROMPT
    assert "American" in CLASSIFY_PROMPT
    assert "Poland" in CLASSIFY_PROMPT


def test_stage2_skip_us_only_actors_without_polish_hook():
    assert "only American actors" in SYSTEM_PROMPT or "US-only" in SYSTEM_PROMPT
    assert "SKIP" in SYSTEM_PROMPT
