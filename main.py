import feedparser
import sqlite3
import anthropic
import requests
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
]

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
                        "title": entry.get("title", ""),
                        "summary": re.sub(r"<[^>]+>", "", entry.get("summary", "")),
                        "source": feed.feed.get("title", feed_url),
                        "date": dt_local.strftime("%d.%m.%Y %H:%M"),
                        "sort_key": dt,
                    })
        except Exception as e:
            log.error(f"Failed to fetch {feed_url}: {e}")
    return new_articles


def summarize_in_hebrew(client, article):
    """Returns (hebrew_text, notify_admin).
    hebrew_text is None if the article should be skipped.
    notify_admin is True if admin should be alerted (insufficient content).
    """
    text = article["title"]
    if article["summary"]:
        text += ". " + article["summary"]

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=160,
        messages=[{
            "role": "user",
            "content": (
                "You are a news editor writing for a Hebrew-language Telegram channel about Poland.\n"
                "First, decide: is this article about Polish internal affairs, or does it directly influence Poland? "
                "If NO, respond with exactly: SKIP\n"
                "If YES but the provided text is too incomplete to summarize faithfully, "
                "respond with exactly: INSUFFICIENT\n"
                "Otherwise write a summary in up to 40 words. "
                "Write in fluent, natural journalistic Hebrew — as a native Hebrew news editor would phrase it, "
                "using correct grammar, natural word order, and proper Hebrew verb forms. "
                "Do not translate word-for-word from Polish or English. "
                "Be faithful to the facts — do not add, remove, or change any information. "
                "CRITICAL: Your output must contain ONLY Hebrew script characters and spaces. "
                "Absolutely no Latin letters, digits, Chinese, Arabic, or any other script. "
                "Never output explanations or English text under any circumstances. "
                "Output only the Hebrew summary, nothing else.\n\n"
                f"Article: {text[:600]}"
            ),
        }],
    )
    result = response.content[0].text.strip()
    if result == "SKIP":
        return None, False
    if result == "INSUFFICIENT":
        return None, True
    # Strip any non-Hebrew characters (keep Hebrew block + niqqud + spaces/punctuation)
    result = re.sub(r"[^\u0590-\u05FF\uFB1D-\uFB4F\s,.:;!?\"'-]", "", result).strip()
    if not result:
        return None, True  # something slipped through — treat as insufficient
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
        f"{article['id']}"
    )
    try:
        send_to_telegram(msg, chat_id=ADMIN_TELEGRAM_ID)
    except Exception as e:
        log.error(f"Failed to notify admin: {e}")


def main():
    conn = init_db()
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    new_articles = get_new_articles(conn)
    new_articles.sort(key=lambda a: a["sort_key"])
    log.info(f"Found {len(new_articles)} new articles")

    for article in new_articles:
        try:
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
            message = f"{hebrew}\n\n<i>{article['source']} | {article['date']}</i>"
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
