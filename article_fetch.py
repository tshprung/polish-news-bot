"""Fetch full article HTML and extract plain text."""
import json
import logging
import re

import requests

log = logging.getLogger(__name__)

# requests uses ISO-8859-1 when HTML has no charset; Polish portals are usually UTF-8 → mojibake in resp.text.
_BAD_DEFAULT_ENCODINGS = frozenset({"iso-8859-1", "windows-1252"})

# Keep fetch results bounded: stage2 will truncate again, but capping here reduces prompt bloat,
# speeds classify, and reduces retries driven by noisy boilerplate.
_MAX_BODY_CHARS = 8000
# After JSON-LD/DOM extraction, boilerplate trim can wipe noisy wires; fall back to DOM/paragraphs if this small.
_MIN_USEFUL_BODY_CHARS = 120


def _trim_boilerplate(text: str) -> str:
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        if len(ln) < 14:
            continue
        low = ln.lower()
        if any(
            k in low
            for k in (
                "reklama",
                "cookies",
                "polityka prywatności",
                "regulamin",
                "zaloguj",
                "zarejestruj",
                "subskryb",
                "kup dostęp",
                "udostępnij",
                "polecamy",
                "czytaj także",
                "zobacz także",
                "więcej na",
                "przeczytaj również",
            )
        ):
            continue
        cleaned.append(ln)
    out = "\n".join(cleaned).strip()
    if len(out) > _MAX_BODY_CHARS:
        out = out[:_MAX_BODY_CHARS].rsplit("\n", 1)[0].strip() or out[:_MAX_BODY_CHARS].strip()
    return out


def _html_text(response: requests.Response) -> str:
    """Decode HTML body with a plausible charset (avoids garbled Polish in resp.text)."""
    raw = response.content
    enc = (response.encoding or "").lower()
    if enc and enc not in _BAD_DEFAULT_ENCODINGS:
        try:
            return raw.decode(response.encoding)
        except (UnicodeDecodeError, LookupError, TypeError):
            pass
    apparent = getattr(response, "apparent_encoding", None) or "utf-8"
    for candidate in (apparent, "utf-8", "cp1250"):
        try:
            return raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _article_body_from_jsonld(page_html: str) -> str:
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            candidates = data.get("@graph", [data])
        elif isinstance(data, list):
            candidates = data
        else:
            continue
        for item in candidates:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if isinstance(t, list):
                types = t
            elif isinstance(t, str):
                types = [t]
            else:
                types = []
            if not any(x in ("NewsArticle", "Article") for x in types):
                continue
            body = item.get("articleBody")
            if isinstance(body, str) and len(body.strip()) > 150:
                return body.strip()
    return ""


