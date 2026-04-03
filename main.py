import html
import logging
import time

from openai import OpenAI

from config import ADMIN_TELEGRAM_ID, SPORTS_KEYWORDS
from database import get_new_articles, init_db
from dedup import deduplicate, record_sent_snapshot
from http_util import make_http_session, request_timeout
from summarize import openai_client, summarize_in_hebrew
from telegram_bot import notify_admin, send_to_telegram, telegram_html_anchor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def main():
    conn = init_db()
    session = make_http_session()
    to = request_timeout()
    client: OpenAI = openai_client()

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
            hebrew, skip_reason = summarize_in_hebrew(client, session, to, article)
            if hebrew is None:
                if skip_reason:
                    log.info(f"Skipped ({skip_reason}): {article['title'][:70]}")
                    notify_admin(session, article, skip_reason, ADMIN_TELEGRAM_ID, to)
                else:
                    log.info(f"Skipped (not Poland-related): {article['title'][:70]}")
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            body = html.escape(hebrew, quote=False)
            footer_label = f"{article['source']} | {article['date']}"
            message = f"{body}\n\n{telegram_html_anchor(article['link'], footer_label)}"
            send_to_telegram(session, message, timeout=to)
            conn.execute(
                "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
            )
            record_sent_snapshot(conn, article)
            conn.commit()
            log.info(f"Sent: {article['title'][:70]}")
            time.sleep(5)
        except Exception as e:
            log.exception("Error on article %s", article["id"])
            try:
                notify_admin(session, article, f"runtime error: {e}", ADMIN_TELEGRAM_ID, to)
            except Exception:
                pass

    conn.close()


if __name__ == "__main__":
    main()
