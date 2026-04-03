"""OpenAI: classify + Hebrew summary."""
import logging
import re
from urllib.parse import urlparse

import requests
from openai import OpenAI

from article_fetch import fetch_article_body
from config import (
    CLASSIFY_PROMPT,
    MAX_SUMMARY_WORDS,
    MAX_SUMMARY_WORDS_HARD,
    OPENAI_MAX_RETRIES,
    OPENAI_TIMEOUT_SEC,
    PAYWALLED_DOMAINS,
    SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)

_SUMMARY_CAP = str(MAX_SUMMARY_WORDS)


def classify(client: OpenAI, text: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=5,
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": f"Article: {text[:500]}"},
        ],
    )
    result = response.choices[0].message.content.strip().upper()
    if result.startswith("SKIP") or "סקיפ" in result:
        return "SKIP"
    return "GO"


def summarize_in_hebrew(
    client: OpenAI,
    session: requests.Session,
    http_timeout: tuple,
    article: dict,
):
    rss_text = article["title"]
    if article["summary"]:
        rss_text += ". " + article["summary"]

    domain = urlparse(article["link"]).netloc.lstrip("www.")
    if domain in PAYWALLED_DOMAINS:
        return None, f"paywalled domain ({domain})"

    body = fetch_article_body(session, article["link"], http_timeout)
    text = (article["title"] + ". " + body) if body else rss_text
    body_available = bool(body)

    decision = classify(client, text)
    if decision == "SKIP":
        return None, None

    stage2_limit = 4000

    def call_stage2(user_blob: str):
        return client.chat.completions.create(
            model="gpt-4o",
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_blob},
            ],
        )

    insufficient_retry_note = (
        "Use any concrete facts given. Short pieces OK: TV/radio = name guests, shows, times; "
        "else what/where/outcome. INSUFFICIENT only if the body adds almost nothing beyond the headline."
    )
    short_retry_note = (
        f"Output a real Hebrew sentence (not empty); max {_SUMMARY_CAP} words."
    )

    result = ""
    used_insuf_retry = False
    for attempt in range(2):
        user_blob = f"Article: {text[:stage2_limit]}"
        if attempt == 1 and used_insuf_retry:
            user_blob = f"{user_blob}\n\n{insufficient_retry_note}"
        elif attempt == 1 and len(result) > 0 and len(result) < 15:
            user_blob = f"{user_blob}\n\n{short_retry_note}"

        response = call_stage2(user_blob)
        finish = response.choices[0].finish_reason
        if finish == "content_filter":
            return None, "blocked by content policy (content_filter)"
        if finish == "length":
            return None, "response truncated"
        result = (response.choices[0].message.content or "").strip()

        if result.upper().startswith("SKIP") or result.startswith("סקיפ"):
            return None, None

        is_insuf = result.upper().startswith("INSUF") or result.startswith("לא מספיק")
        if is_insuf:
            if not body_available:
                return None, "body not accessible (paywall or blocked)"
            if body_available and not used_insuf_retry and attempt == 0:
                used_insuf_retry = True
                log.info("Stage 2 INSUFFICIENT — retry with hint (schedule/thin body)")
                continue
            return None, "insufficient content even with full article"

        if len(result) >= 15:
            break
        log.warning(f"Stage 2 response too short (attempt {attempt + 1}): '{result}'")
        if attempt >= 1:
            return None, "response too short after retry"

    if len(result) < 15:
        return None, "response too short after retry"

    result = re.sub(
        r"[^\u0590-\u05FF\uFB1D-\uFB4FA-Za-z0-9\u00C0-\u024F\s,.:;!?%()\"\'-]", "", result
    ).strip()
    if not result:
        return None, "sanitization left empty result"
    if not re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result):
        return None, "no Hebrew characters in result"
    m_heb = re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result)
    result = result[m_heb.start() :].strip()
    if len(result) < 15:
        return None, "Hebrew too short after removing leading non-Hebrew (likely echoed input)"

    _hebrew_glue = r"\u0590-\u05FF\uFB1D-\uFB4F"
    _latin_glue = r"A-Za-z\u00C0-\u024F"
    result = re.sub(rf"[{_hebrew_glue}]+(?=[{_latin_glue}])", "", result)
    result = re.sub(rf"(?<=[{_latin_glue}])[{_hebrew_glue}]+", "", result)
    result = result.strip()

    hebrew_re = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")
    latin_re = re.compile(r"[A-Za-z]")
    for token in re.split(r"[\s\-]+", result):
        if hebrew_re.search(token) and latin_re.search(token):
            return None, f"mixed-script word detected: '{token}'"

    word_count = len(result.split())
    if word_count > MAX_SUMMARY_WORDS_HARD:
        return None, f"summary too long ({word_count} words, max {MAX_SUMMARY_WORDS})"

    return result, None


def openai_client() -> OpenAI:
    return OpenAI(timeout=OPENAI_TIMEOUT_SEC, max_retries=OPENAI_MAX_RETRIES)
