"""Telegram send + admin notify."""
import html
import logging

import requests

from config import BOT_TOKEN, CHANNEL_ID

log = logging.getLogger(__name__)


def telegram_html_anchor(url: str, label: str) -> str:
    return (
        f"<a href=\"{html.escape(url, quote=True)}\">"
        f"{html.escape(label, quote=False)}</a>"
    )


def send_to_telegram(session: requests.Session, message, chat_id=None, timeout: tuple = (5, 15)):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = session.post(
        url,
        json={"chat_id": chat_id or CHANNEL_ID, "text": message, "parse_mode": "HTML"},
        timeout=timeout,
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


def notify_admin(session: requests.Session, article, reason, admin_chat_id: str | None, timeout: tuple):
    if not admin_chat_id:
        return
    reason_esc = html.escape(str(reason), quote=False)
    title_esc = html.escape(article["title"], quote=False)
    msg = f"⚠️ Skipped article ({reason_esc}):\n<b>{title_esc}</b>\n{article['link']}"
    try:
        send_to_telegram(session, msg, chat_id=admin_chat_id, timeout=timeout)
    except Exception as e:
        log.error(f"Failed to notify admin: {e}")


__all__ = ["send_to_telegram", "notify_admin", "telegram_html_anchor"]
