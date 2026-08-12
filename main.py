import html
import logging
import os
import sys
import time

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
    record_sent_snapshot,
)
from http_util import make_http_session, request_timeout
from email_digest import iso_utc_now, score_and_classify_item, send_email_digest
from summarize import openai_client, summarize_in_hebrew
from telegram_bot import notify_admin, send_to_telegram, telegram_html_anchor
from telegram_digest import send_daily_telegram_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def _telegram_min_score() -> int:
    try:
        return int(os.environ.get("NEWS_TELEGRAM_MIN_SCORE", "40"))
    except ValueError:
        return 40


def _mark_seen(conn, article):
    conn.execute("INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],))
    conn.commit()


def run_ingestion():
    conn = init_db()
    session = make_http_session()
    to = request_timeout()
    client: OpenAI = openai_client()
    min_score = _telegram_min_score()

    if not ADMIN_TELEGRAM_ID:
        log.warning("ADMIN_TELEGRAM_ID is unset — failed articles will not DM you")

    new_articles = get_new_articles(conn)
    new_articles.sort(key=lambda a: a["sort_key"])
    new_articles = deduplicate(conn, new_articles)
    log.info("Found %d new articles after deduplication", len(new_articles))

    for article in new_articles:
        try:
            if SPORTS_KEYWORDS.search(article["title"]):
                log.info("Skipped (sports keyword): %s", article["title"][:70])
                _mark_seen(conn, article)
                continue
            if should_skip_commercial_clickbait_title(article["title"]):
                log.info("Skipped (commercial/clickbait title): %s", article["title"][:70])
                _mark_seen(conn, article)
                continue
            if is_zeit_jahrgang_index_url(article.get("link")):
                log.info("Skipped (ZEIT year hub URL): %s", article["title"][:70])
                _mark_seen(conn, article)
                continue

            immediate_allowed = True
            if article_is_pl_weather_forecast_beat(article) and not weather_post_allowed(
                conn, WEATHER_POST_MIN_INTERVAL_SEC
            ):
                immediate_allowed = False
                log.info("Immediate alert suppressed (weather rate %ds): %s", WEATHER_POST_MIN_INTERVAL_SEC, article["title"][:70])
            if article_is_de_pl_fuel_tourism_beat(article) and not fuel_tourism_post_allowed(
                conn, FUEL_TOURISM_POST_MIN_INTERVAL_SEC
            ):
                immediate_allowed = False
                log.info("Immediate alert suppressed (fuel tourism rate %ds): %s", FUEL_TOURISM_POST_MIN_INTERVAL_SEC, article["title"][:70])
            if article_is_pl_tk_judge_oath_beat(article) and not tk_judge_oath_post_allowed(
                conn, TK_JUDGE_OATH_POST_MIN_INTERVAL_SEC
            ):
                immediate_allowed = False
                log.info("Immediate alert suppressed (TK judge rate %ds): %s", TK_JUDGE_OATH_POST_MIN_INTERVAL_SEC, article["title"][:70])

            hebrew, skip_reason = summarize_in_hebrew(client, session, to, article)
            if hebrew is None:
                if skip_reason:
                    log.info("Skipped (%s): %s", skip_reason, article["title"][:70])
                    if not skip_admin_notify_for_article(article, skip_reason):
                        notify_admin(session, article, skip_reason, ADMIN_TELEGRAM_ID, to)
                else:
                    log.info("Skipped (not Poland-related): %s", article["title"][:70])
                _mark_seen(conn, article)
                continue

            try:
                score, category, region = score_and_classify_item(
                    article.get("title", ""),
                    article.get("source", ""),
                    article.get("link", ""),
                    hebrew,
                )
            except Exception as e:
                log.warning("Importance scoring failed: %s", e)
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
                log.info("Queued for digest (score=%d category=%s): %s", score, category, article["title"][:70])

            if immediate_allowed and score >= min_score:
                body = html.escape(hebrew, quote=False)
                footer_label = f"{article['source']} | {article['date']}"
                message = f"{body}\n\n{telegram_html_anchor(article['link'], footer_label)}"
                if TELEGRAM_LINK_PREVIEW_ENABLED:
                    message = f"{message}\n{article['link']}"
                send_to_telegram(session, message, timeout=to)
                record_sent_snapshot(conn, article)
                if article_is_pl_weather_forecast_beat(article):
                    record_weather_post(conn)
                if article_is_de_pl_fuel_tourism_beat(article):
                    record_fuel_tourism_post(conn)
                if article_is_pl_tk_judge_oath_beat(article):
                    record_tk_judge_oath_post(conn)
                log.info("Sent high-impact alert (score=%d): %s", score, article["title"][:70])
                time.sleep(5)
            else:
                log.info("Held for daily digest (score=%d): %s", score, article["title"][:70])

            conn.commit()
            _mark_seen(conn, article)
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
        log.info("Email digest %s: %s", slot, reason)
        return 0
    mark_email_digest_items_sent(conn, sent_ids, slot, iso_utc_now())
    conn.commit()
    log.info("Email digest sent: slot=%s items=%d", slot, len(sent_ids))
    return 0


def run_send_telegram_digest() -> int:
    conn = init_db()
    session = make_http_session()
    to = request_timeout()
    client: OpenAI = openai_client()
    try:
        send_daily_telegram_digest(conn, client, session, to)
    finally:
        conn.close()
    return 0


def main():
    if "--send-email-digest" in sys.argv:
        try:
            idx = sys.argv.index("--send-email-digest")
            slot = sys.argv[idx + 1]
        except Exception:
            raise SystemExit("usage: python main.py --send-email-digest <morning|midday|evening>")
        return run_send_email_digest(slot)
    if "--send-telegram-digest" in sys.argv:
        return run_send_telegram_digest()
    return run_ingestion()


if __name__ == "__main__":
    raise SystemExit(main())
