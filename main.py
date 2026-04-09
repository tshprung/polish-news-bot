import html
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from openai import OpenAI

from config import (
    ADMIN_TELEGRAM_ID,
    CHANNEL_POSTING_MODE,
    DIGEST_MAX_MESSAGE_CHARS,
    DIGEST_WINDOW_MINUTES,
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
from summarize import merge_digest_bullets, openai_client, summarize_in_hebrew
from telegram_bot import notify_admin, send_to_telegram, telegram_html_anchor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

_DIGEST_MODE = CHANNEL_POSTING_MODE == "digest"


def _digest_time_window_utc() -> tuple[datetime, datetime]:
    end_utc = datetime.now(timezone.utc)
    start_utc = end_utc - timedelta(minutes=int(DIGEST_WINDOW_MINUTES))
    return start_utc, end_utc


def _filter_articles_digest_window(articles: list) -> list:
    start_utc, end_utc = _digest_time_window_utc()
    out = [a for a in articles if start_utc <= a["sort_key"] <= end_utc]
    if out and _DIGEST_MODE:
        log.info(
            "Digest window %s .. %s UTC: %d articles (of %d after dedup)",
            start_utc.isoformat(timespec="minutes"),
            end_utc.isoformat(timespec="minutes"),
            len(out),
            len(articles),
        )
    return out


def _digest_header() -> str:
    now_pl = datetime.now(ZoneInfo("Europe/Warsaw"))
    start_pl = now_pl - timedelta(minutes=int(DIGEST_WINDOW_MINUTES))
    r0 = start_pl.strftime("%d.%m.%Y %H:%M")
    r1 = now_pl.strftime("%H:%M")
    return f"<b>סיכום חדשות — פולין</b>\n{r0}–{r1} ורשה"


def split_telegram_digest(header: str, bullets: list[str], max_chars: int) -> list[str]:
    """One or more HTML messages under Telegram length limit."""
    chunks: list[str] = []
    current_lines: list[str] = []
    part = 1

    def chunk_body(lines: list[str]) -> str:
        return "\n".join(lines)

    cont_header = "<b>סיכום חדשות — פולין (המשך)</b>"
    for b in bullets:
        line = "• " + html.escape((b or "").strip(), quote=False)
        h = header if part == 1 else cont_header
        overhead = len(h) + 2
        if overhead + len(line) > max_chars:
            line = line[: max(80, max_chars - overhead - 1)] + "…"
        test_body = chunk_body(current_lines + [line])
        if overhead + len(test_body) > max_chars and current_lines:
            chunks.append(f"{h}\n\n{chunk_body(current_lines)}")
            part += 1
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        h = header if part == 1 else cont_header
        chunks.append(f"{h}\n\n{chunk_body(current_lines)}")
    return chunks


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
    if _DIGEST_MODE:
        new_articles = _filter_articles_digest_window(new_articles)

    pending_digest: list[dict] = []

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
            if _DIGEST_MODE:
                pending_digest.append({"article": article, "hebrew": hebrew})
                log.info(f"Queued for digest: {article['title'][:70]}")
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

    if _DIGEST_MODE and pending_digest:
        try:
            merge_items = [
                {"title": x["article"]["title"], "hebrew": x["hebrew"]}
                for x in pending_digest
            ]
            bullets = merge_digest_bullets(client, merge_items)
            if not bullets:
                bullets = [x["hebrew"].strip() for x in pending_digest if x.get("hebrew")]
            chunks = split_telegram_digest(
                _digest_header(),
                bullets,
                int(DIGEST_MAX_MESSAGE_CHARS),
            )
            for i, chunk in enumerate(chunks):
                send_to_telegram(session, chunk, timeout=to)
                if i + 1 < len(chunks):
                    time.sleep(2)
            for x in pending_digest:
                art = x["article"]
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (art["id"],)
                )
                record_sent_snapshot(conn, art)
                if article_is_pl_weather_forecast_beat(art):
                    record_weather_post(conn)
                if article_is_de_pl_fuel_tourism_beat(art):
                    record_fuel_tourism_post(conn)
                if article_is_pl_tk_judge_oath_beat(art):
                    record_tk_judge_oath_post(conn)
            conn.commit()
            log.info(
                "Sent digest: %d source articles, %d bullets, %d message part(s)",
                len(pending_digest),
                len(bullets),
                len(chunks),
            )
        except Exception as e:
            log.exception("Digest send failed (%s); articles left unmarked for retry", e)
            try:
                if ADMIN_TELEGRAM_ID:
                    send_to_telegram(
                        session,
                        html.escape(f"Digest send failed: {e}", quote=False),
                        chat_id=ADMIN_TELEGRAM_ID,
                        timeout=to,
                    )
            except Exception:
                pass

    conn.close()


if __name__ == "__main__":
    main()
