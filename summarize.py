"""OpenAI: classify + Hebrew summary."""
import atexit
import html
import logging
import re
from urllib.parse import urlparse

from dataclasses import dataclass

import requests
import openai
from openai import OpenAI

from article_fetch import fetch_article_body
from config import (
    CLASSIFY_PROMPT,
    MAX_SUMMARY_WORDS,
    MAX_SUMMARY_WORDS_HARD,
    OPENAI_MAX_RETRIES,
    OPENAI_MODEL_CLASSIFY,
    OPENAI_MODEL_SUMMARIZE,
    OPENAI_TIMEOUT_SEC,
    PAYWALLED_DOMAINS,
    STAGE2_INPUT_CHARS_DEFAULT,
    STAGE2_INPUT_CHARS_LONG_BODY,
    SYSTEM_PROMPT,
    baltic_marine_wildlife_no_poland_skip_reason,
    baltic_wildlife_history_skip_reason,
    crowdfunding_medical_skip_reason,
    entertainment_chat_skip_reason,
    evergreen_culture_skip_reason,
    fold_pl,
    hebrew_scope_meta_summary_skip_reason,
    is_zeit_jahrgang_index_url,
    should_reject_hebrew_scope_meta_summary,
    pan_eu_property_guide_skip_reason,
    public_opinion_poll_skip_reason,
    rss_teaser_skip_reason,
    should_skip_baltic_marine_wildlife_without_poland_blob,
    should_skip_baltic_wildlife_history_teaser,
    should_skip_entertainment_politician_chat_teaser,
    should_skip_evergreen_culture_teaser,
    should_skip_information_poor_rss_teaser,
    should_skip_pan_eu_generic_property_guide,
    should_skip_private_medical_fundraiser_blob,
    should_skip_private_medical_fundraiser_teaser,
    should_skip_public_opinion_poll_blob,
    should_skip_public_opinion_poll_teaser,
    should_skip_non_national_poland_teaser,
    non_national_poland_skip_reason,
    should_skip_ultra_short_rss_item,
    ultra_short_rss_skip_reason,
    zeit_jahrgang_index_skip_reason,
)

log = logging.getLogger(__name__)

_SUMMARY_CAP = str(MAX_SUMMARY_WORDS)


def _chat_create(client: OpenAI, *, model: str, messages: list[dict], max_out: int):
    try:
        return client.chat.completions.create(
            model=model,
            max_completion_tokens=max_out,
            messages=messages,
        )
    except openai.BadRequestError as e:
        if "Unsupported parameter: 'max_completion_tokens'" in str(e):
            return client.chat.completions.create(
                model=model,
                max_tokens=max_out,
                messages=messages,
            )
        raise


@dataclass
class _RunTelemetry:
    classify_calls: int = 0
    stage2_calls: int = 0
    stage2_retries: int = 0
    body_fetched_chars: int = 0
    stage2_input_chars: int = 0


_TEL = _RunTelemetry()


@atexit.register
def _log_run_telemetry() -> None:
    # Numeric-only (no article text) so it is safe to keep in logs.
    if _TEL.classify_calls == 0 and _TEL.stage2_calls == 0:
        return
    avg_in = (_TEL.stage2_input_chars / _TEL.stage2_calls) if _TEL.stage2_calls else 0.0
    avg_body = (_TEL.body_fetched_chars / _TEL.classify_calls) if _TEL.classify_calls else 0.0
    log.info(
        "OpenAI telemetry: classify_calls=%d stage2_calls=%d stage2_retries=%d avg_stage2_input_chars=%.0f avg_body_chars=%.0f",
        _TEL.classify_calls,
        _TEL.stage2_calls,
        _TEL.stage2_retries,
        avg_in,
        avg_body,
    )

_HEBREW_CHAR_RE = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")
_SANITIZE_HB_LINE = re.compile(
    r"[^\u0590-\u05FF\uFB1D-\uFB4FA-Za-z0-9\u00C0-\u024F\s,.:;!?%()\"\'-]"
)

