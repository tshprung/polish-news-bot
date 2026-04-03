"""Fetch full article HTML and extract plain text."""
import json
import logging
import re

import requests

log = logging.getLogger(__name__)


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
    if len(paragraph_body) >= 180:
        if len(paragraph_body) > len(best):
            best = paragraph_body
        elif best is primary and len(primary) > len(paragraph_body) + 80:
            best = paragraph_body
    return best


def fetch_article_body(session: requests.Session, url: str, timeout: tuple) -> str:
    paywall_signals = [
        "zaloguj się",
        "zarejestruj się",
        "prenumerata",
        "subskrypcja",
        "kup dostęp",
        "płatna treść",
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
        page_html = resp.text

        text = _article_body_from_jsonld(page_html)
        if len(text) >= 200:
            if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return ""
            log.info(f"Fetched {len(text)} chars (JSON-LD) from {url}")
            return text

        stripped = re.sub(
            r"<script\b[^>]*>.*?</script>", " ", page_html, flags=re.DOTALL | re.IGNORECASE
        )
        stripped = re.sub(
            r"<style\b[^>]*>.*?</style>", " ", stripped, flags=re.DOTALL | re.IGNORECASE
        )

        text = _article_body_from_dom(stripped)
        if len(text) >= 250:
            if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return ""
            log.info(f"Fetched {len(text)} chars (DOM) from {url}")
            return text.strip()

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
        if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
            log.warning(f"Paywall detected at {url}, ignoring fetched content")
            return ""
        log.info(f"Fetched {len(text)} chars from {url}")
        return text.strip()
    except Exception as e:
        log.warning(f"Could not fetch article body from {url}: {e}")
        return ""
