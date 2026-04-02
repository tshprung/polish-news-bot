import feedparser
import sqlite3
import requests
from openai import OpenAI
import html
import time
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

FEEDS = [
    # General national (headlines from several editorial lenses)
    "https://tvn24.pl/rss/najwazniejsze.xml",
    "https://www.rmf24.pl/fakty/feed",
    "https://wiadomosci.onet.pl/.feed",
    "https://www.polsatnews.pl/rss/wszystkie.xml",
    "https://wydarzenia.interia.pl/feed",
    "https://wiadomosci.wp.pl/rss.xml",
    "https://wiadomosci.gazeta.pl/pub/rss/wiadomosci.xml",
    # PAP wire — domestic politics/society + economy (factual backbone; expect overlap with portals)
    "https://pap-mediaroom.pl/kategoria/polityka-i-społeczeństwo/rss.xml",
    "https://pap-mediaroom.pl/kategoria/biznes-i-finanse/rss.xml",
    # wyborcza.pl removed — paywalled, article body not accessible
    # rp.pl removed — JS-rendered content, not accessible via static scraping
]

SPORTS_KEYWORDS = re.compile(
    r"\b(sport|pi[łl]k|mecz|liga|transfer|fifa|ekstraklasa|kibic|trener|bramk|"
    r"mistrzostwa|turniej|olimp|zawodnik|skoczni|hokej|tenis|koszykówk|siatk[oó]wk|"
    r"lekkoatletyk|wy[śs]cig|formu[łl]a\s*1|tour\s+de|rugby|krykiet|boks|wrestling)\b",
    re.IGNORECASE,
)

PAYWALLED_DOMAINS = {"pro.rp.pl", "rp.pl", "wyborcza.pl"}

# Summaries: align model instruction, validation cap, and user-facing expectation.
MAX_SUMMARY_WORDS = 40
MAX_SUMMARY_WORDS_HARD = 48  # small slack above prompt limit (counts Latin names as words)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = Path(os.environ.get("DB_PATH", "/opt/polish_news/seen.db"))

SYSTEM_PROMPT = (
    "You are a Hebrew news editor for a Telegram channel.\n\n"
    "AUDIENCE\n"
    "- Hebrew speakers who live in Poland; they follow Polish national news.\n"
    "- Summarize in Hebrew so they grasp the story quickly; keep Polish context where needed.\n\n"
    "CONTEXT\n"
    "- Articles are from Polish media.\n"
    "- Assume Poland unless stated otherwise.\n"
    "- Polish people = פולנים (never ישראלים).\n\n"
    "TASK\n"
    "Return exactly one:\n"
    "1. SKIP — sports / not Polish internal affairs / no impact on life in Poland\n"
    "2. INSUFFICIENT — missing or unclear key facts\n"
    "3. Hebrew summary — one or two short sentences, "
    f"≤{MAX_SUMMARY_WORDS} words total\n\n"
    "RULES\n"
    "- Output only one option (no explanations, no preamble in Polish or English).\n"
    "- First significant output for a Hebrew summary must be Hebrew text "
    "(Latin only inside the sentence for names, places, acronyms).\n"
    "- SKIP / INSUFFICIENT must match exactly.\n"
    "- No hallucinations or assumptions.\n"
    "- Do not repeat or quote the article; paraphrase.\n"
    "- If the headline is clear → summarize.\n\n"
    "HEBREW\n"
    "- Natural, fluent, factual.\n"
    "- Keep Polish place names (e.g. Warszawa).\n"
    "- Keep names/orgs in Latin (e.g. NATO, PiS).\n"
    "- No mixed scripts within a single word.\n"
    "- Use standard Hebrew words only.\n\n"
    "OUTPUT\n"
    f"SKIP / INSUFFICIENT / ≤{MAX_SUMMARY_WORDS}-word Hebrew summary"
)


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_articles "
        "(id TEXT PRIMARY KEY, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("DELETE FROM seen_articles WHERE sent_at < datetime('now', '-7 days')")
    conn.commit()
    return conn


def get_new_articles(conn):
    new_articles = []
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                article_id = entry.get("id") or entry.get("link")
                if not article_id:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM seen_articles WHERE id = ?", (article_id,)
                ).fetchone()
                if not exists:
                    published = entry.get("published_parsed")
                    if published:
                        dt = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        dt = datetime.now(timezone.utc)
                    dt_local = dt.astimezone(ZoneInfo("Europe/Warsaw"))
                    new_articles.append({
                        "id": article_id,
                        "link": entry.get("link") or article_id,
                        "title": entry.get("title", ""),
                        "summary": re.sub(r"<[^>]+>", "", entry.get("summary", "")),
                        "source": feed.feed.get("title", feed_url),
                        "date": dt_local.strftime("%d.%m.%Y %H:%M"),
                        "sort_key": dt,
                    })
        except Exception as e:
            log.error(f"Failed to fetch {feed_url}: {e}")
    return new_articles