def _article_body_from_dom(stripped_html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""

    def cleanup_root(r):
        for sel in (
            "ad-default",
            "aside",
            ".ods-m-bullet-list",
            ".ods-o-authorship-bottom",
            ".ods-c-share-buttons-wrapper",
            ".ods-m-socials-stream",
            ".ods-m-tts-player",
            ".ods-o-authorship-top",
            ".ods-c-actionbar",
            ".ods-c-modal-premium",
            ".ods-o-onetchat-widget-chat",
        ):
            for tag in r.select(sel):
                tag.decompose()

    soup = BeautifulSoup(stripped_html, "html.parser")
    for jid in ("pianoOffer", "pianoInfo"):
        for tag in soup.find_all(id=jid):
            tag.decompose()

    root = soup.select_one("[class*='ods-article-body']")
    if root is None:
        root = soup.find("article")
    if root is None:
        return ""
    scope = root

    cleanup_root(scope)
    block = scope.get_text(separator="\n", strip=True)
    lines = [ln for ln in (x.strip() for x in block.splitlines()) if len(ln) > 12]
    primary = "\n".join(lines)

    paragraph_chunks = []
    for p in scope.find_all("p"):
        if p.find_parent("aside"):
            continue
        chunk = p.get_text(separator=" ", strip=True)
        if len(chunk) >= 20:
            paragraph_chunks.append(chunk)
    paragraph_body = "\n".join(paragraph_chunks)

    body_chunks = []
    for div in scope.select("div.ods-a-body-text"):
        chunk = div.get_text(separator=" ", strip=True)
        if len(chunk) > 25:
            body_chunks.append(chunk)
    fallback = "\n".join(body_chunks)

    best = primary
    if len(fallback) > len(best):
        best = fallback
    # Prefer <p>-only extract when it looks like the full story (WP chrome in get_text).
    # Onet/Politico often put most copy in divs: paragraph_body can be only pull-quotes vs huge primary.
    _para_substantial = len(paragraph_body) >= max(
        200, int(0.38 * max(len(primary), 1))
    )
    if len(paragraph_body) >= 180:
        if len(paragraph_body) > len(best):
            best = paragraph_body
        elif (
            best is primary
            and len(primary) > len(paragraph_body) + 80
            and _para_substantial
        ):
            best = paragraph_body
    return best


def fetch_article_body(session: requests.Session, url: str, timeout: tuple) -> str:
    # "zaloguj się" can appear for comments/newsletters and is not necessarily a paywall.
    # Treat only strong subscription/payment prompts as paywall, and treat login/register as weak.
    paywall_signals_strong = [
        "prenumerata",
        "subskrypcja",
        "kup dostęp",
        "płatna treść",
    ]
    paywall_signals_weak = [
        "zaloguj się",
        "zarejestruj się",
    ]
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        }
        resp = session.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        page_html = _html_text(resp)

        text = _article_body_from_jsonld(page_html)
        if len(text) >= 200:
            trimmed = _trim_boilerplate(text)
            low = trimmed.lower()
            if any(s in low for s in paywall_signals_strong) and len(trimmed) < 900:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return ""
            if len(trimmed) >= _MIN_USEFUL_BODY_CHARS:
                log.info(f"Fetched {len(trimmed)} chars (JSON-LD) from {url}")
                return trimmed
            log.info(
                "JSON-LD trimmed to %d chars (below %d); trying DOM fallback for %s",
                len(trimmed),
                _MIN_USEFUL_BODY_CHARS,
                url,
            )

        stripped = re.sub(
            r"<script\b[^>]*>.*?</script>", " ", page_html, flags=re.DOTALL | re.IGNORECASE
        )
        stripped = re.sub(
            r"<style\b[^>]*>.*?</style>", " ", stripped, flags=re.DOTALL | re.IGNORECASE
        )

        text = _article_body_from_dom(stripped)
        if len(text) >= 250:
            trimmed = _trim_boilerplate(text.strip())
            low = trimmed.lower()
            if any(s in low for s in paywall_signals_strong) and len(trimmed) < 900:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return ""
            if len(trimmed) >= _MIN_USEFUL_BODY_CHARS:
                log.info(f"Fetched {len(trimmed)} chars (DOM) from {url}")
                return trimmed
            log.info(
                "Primary DOM trimmed to %d chars; trying paragraph fallback for %s",
                len(trimmed),
                url,
            )

        def extract_paragraphs(source):
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", source, re.DOTALL)
            return " ".join(
                re.sub(r"<[^>]+>", "", p).strip() for p in paragraphs if len(p) > 40
            )

        article_match = re.search(r"<article[^>]*>(.*?)</article>", stripped, re.DOTALL)
        if not article_match:
            article_match = re.search(
                r'<section[^>]*class="[^"]*\bart_content\b[^"]*"[^>]*>(.*?)</section>',
                stripped,
                re.DOTALL | re.IGNORECASE,
            )
        text = ""
        if article_match:
            text = extract_paragraphs(article_match.group(1)).strip()
        if len(text) < 300:
            text = extract_paragraphs(stripped).strip()
        text = _trim_boilerplate(text.strip())
        low = text.lower()
        if any(s in low for s in paywall_signals_strong) and len(text) < 900:
            log.warning(f"Paywall detected at {url}, ignoring fetched content")
            return ""
        log.info(f"Fetched {len(text)} chars from {url}")
        return text
    except Exception as e:
        log.warning(f"Could not fetch article body from {url}: {e}")
        return ""
