import feedparser
import sqlite3
import requests
from openai import OpenAI
import time
import os
import re
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

FEEDS = [
    "https://tvn24.pl/rss/najwazniejsze.xml",
    "https://www.rmf24.pl/fakty/feed",
    "https://wiadomosci.onet.pl/.feed",
    "https://www.polsatnews.pl/rss/wszystkie.xml",
    "https://wyborcza.pl/pub/rss/najnowsze_wyborcza.xml",
    "https://www.rp.pl/rss_main",
    "https://wydarzenia.interia.pl/feed",
    "https://wiadomosci.wp.pl/rss.xml",
]

SPORTS_KEYWORDS = re.compile(
    r"\b(sport|pi[łl]k|mecz|liga|transfer|fifa|ekstraklasa|kibic|trener|bramk|"
    r"mistrzostwa|turniej|olimp|zawodnik|skoczni|hokej|tenis|koszykówk|siatk[oó]wk|"
    r"lekkoatletyk|wy[śs]cig|formu[łl]a\s*1|tour\s+de|rugby|krykiet|boks|wrestling)\b",
    re.IGNORECASE,
)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = Path(os.environ.get("DB_PATH", "/opt/polish_news/seen.db"))

SYSTEM_PROMPT = (
    "You are a Hebrew-language news editor for a Telegram channel serving Israelis living in Poland.\n\n"
    "CONTEXT:\n"
    "- All input articles are from Polish news sources.\n"
    "- Assume all events occur in Poland unless explicitly stated otherwise.\n"
    "- Assume all people are Polish unless explicitly stated otherwise.\n"
    "- Polish people are פולנים — never write ישראלים when referring to Polish people.\n"
    "- Do NOT infer or change country, nationality, or context.\n\n"
    "TASK:\n"
    "For each article, output EXACTLY ONE of the following:\n\n"
    "1. SKIP\n"
    "   - If the article is about sports\n"
    "   - OR not about Polish internal affairs\n"
    "   - OR has no direct impact on life in Poland\n\n"
    "2. INSUFFICIENT\n"
    "   - If the article is relevant but lacks enough verified details to summarize safely without guessing\n"
    "   - If any key fact is unclear → return INSUFFICIENT\n\n"
    "3. A Hebrew summary (max 30 words, single sentence)\n\n"
    "CRITICAL RULES:\n"
    "- Output ONLY one of the three options. No explanations, no extra text.\n"
    "- SKIP and INSUFFICIENT must appear exactly as written (Latin characters, uppercase).\n"
    "- NEVER hallucinate, infer, or complete missing details.\n\n"
    "HEBREW SUMMARY RULES:\n"
    "- Fluent, natural, journalistic Hebrew — not a literal translation.\n"
    "- Strictly factual: do not add, remove, or reinterpret information.\n"
    "- Focus only on the most important new information.\n\n"
    "LANGUAGE RULES:\n"
    "- Place names remain in original Polish spelling (e.g. Warszawa, Kraków, Gdańsk).\n"
    "- Names, acronyms, and organizations remain in Latin script (e.g. NATO, PiS, Morawiecki, 'SAFE 0 proc.').\n"
    "- Do not mix scripts within a single word — if unsure of a Hebrew word, use the full Latin word instead.\n"
    "- Use standard Hebrew words where they clearly exist "
    "(e.g. parliament → פרלמנט, factory → מפעל, synagogue → בית כנסת, cheater → נוכל).\n"
    "- Use only valid, real Hebrew words — never invent terms.\n"
    "- No non-Hebrew/non-Latin scripts (no Chinese, Arabic, etc.).\n\n"
    "OUTPUT:\n"
    "- Either: SKIP\n"
    "- Or: INSUFFICIENT\n"
    "- Or: a single Hebrew sentence (≤30 words)"
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


def deduplicate(articles):
    """Remove articles whose title is very similar to an earlier article within 2 hours."""
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
                    break
        if not is_duplicate:
            kept.append(article)
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
        # Try <article> block first, fall back to all <p> tags
        article_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
        source = article_match.group(1) if article_match else html
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", source, re.DOTALL)
        text = " ".join(re.sub(r"<[^>]+>", "", p).strip() for p in paragraphs if len(p) > 40)
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
    """Returns (hebrew_text, notify_admin).
    hebrew_text is None if the article should be skipped.
    notify_admin is True if admin should be alerted (insufficient content).
    """
    text = article["title"]
    if article["summary"]:
        text += ". " + article["summary"]

    # Always fetch the full article body for best summarization quality
    body = fetch_article_body(article["link"])
    fetched_body = bool(body)
    if body:
        text = article["title"] + ". " + body

    # Stage 1: classify with cheap model — only filters obvious non-Poland/sports
    decision = classify(client, text)
    if decision == "SKIP":
        return None, False

    def call_stage2(t):
        return client.chat.completions.create(
            model="gpt-4o",
            max_tokens=300,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Article: {t[:2000]}"},
            ],
        )

    # Stage 2: summarize with powerful model
    response = call_stage2(text)
    if response.choices[0].finish_reason == "length":
        return None, True
    result = response.choices[0].message.content.strip()

    # If INSUFFICIENT and we haven't fetched the full body yet, try fetching and retry once
    if (result.upper().startswith("INSUF") or result.startswith("לא מספיק")) and not fetched_body:
        body = fetch_article_body(article["link"])
        if body:
            text = article["title"] + ". " + body
            response = call_stage2(text)
            if response.choices[0].finish_reason == "length":
                return None, True
            result = response.choices[0].message.content.strip()

    if result.upper().startswith("SKIP") or result.startswith("סקיפ"):
        return None, False
    if result.upper().startswith("INSUF") or result.startswith("לא מספיק"):
        return None, True
    if len(result) < 15:
        return None, True

    # Allow Hebrew, Latin, digits, Polish diacritics (ą ć ę ł ń ó ś ź ż etc.), punctuation
    result = re.sub(r"[^\u0590-\u05FF\uFB1D-\uFB4FA-Za-z0-9\u00C0-\u024F\s,.:;!?%()\"\'-]", "", result).strip()
    if not result:
        return None, True
    if not re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result):
        return None, True

    hebrew_re = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")
    latin_re = re.compile(r"[A-Za-z]")
    for word in result.split():
        if hebrew_re.search(word) and latin_re.search(word):
            return None, True

    return result, False