_ISRAEL_MENTION_RE = re.compile(
    r"(?is)(?:\bIsrael\b|Izrael|ישראל|Tel\s*[-]?\s*Aviv|Jerusalem|תל\s*[-]?\s*אביב|ירושלים)"
)


def _sanitize_hebrew_summary_line(result: str) -> str:
    """Decode HTML entities before stripping chars, or &#34; becomes garbage \"34;\"."""
    return _SANITIZE_HB_LINE.sub("", html.unescape(result)).strip()

_LEADING_LABEL_PATTERNS = (
    r"^העברית\s*:\s*",
    r"^עברית\s*:\s*",
    r"^תרגום\s*:\s*",
    r"^סיכום\s*:\s*",
    r"^hebrew\s*:\s*",
    r"^summary\s*:\s*",
)


def strip_leading_summary_labels(text: str) -> str:
    """Remove model echoes like 'עברית:' before the real summary."""
    s = text.strip()
    for _ in range(4):
        prev = s
        for pat in _LEADING_LABEL_PATTERNS:
            s = re.sub(pat, "", s, count=1, flags=re.IGNORECASE).lstrip()
        if s == prev:
            break
    return s


def _source_suggests_warsaw_area_not_israel(polish_blob: str) -> bool:
    """True if folded Polish text points to Warsaw/Syrenka without an Israel/Tel Aviv angle."""
    f = fold_pl(polish_blob[:6000])
    if not re.search(r"warszaw|syrenk|warszawsk", f, re.IGNORECASE):
        return False
    if re.search(r"izrael|tel\s*aviv|tel\s*awiw|jerozolim", f, re.IGNORECASE):
        return False
    return True


def _hebrew_mentions_major_israeli_city(hebrew: str) -> bool:
    return bool(re.search(r"תל\s*[-]?\s*אביב|ירושלים", hebrew))


def _strip_erroneous_israel_subject_prefix(hebrew: str, source_blob: str) -> str:
    """
    Some German headlines like "Microsoft schlägt Alarm" may get mistranslated as
    "ישראל ש-Microsoft ..." (as if Israel is the target/subject). Strip that prefix
    unless the source explicitly mentions Israel.
    """
    s = (hebrew or "").strip()
    if not s.startswith("ישראל"):
        return s
    if _ISRAEL_MENTION_RE.search(source_blob or ""):
        return s
    # Common bad pattern: "ישראל ש-Microsoft ..." / "ישראל ש Microsoft ..."
    return re.sub(r"^ישראל\s*ש\s*[-]?\s*", "", s, count=1).lstrip()


def classify(client: OpenAI, text: str):
    _TEL.classify_calls += 1
    response = _chat_create(
        client,
        model=OPENAI_MODEL_CLASSIFY,
        max_out=5,
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": f"Article: {text[:500]}"},
        ],
    )
    result = response.choices[0].message.content.strip().upper()
    if result.startswith("SKIP") or "סקיפ" in result:
        return "SKIP"
    return "GO"


def _rss_excerpt_substantial(article: dict) -> bool:
    summary = (article.get("summary") or "").strip()
    title = (article.get("title") or "").strip()
    if len(summary) >= 200:
        return True
    if len(title) + len(summary) >= 300:
        return True
    return len(summary) >= 120 and len(title) + len(summary) >= 220


