import html
import logging
import time

from openai import OpenAI

from config import (
    ADMIN_TELEGRAM_ID,
    FUEL_TOURISM_POST_MIN_INTERVAL_SEC,
    SPORTS_KEYWORDS,
    TK_JUDGE_OATH_POST_MIN_INTERVAL_SEC,
    WEATHER_POST_MIN_INTERVAL_SEC,
    is_zeit_jahrgang_index_url,
    should_skip_commercial_clickbait_title,
    skip_admin_notify_for_article,
)
from database import (
    fuel_tourism_post_allowed,
    get_new_articles,
    init_db,
    record_fuel_tourism_post,
    record_tk_judge_oath_post,
    record_weather_post,
    tk_judge_oath_post_allowed,
    weather_post_allowed,
)
from dedup import (
    article_is_de_pl_fuel_tourism_beat,
    article_is_pl_tk_judge_oath_beat,
    article_is_pl_weather_forecast_beat,
    deduplicate,
    record_sent_snapshot,
)
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
            if should_skip_commercial_clickbait_title(article["title"]):
                log.info(f"Skipped (commercial/clickbait title): {article['title'][:70]}")
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            if is_zeit_jahrgang_index_url(article.get("link")):
                log.info(f"Skipped (ZEIT year hub URL): {article['title'][:70]}")
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            if article_is_pl_weather_forecast_beat(article) and not weather_post_allowed(
                conn, WEATHER_POST_MIN_INTERVAL_SEC
            ):
                log.info(
                    "Skipped (weather rate %ds): %s",
                    WEATHER_POST_MIN_INTERVAL_SEC,
                    article["title"][:70],
                )
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            if article_is_de_pl_fuel_tourism_beat(article) and not fuel_tourism_post_allowed(
                conn, FUEL_TOURISM_POST_MIN_INTERVAL_SEC
            ):
                log.info(
                    "Skipped (fuel tourism rate %ds): %s",
                    FUEL_TOURISM_POST_MIN_INTERVAL_SEC,
                    article["title"][:70],
                )
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            if article_is_pl_tk_judge_oath_beat(article) and not tk_judge_oath_post_allowed(
                conn, TK_JUDGE_OATH_POST_MIN_INTERVAL_SEC
            ):
                log.info(
                    "Skipped (TK judge oath rate %ds): %s",
                    TK_JUDGE_OATH_POST_MIN_INTERVAL_SEC,
                    article["title"][:70],
                )
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            hebrew, skip_reason = summarize_in_hebrew(client, session, to, article)
            if hebrew is None:
                if skip_reason:
                    log.info(f"Skipped ({skip_reason}): {article['title'][:70]}")
                    if not skip_admin_notify_for_article(article, skip_reason):
                        notify_admin(
                            session,
                            article,
                            skip_reason,
                            ADMIN_TELEGRAM_ID,
                            to,
                        )
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
            if article_is_pl_weather_forecast_beat(article):
                record_weather_post(conn)
            if article_is_de_pl_fuel_tourism_beat(article):
                record_fuel_tourism_post(conn)
            if article_is_pl_tk_judge_oath_beat(article):
                record_tk_judge_oath_post(conn)
            conn.commit()
            log.info(f"Sent: {article['title'][:70]}")
            time.sleep(5)
        except Exception as e:
            log.exception("Error on article %s", article["id"])
            try:
                if not skip_admin_notify_for_article(article):
                    notify_admin(session, article, f"runtime error: {e}", ADMIN_TELEGRAM_ID, to)
            except Exception:
                pass

    conn.close()


if __name__ == "__main__":
    main()