def send_to_telegram(message, chat_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id or CHANNEL_ID, "text": message, "parse_mode": "HTML"},
        timeout=10,
    )
    resp.raise_for_status()


def notify_admin(article):
    if not ADMIN_TELEGRAM_ID:
        return
    msg = (
        f"⚠️ Could not summarize article (insufficient content):\n"
        f"<b>{article['title']}</b>\n"
        f"{article['link']}"
    )
    try:
        send_to_telegram(msg, chat_id=ADMIN_TELEGRAM_ID)
    except Exception as e:
        log.error(f"Failed to notify admin: {e}")


def main():
    conn = init_db()
    client = OpenAI()  # reads OPENAI_API_KEY from env

    new_articles = get_new_articles(conn)
    new_articles.sort(key=lambda a: a["sort_key"])
    new_articles = deduplicate(new_articles)
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
            hebrew, should_notify = summarize_in_hebrew(client, article)
            if hebrew is None:
                if should_notify:
                    log.info(f"Skipped (insufficient content): {article['title'][:70]}")
                    notify_admin(article)
                else:
                    log.info(f"Skipped (not Poland-related): {article['title'][:70]}")
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            message = f"{hebrew}\n\n<a href=\"{article['link']}\">{article['source']} | {article['date']}</a>"
            send_to_telegram(message)
            conn.execute(
                "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
            )
            conn.commit()
            log.info(f"Sent: {article['title'][:70]}")
            time.sleep(5)
        except Exception as e:
            log.error(f"Error on article {article['id']}: {e}")

    conn.close()


if __name__ == "__main__":
    main()
