import feedparser
import sqlite3
import anthropic
import requests
import time
import os
import re
import logging
from pathlib import Path

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
                    new_articles.append({
                        "id": article_id,
                        "title": entry.get("title", ""),
                        "summary": re.sub(r"<[^>]+>", "", entry.get("summary", "")),
                        "source": feed.feed.get("title", feed_url),
                    })
        except Exception as e:
            log.error(f"Failed to fetch {feed_url}: {e}")
    return new_articles


def summarize_in_hebrew(client, article):
    text = article["title"]
    if article["summary"]:
        text += ". " + article["summary"]

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": (
                "Summarize the following Polish news article in Hebrew in up to 20 words. "
                "Be faithful — do not add, remove, or change any information. "
                "Output only the Hebrew summary, nothing else.\n\n"
                f"Article: {text[:600]}"
            ),
        }],
    )
    return response.content[0].text.strip()


def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": CHANNEL_ID, "text": message, "parse_mode": "HTML"},
        timeout=10,
    )
    resp.raise_for_status()


def main():
    conn = init_db()
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    new_articles = get_new_articles(conn)
    log.info(f"Found {len(new_articles)} new articles")

    for article in new_articles:
        try:
            hebrew = summarize_in_hebrew(client, article)
            message = f"{hebrew}\n\n<i>{article['source']}</i>"
            send_to_telegram(message)
            conn.execute(
                "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
            )
            conn.commit()
            log.info(f"Sent: {article['title'][:70]}")
            time.sleep(2)
        except Exception as e:
            log.error(f"Error on article {article['id']}: {e}")

    conn.close()


if __name__ == "__main__":
    main()