def title_words(title):
    """Return a set of lowercased words from a title, stripped of punctuation."""
    return set(re.sub(r"[^\w\s]", "", title.lower()).split())


def deduplicate(conn, articles):
    """Remove articles whose title is very similar to an earlier article within 2 hours.

    Dropped duplicates are marked seen so the same RSS id is not retried every run.
    """
    kept = []
    for article in articles:
        words = title_words(article["title"])
        is_duplicate = False
        for seen in kept:
            if abs((article["sort_key"] - seen["sort_key"]).total_seconds()) <= 7200:
                seen_words = title_words(seen["title"])
                if not words or not seen_words:
                    continue
                overlap = len(words & seen_words) / max(len(words), len(seen_words))
                if overlap >= 0.6:
                    is_duplicate = True
                    log.info(
                        f"Duplicate ({overlap:.0%} overlap): '{article['title'][:60]}' "
                        f"~ '{seen['title'][:60]}'"
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                    )
                    break
        if not is_duplicate:
            kept.append(article)
    conn.commit()
    return kept


def fetch_article_body(url):
    """Fetch full article text from URL. Returns plain text, stripped of HTML tags."""
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
        resp = requests.get(url, timeout=10, headers=headers)
        resp.raise_for_status()
        html = resp.text
        # Try <article> block first; if it yields little content, fall back to full page
        article_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
        def extract_paragraphs(source):
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", source, re.DOTALL)
            return " ".join(re.sub(r"<[^>]+>", "", p).strip() for p in paragraphs if len(p) > 40)
        text = ""
        if article_match:
            text = extract_paragraphs(article_match.group(1)).strip()
        if len(text) < 300:
            text = extract_paragraphs(html).strip()
        # Discard if the page looks like a paywall or login prompt
        paywall_signals = ["zaloguj się", "zarejestruj się", "prenumerata", "subskrypcja", "kup dostęp", "płatna treść"]
        if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
            log.warning(f"Paywall detected at {url}, ignoring fetched content")
            return ""
        log.info(f"Fetched {len(text)} chars from {url}")
        return text.strip()
    except Exception as e:
        log.warning(f"Could not fetch article body from {url}: {e}")
        return ""


CLASSIFY_PROMPT = (
    "You are a filter for a news channel about Poland.\n"
    "All articles come from Polish news sources.\n\n"
    "Reply with SKIP only if the article is clearly about:\n"
    "- Foreign news with no connection to Poland\n"
    "- Sports\n\n"
    "Reply with GO for everything else — including Polish politics, crime, economy, society, "
    "weather, accidents, and any story where Poland or Polish people are involved.\n"
    "When in doubt, reply GO.\n\n"
    "Reply with only one word: SKIP or GO."
)


def classify(client, text):
    """Stage 1: cheap model decides SKIP / GO."""
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


