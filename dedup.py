"""Conservative exact-copy detection; semantic story memory lives in story_memory."""
import logging
import re
import sqlite3
import time

from config import DEDUP_CONTENT_SUMMARY_CHARS, DEDUP_WINDOW_HOURS, fold_pl

log = logging.getLogger(__name__)


def load_dedup_snapshots(conn: sqlite3.Connection, window_hours: int) -> list:
    cutoff = int(time.time()) - (window_hours * 3600)
    rows = conn.execute(
        "SELECT article_id, title, summary, sort_epoch FROM dedup_recent WHERE sort_epoch >= ?", (cutoff,)
    ).fetchall()
    return [{"id": r[0], "title": r[1], "summary": r[2], "sort_epoch": r[3]} for r in rows]


def save_dedup_snapshot(conn: sqlite3.Connection, article_id: str, title: str, summary: str, epoch: int):
    trunc_summary = (summary or "")[:DEDUP_CONTENT_SUMMARY_CHARS]
    conn.execute(
        "INSERT OR REPLACE INTO dedup_recent (article_id, title, summary, sort_epoch) VALUES (?, ?, ?, ?)",
        (article_id, title or "", trunc_summary, epoch),
    )


def _is_near_duplicate(a: dict, b: dict) -> tuple[bool, str]:
    """Only collapse identical copy here; semantic novelty is checked after translation.

    Shared names and vocabulary cannot tell an approval from a cancellation.
    """
    def normalize(item):
        return tuple(re.sub(r"\s+", " ", str(item.get(key) or "")).strip().casefold()
                     for key in ("title", "summary"))
    left, right = normalize(a), normalize(b)
    identical = bool(left[0]) and left == right
    return identical, "identical copy" if identical else ""


def _is_fuel_tourism_de_pl_border_beat(article: dict) -> bool:
    t = article.get("title", "")
    s = article.get("summary", "")
    bf = fold_pl(f"{t}\n{s}")
    if not any(x in bf for x in ("border", "granic", "tank", "paliw", "kraftstoff", "דלק", "גבול")):
        return False
    poland_anchor = re.search(r"(?:\bpolsk|polce|\bw\s+polsce|przygraniczn|lubieszyn|szczecin|polsko\s*-\s*niemieck|granica.{0,36}(?:pols|niemc)|קו\s+הגבול|בפולין|ובפולין|פולין)", bf, re.I)
    fuel_price = re.search(r"(?:paliw\w*|benzyn|diesel|ceny\s+paliw|stacj\w*\s*paliw|obniz|obniż|znizk|zniż|vat|mieś|podatk|taniej|דלק|מחיר|מעמ|מע\"מ|הנמוך|הפחת)", bf, re.I)
    return bool(poland_anchor and fuel_price)


def article_is_de_pl_fuel_tourism_beat(article: dict) -> bool:
    return _is_fuel_tourism_de_pl_border_beat(article)


def article_is_pl_weather_forecast_beat(article: dict) -> bool:
    bf = fold_pl(f"{article.get('title', '')}\n{article.get('summary', '')}\n{article.get('link', '')}")
    return bool(re.search(r"(?:pogod|prognoz|synop|temperatur|upał|upaly|burz|deszcz|opad|wiatr|IMGW|alert.*meteo|meteo)", bf, re.I))


def article_is_pl_tk_judge_oath_beat(article: dict) -> bool:
    bf = fold_pl(f"{article.get('title', '')}\n{article.get('summary', '')}\n{article.get('link', '')}")
    return bool(re.search(r"trybunal|בית המשפט החוקתי|tk\b|sedzi.*przysieg|przysieg.*sedzi|zaprzysieg|sedzi.*trybun", bf, re.I))


def deduplicate(conn: sqlite3.Connection, articles: list) -> list:
    prior = load_dedup_snapshots(conn, DEDUP_WINDOW_HOURS)
    kept = []
    for article in articles:
        candidates = kept + prior
        for seen in candidates:
            dup, detail = _is_near_duplicate(article, seen)
            if dup:
                log.info("Skipping near-duplicate: '%s' -> matches ID %s (%s)", article.get("title"), seen.get("id"), detail)
                break
        else:
            kept.append(article)
    return kept

