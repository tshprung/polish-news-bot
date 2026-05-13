import html
import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from config import (
    ADMIN_TELEGRAM_ID,
    FUEL_TOURISM_POST_MIN_INTERVAL_SEC,
    TELEGRAM_LINK_PREVIEW_ENABLED,
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
    get_unsent_email_digest_items,
    init_db,
    mark_email_digest_items_sent,
    record_fuel_tourism_post,
    record_tk_judge_oath_post,
    record_weather_post,
    store_email_digest_item,
    tk_judge_oath_post_allowed,
    weather_post_allowed,
)
from dedup import (
    article_is_de_pl_fuel_tourism_beat,
    article_is_pl_tk_judge_oath_beat,
    article_is_pl_weather_forecast_beat,
    deduplicate,
    load_dedup_snapshots,
    record_sent_snapshot,
    topic_cooldown_filter,
)
from http_util import make_http_session, request_timeout
from email_digest import iso_utc_now, score_and_classify_item, send_email_digest
from summarize import openai_client, summarize_in_hebrew
from telegram_bot import notify_admin, send_to_telegram, telegram_html_anchor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def run_hourly_telegram():
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

    # Topic-level cooldown: if a topic was already sent in the last 24h, suppress updates.
    # Uses only already-sent snapshots (dedup_recent) + earlier items in this run.
    prior_sent = load_dedup_snapshots(conn, 24)
    new_articles, cooled = topic_cooldown_filter(prior_sent, new_articles, window_hours=24)
    for a, reason in cooled:
        log.info("Skipped (topic cooldown 24h, %s): %s", reason, a["title"][:70])
        conn.execute("INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (a["id"],))
    conn.commit()
    log.info(f"{len(new_articles)} remain after topic cooldown")

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
            if TELEGRAM_LINK_PREVIEW_ENABLED:
                message = f"{message}\n{article['link']}"
            send_to_telegram(session, message, timeout=to)
            try:
                try:
                    score, category, region = score_and_classify_item(
                        article.get("title", ""),
                        article.get("source", ""),
                        article.get("link", ""),
                        hebrew,
                    )
                except Exception as e:
                    log.warning("Email-digest scoring failed: %s", e)
                    score, category, region = 0, "other", None
                stored = store_email_digest_item(
                    conn,
                    article,
                    hebrew,
                    importance_score=score,
                    category=category,
                    region=region,
                )
                if stored:
                    log.info("Stored for email digest: %s", article["title"][:70])
                else:
                    log.info("Email digest already stored: %s", article["title"][:70])
            except Exception as e:
                log.warning("Email-digest store failed: %s", e)
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


def run_send_email_digest(slot: str) -> int:
    conn = init_db()
    client: OpenAI = openai_client()

    items = get_unsent_email_digest_items(conn)
    log.info("Email digest unsent items: %d", len(items))

    sent_ids, reason = send_email_digest(client=client, slot=slot, items=items)
    if reason:
        if slot == "midday" and "insufficient" in reason:
            log.info("Email digest %s: %s", slot, reason)
            return 0
        log.info("Email digest %s: %s", slot, reason)
        return 0

    sent_at = iso_utc_now()
    mark_email_digest_items_sent(conn, sent_ids, slot, sent_at)
    conn.commit()
    log.info("Email digest sent: slot=%s items=%d", slot, len(sent_ids))
    return 0


def main():
    if "--send-email-digest" in sys.argv:
        try:
            idx = sys.argv.index("--send-email-digest")
            slot = sys.argv[idx + 1]
        except Exception:
            raise SystemExit("usage: python main.py --send-email-digest <morning|midday|evening>")
        return run_send_email_digest(slot)
    return run_hourly_telegram()


if __name__ == "__main__":
    raise SystemExit(main())
