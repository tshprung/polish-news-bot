import feedparser
import sqlite3
import requests
from openai import OpenAI
import time
import os
import re
import logging
from datetime import datetime, timezone
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


def fetch_article_body(url):
    """Fetch full article text from URL. Returns plain text, stripped of HTML tags."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # Extract text from <p> tags only — avoids nav/ads/footer noise
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", resp.text, re.DOTALL)
        text = " ".join(re.sub(r"<[^>]+>", "", p) for p in paragraphs)
        return text.strip()
    except Exception as e:
        log.warning(f"Could not fetch article body from {url}: {e}")
        return ""


def summarize_in_hebrew(client, article):
    """Returns (hebrew_text, notify_admin).
    hebrew_text is None if the article should be skipped.
    notify_admin is True if admin should be alerted (insufficient content).
    """
    text = article["title"]
    if article["summary"]:
        text += ". " + article["summary"]

    # If RSS gave us little content, fetch the full article body
    if len(text) < 200:
        body = fetch_article_body(article["link"])
        if body:
            text = article["title"] + ". " + body

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=300,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a news editor writing for a Hebrew-language Telegram channel about Poland.\n\n"
                    "Respond with EXACTLY one of these three options — no other text, no reasoning, no preamble:\n"
                    "  1. SKIP — if the article is not about Polish internal affairs, "
                    "does not directly influence Poland, or is about sports.\n"
                    "  2. INSUFFICIENT — if the article is relevant to Poland but the text is too "
                    "incomplete to summarize faithfully.\n"
                    "  3. A Hebrew summary of up to 30 words.\n\n"
                    "Rules for the Hebrew summary:\n"
                    "- Fluent, natural journalistic Hebrew as a native editor would write it.\n"
                    "- Correct grammar, natural Hebrew word order and verb forms. Never translate word-for-word.\n"
                    "- Be faithful to the facts — do not add, remove, or change information.\n"
                    "- Place names (cities, regions, countries) must stay in their original Polish spelling "
                    "(e.g. Warszawa, Kraków, Gdańsk).\n"
                    "- People's names, official project names, and acronyms must stay in their original "
                    "Latin spelling (e.g. Morawiecki, NATO, PiS, 'SAFE 0 proc.').\n"
                    "- Every word must be entirely in one script — never mix Hebrew and Latin within a single word. "
                    "If you don't know the Hebrew word, use the full Latin word instead.\n"
                    "- Common nouns with standard Hebrew equivalents must use Hebrew "
                    "(e.g. synagogue → בית כנסת, church → כנסייה, parliament → פרלמנט).\n"
                    "- No Chinese, Arabic, or any non-Latin/non-Hebrew script.\n"
                    "- Only use real, standard Hebrew words that actually exist — never invent words.\n"
                    "- Output only the summary — no labels, explanations, or reasoning."
                ),
            },
            {
                "role": "user",
                "content": f"Article: {text[:2000]}",
            },
        ],
    )
    # Guard against truncation — a cut-off summary is worse than no summary
    if response.choices[0].finish_reason == "length":
        return None, True
    result = response.choices[0].message.content.strip()
    if result.upper().startswith("SKIP"):
        return None, False
    if result.upper().startswith("INSUF"):
        return None, True
    # Strip non-Hebrew/non-Latin characters (block CJK and other exotic scripts)
    result = re.sub(r"[^\u0590-\u05FF\uFB1D-\uFB4FA-Za-z0-9\s,.:;!?%()\"\'-]", "", result).strip()
    if not result:
        return None, True
    # If result has no Hebrew characters at all, it's a misrouted signal or English explanation
    if not re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result):
        return None, True
    # Detect mixed-script words (Hebrew + Latin in same word)
    hebrew_re = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")
    latin_re = re.compile(r"[A-Za-z]")
    for word in result.split():
        if hebrew_re.search(word) and latin_re.search(word):
            return None, True  # mixed-script word — skip and notify admin
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
    log.info(f"Found {len(new_articles)} new articles")

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