def summarize_in_hebrew(
    client: OpenAI,
    session: requests.Session,
    http_timeout: tuple,
    article: dict,
):
    rss_text = article["title"]
    if article["summary"]:
        rss_text += ". " + article["summary"]

    if should_skip_ultra_short_rss_item(article.get("title"), article.get("summary")):
        return None, ultra_short_rss_skip_reason()

    if should_skip_public_opinion_poll_teaser(
        article.get("title"),
        article.get("summary"),
        article.get("link") or "",
    ):
        return None, public_opinion_poll_skip_reason()

    if should_skip_information_poor_rss_teaser(article["title"], article["summary"]):
        return None, rss_teaser_skip_reason()

    if should_skip_evergreen_culture_teaser(
        article["title"], article["summary"], article.get("link"),
    ):
        return None, evergreen_culture_skip_reason()

    if should_skip_baltic_wildlife_history_teaser(
        article["title"], article["summary"], article.get("link"),
    ):
        return None, baltic_wildlife_history_skip_reason()

    if should_skip_entertainment_politician_chat_teaser(
        article["title"], article["summary"], article.get("link"),
    ):
        return None, entertainment_chat_skip_reason()

    if should_skip_pan_eu_generic_property_guide(article["title"], article["summary"]):
        return None, pan_eu_property_guide_skip_reason()

    if should_skip_private_medical_fundraiser_teaser(article["title"], article["summary"]):
        return None, crowdfunding_medical_skip_reason()

    if should_skip_non_national_poland_teaser(
        article.get("title") or "", article.get("summary") or "", article.get("link") or ""
    ):
        return None, non_national_poland_skip_reason()

    if is_zeit_jahrgang_index_url(article.get("link")):
        return None, zeit_jahrgang_index_skip_reason()

    domain = urlparse(article["link"]).netloc.lstrip("www.")
    if domain in PAYWALLED_DOMAINS:
        return None, f"paywalled domain ({domain})"

    body = fetch_article_body(session, article["link"], http_timeout)
    if body:
        _TEL.body_fetched_chars += len(body)
    text = (article["title"] + ". " + body) if body else rss_text
    body_available = bool(body)

    if should_skip_public_opinion_poll_blob(
        (article.get("title") or "")
        + "\n"
        + (article.get("summary") or "")
        + "\n"
        + (article.get("link") or "")
        + "\n"
        + (body or "")[:12000],
    ):
        return None, public_opinion_poll_skip_reason()

    if body and should_skip_private_medical_fundraiser_blob(
        (article["title"] or "") + "\n" + body[:10000]
    ):
        return None, crowdfunding_medical_skip_reason()

    pl_baltic_blob = (
        (article.get("title") or "")
        + "\n"
        + (article.get("summary") or "")
        + "\n"
        + (article.get("link") or "")
        + "\n"
        + (body or "")[:12000]
    )
    if should_skip_baltic_marine_wildlife_without_poland_blob(pl_baltic_blob):
        return None, baltic_marine_wildlife_no_poland_skip_reason()

    decision = classify(client, text)
    if decision == "SKIP":
        return None, None

    stage2_limit = int(STAGE2_INPUT_CHARS_DEFAULT)
    if not _rss_excerpt_substantial(article) and len(body or "") >= 4500:
        stage2_limit = int(STAGE2_INPUT_CHARS_LONG_BODY)

    def call_stage2(user_blob: str):
        _TEL.stage2_calls += 1
        _TEL.stage2_input_chars += len(user_blob)
        return _chat_create(
            client,
            model=OPENAI_MODEL_SUMMARIZE,
            max_out=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_blob},
            ],
        )

    insufficient_retry_note = (
        "Use any concrete facts given. Short pieces OK: TV/radio = name guests, shows, times; "
        "else what/where/outcome; interviews and official wires = who + what they said or decided. "
        "INSUFFICIENT only if the body adds almost nothing beyond the headline (no names, agencies, dates, numbers, decisions)."
    )
    strong_insuf_note = (
        "The body is long and clearly contains reporting: names, titles, quotations, and/or attribution. "
        "Examples: US ambassador in Poland, EU/Iran/NATO diplomacy; regional RDOŚ/environmental rules; "
        "local incidents with services/responders—summarize factually who said/did what and on what topic. "
        "Reply INSUFFICIENT only when there are no extractable facts beyond the headline."
    )
    short_retry_note = (
        f"Output a real Hebrew sentence (not empty); max {_SUMMARY_CAP} words."
    )

    result = ""
    insuf_hint_tier = 0  # 0=none, 1=standard insufficient hint, 2=long-article / quote-heavy hint
    for attempt in range(2):
        if attempt >= 1:
            _TEL.stage2_retries += 1
        user_blob = f"Article: {text[:stage2_limit]}"
        if insuf_hint_tier == 1:
            user_blob = f"{user_blob}\n\n{insufficient_retry_note}"
        elif insuf_hint_tier == 2:
            user_blob = f"{user_blob}\n\n{strong_insuf_note}"
        elif attempt >= 1 and len(result) > 0 and len(result) < 15:
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
            if insuf_hint_tier == 0:
                insuf_hint_tier = 1
                log.info("Stage 2 INSUFFICIENT — retry with hint (schedule/thin body)")
                continue
            if insuf_hint_tier == 1 and len(text) >= 1200:
                insuf_hint_tier = 2
                log.info("Stage 2 INSUFFICIENT — retry with long-body / diplomacy hint")
                continue
            return None, "insufficient content even with full article"

        if len(result) >= 15:
            break
        log.warning(f"Stage 2 response too short (attempt {attempt + 1}): '{result}'")
        if attempt >= 2:
            return None, "response too short after retry"

    if result.upper().startswith("INSUF") or result.startswith("לא מספיק"):
        if not body_available:
            return None, "body not accessible (paywall or blocked)"
        return None, "insufficient content even with full article"
    if len(result) < 15:
        return None, "response too short after retry"

    result = strip_leading_summary_labels(result)

    result = _sanitize_hebrew_summary_line(result)
    if not result:
        return None, "sanitization left empty result"

    if not _HEBREW_CHAR_RE.search(result):
        log.warning("Stage 2: no Hebrew after sanitize — retry with Hebrew-only instruction")
        hebrew_only_note = (
            "You must write the summary using Hebrew letters (עברית). Your previous reply had no Hebrew. "
            "1-2 factual sentences; Latin script only for proper names (e.g. Nawrocki, Orbán, WP). "
            f"Max {_SUMMARY_CAP} words. Do not output English-only or Polish-only text."
        )
        response = call_stage2(f"Article: {text[:stage2_limit]}\n\n{hebrew_only_note}")
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
            return None, "insufficient content even with full article"
        if len(result) < 15:
            return None, "no Hebrew characters in result"
        result = strip_leading_summary_labels(result)
        result = _sanitize_hebrew_summary_line(result)
        if not result:
            return None, "sanitization left empty result"
        if not _HEBREW_CHAR_RE.search(result):
            return None, "no Hebrew characters in result"

    m_heb = _HEBREW_CHAR_RE.search(result)
    result = result[m_heb.start() :].strip()
    if len(result) < 15:
        return None, "Hebrew too short after removing leading non-Hebrew (likely echoed input)"

    _hebrew_glue = r"\u0590-\u05FF\uFB1D-\uFB4F"
    _latin_glue = r"A-Za-z\u00C0-\u024F"
    result = re.sub(rf"[{_hebrew_glue}]+(?=[{_latin_glue}])", "", result)
    result = re.sub(rf"(?<=[{_latin_glue}])[{_hebrew_glue}]+", "", result)
    result = result.strip()

    hebrew_re = _HEBREW_CHAR_RE
    latin_re = re.compile(r"[A-Za-z]")
    for token in re.split(r"[\s\-]+", result):
        if hebrew_re.search(token) and latin_re.search(token):
            return None, f"mixed-script word detected: '{token}'"

    word_count = len(result.split())
    if word_count > MAX_SUMMARY_WORDS_HARD:
        return None, f"summary too long ({word_count} words, max {MAX_SUMMARY_WORDS})"

    if _source_suggests_warsaw_area_not_israel(text) and _hebrew_mentions_major_israeli_city(
        result
    ):
        log.warning("GEO guard: Warsaw-area Polish source but Hebrew cited Tel Aviv/Jerusalem")
        return None, "GEO mismatch (Warsaw/Syrenka story vs Israeli city in Hebrew; re-run)"

    result = _strip_erroneous_israel_subject_prefix(result, text)
    if not result:
        return None, "empty after stripping erroneous Israel prefix"

    if should_reject_hebrew_scope_meta_summary(result):
        return None, hebrew_scope_meta_summary_skip_reason()

    if should_skip_public_opinion_poll_blob(result):
        return None, public_opinion_poll_skip_reason()

    return result, None


def openai_client() -> OpenAI:
    return OpenAI(timeout=OPENAI_TIMEOUT_SEC, max_retries=OPENAI_MAX_RETRIES)