def summarize_in_hebrew(client, article):
    """Returns (hebrew_text, skip_reason).
    hebrew_text is None if the article should be skipped.
    skip_reason is None on success, or a string describing why it was skipped.
    """
    rss_text = article["title"]
    if article["summary"]:
        rss_text += ". " + article["summary"]

    # Skip fetching for known paywalled domains
    domain = urlparse(article["link"]).netloc.lstrip("www.")
    if domain in PAYWALLED_DOMAINS:
        return None, f"paywalled domain ({domain})"

    # Always fetch the full article body
    body = fetch_article_body(article["link"])
    text = (article["title"] + ". " + body) if body else rss_text
    body_available = bool(body)

    # Stage 1: classify with cheap model — only filters obvious non-Poland/sports
    decision = classify(client, text)
    if decision == "SKIP":
        return None, None  # silent skip, not Poland-related

    def call_stage2(t):
        return client.chat.completions.create(
            model="gpt-4o",
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Article: {t[:2000]}"},
            ],
        )

    # Stage 2: summarize with powerful model (retry once on bad response)
    for attempt in range(2):
        response = call_stage2(text)
        finish = response.choices[0].finish_reason
        if finish == "content_filter":
            return None, "blocked by content policy (content_filter)"
        if finish == "length":
            return None, "response truncated"
        result = (response.choices[0].message.content or "").strip()

        if result.upper().startswith("SKIP") or result.startswith("סקיפ"):
            return None, None
        if result.upper().startswith("INSUF") or result.startswith("לא מספיק"):
            if not body_available:
                return None, "body not accessible (paywall or blocked)"
            return None, "insufficient content even with full article"
        if len(result) >= 15:
            break
        log.warning(f"Stage 2 response too short (attempt {attempt + 1}): '{result}'")
    else:
        return None, "response too short after retry"

    # Allow Hebrew, Latin, digits, Polish diacritics (ą ć ę ł ń ó ś ź ż etc.), punctuation
    result = re.sub(r"[^\u0590-\u05FF\uFB1D-\uFB4FA-Za-z0-9\u00C0-\u024F\s,.:;!?%()\"\'-]", "", result).strip()
    if not result:
        return None, "sanitization left empty result"
    if not re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result):
        return None, "no Hebrew characters in result"
    # Allow Latin prefixes (quoted show titles, names, PiS/NATO) before the Hebrew sentence.
    # Drop echoed Polish only when almost no real Hebrew remains after the prefix.
    m_heb = re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result)
    result = result[m_heb.start() :].strip()
    if len(result) < 15:
        return None, "Hebrew too short after removing leading non-Hebrew (likely echoed input)"

    hebrew_re = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")
    latin_re = re.compile(r"[A-Za-z]")
    for token in re.split(r"[\s\-]+", result):  # split on spaces and hyphens
        if hebrew_re.search(token) and latin_re.search(token):
            return None, f"mixed-script word detected: '{token}'"

    word_count = len(result.split())
    if word_count > MAX_SUMMARY_WORDS_HARD:
        return None, f"summary too long ({word_count} words, max {MAX_SUMMARY_WORDS})"

    return result, None


def _telegram_html_anchor(url: str, label: str) -> str:
    """Build <a href> for Telegram HTML; escape entities in URL and label."""
    return (
        f"<a href=\"{html.escape(url, quote=True)}\">"
        f"{html.escape(label, quote=False)}</a>"
    )


def send_to_telegram(message, chat_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id or CHANNEL_ID, "text": message, "parse_mode": "HTML"},
        timeout=10,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        detail = ""
        try:
            detail = resp.json().get("description", "")
        except Exception:
            detail = resp.text[:200]
        log.error("Telegram API error: %s — %s", resp.status_code, detail)
        raise


def notify_admin(article, reason):
    if not ADMIN_TELEGRAM_ID:
        return
    reason_esc = html.escape(str(reason), quote=False)
    title_esc = html.escape(article["title"], quote=False)
    msg = f"⚠️ Skipped article ({reason_esc}):\n<b>{title_esc}</b>\n{article['link']}"
    try:
        send_to_telegram(msg, chat_id=ADMIN_TELEGRAM_ID)
    except Exception as e:
        log.error(f"Failed to notify admin: {e}")


def main():
    conn = init_db()
    client = OpenAI()  # reads OPENAI_API_KEY from env

    if not ADMIN_TELEGRAM_ID:
        log.warning("ADMIN_TELEGRAM_ID is unset — failed articles will not DM you")

    new_articles = get_new_articles(conn)
    new_articles.sort(key=lambda a: a["sort_key"])
    new_articles = deduplicate(conn, new_articles)
    log.info(f"Found {len(new_articles)} new articles after deduplication")

    for article in new_articles:
        try:
            if SPORTS_KEYWORDS.search(article["title"]):
                log.info(f"Skipped (sports keyword): {article['title'][:70]}")
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            hebrew, skip_reason = summarize_in_hebrew(client, article)
            if hebrew is None:
                if skip_reason:
                    log.info(f"Skipped ({skip_reason}): {article['title'][:70]}")
                    notify_admin(article, skip_reason)
                else:
                    log.info(f"Skipped (not Poland-related): {article['title'][:70]}")
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            body = html.escape(hebrew, quote=False)
            footer_label = f"{article['source']} | {article['date']}"
            message = f"{body}\n\n{_telegram_html_anchor(article['link'], footer_label)}"
            send_to_telegram(message)
            conn.execute(
                "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
            )
            conn.commit()
            log.info(f"Sent: {article['title'][:70]}")
            time.sleep(5)
        except Exception as e:
            log.exception("Error on article %s", article["id"])
            try:
                notify_admin(article, f"runtime error: {e}")
            except Exception:
                pass

    conn.close()


if __name__ == "__main__":
    main()
