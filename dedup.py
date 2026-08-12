"""Cross-outlet near-duplicate detection from title + RSS summary."""
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
import time

from config import (
    DEDUP_CONTENT_SUMMARY_CHARS,
    DEDUP_DICE_MIN,
    DEDUP_DICE_RELAXED,
    DEDUP_JACCARD_MIN,
    DEDUP_JACCARD_RELAXED,
    DEDUP_OVERLAP_LOOSE,
    DEDUP_OVERLAP_MIN,
    DEDUP_OVERLAP_MIN_TOKENS,
    DEDUP_OVERLAP_SET_MIN,
    DEDUP_STRONG_INTERSECTION,
    DEDUP_WINDOW_HOURS,
    POLISH_STOPWORDS,
    TOPIC_DEDUP_MIN_LEXICAL,
    TOPIC_DEDUP_MIN_LEXICAL_WEATHER,
    _DEDUP_SHORT_TOKENS_OK,
    fold_pl,
)

log = logging.getLogger(__name__)

_GENERIC_ANCHORS = frozenset(
    fold_pl(x)
    for x in (
        "prokuratura", "sledztwo", "sledztwa", "policja", "sad", "sejm", "rzad", "ustawa", "ustawy",
        "weto", "prezydent", "premier", "minister", "ministerstwo", "posel", "poslowie", "senat",
        "polska", "polski", "polsce", "kraj", "kraju", "decyzja", "zmiany", "nowe", "nowelizacja",
        "chodzi", "sprawa", "sprawy", "zarzuty", "zatrzymany", "areszt", "wypadek", "oglosil",
        "poinformowal", "szef", "lider", "partia", "wybory", "glosowanie",
    )
)


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


def tokens_from_blob(text: str) -> list:
    if not text:
        return []
    raw_tokens = re.findall(r"\b[a-ząćęłńóśźż0-9_-]{2,24}\b", text.lower())
    return [f for t in raw_tokens if (f := fold_pl(t)) not in POLISH_STOPWORDS]


def _is_near_duplicate(a: dict, b: dict) -> tuple[bool, str]:
    t_a = tokens_from_blob(f"{a.get('title', '')} \n {a.get('summary', '')}")
    t_b = tokens_from_blob(f"{b.get('title', '')} \n {b.get('summary', '')}")
    if not t_a or not t_b:
        return False, ""
    set_a, set_b = set(t_a), set(t_b)
    intersection = set_a.intersection(set_b)
    meaningful_intersection = intersection.difference(_GENERIC_ANCHORS)
    meaningful_len = len(meaningful_intersection)
    if meaningful_len >= DEDUP_STRONG_INTERSECTION:
        non_short = [t for t in meaningful_intersection if len(t) > 3 or t in _DEDUP_SHORT_TOKENS_OK]
        if len(non_short) >= 2:
            return True, f"strong intersection (len={meaningful_len})"
    union_len = len(set_a.union(set_b))
    jaccard = meaningful_len / union_len if union_len else 0.0
    len_a, len_b = len(set_a), len(set_b)
    dice = (2 * meaningful_len) / (len_a + len_b) if (len_a + len_b) else 0.0
    smaller_len = min(len_a, len_b)
    overlap_ratio = meaningful_len / smaller_len if smaller_len else 0.0
    if jaccard >= DEDUP_JACCARD_MIN and dice >= DEDUP_DICE_MIN:
        return True, f"jaccard={jaccard:.2f}, dice={dice:.2f}"
    tags_a = {t for t in t_a if t.startswith("#")}
    tags_b = {t for t in t_b if t.startswith("#")}
    shared_tags = tags_a.intersection(tags_b)
    if shared_tags:
        min_lex = TOPIC_DEDUP_MIN_LEXICAL_WEATHER if "#pl_weather_forecast" in shared_tags else TOPIC_DEDUP_MIN_LEXICAL
        if meaningful_len >= min_lex and (jaccard >= DEDUP_JACCARD_RELAXED or dice >= DEDUP_DICE_RELAXED or overlap_ratio >= DEDUP_OVERLAP_LOOSE):
            return True, f"topic tag match {list(shared_tags)} with relaxed metrics"
    if overlap_ratio >= DEDUP_OVERLAP_MIN and meaningful_len >= DEDUP_OVERLAP_MIN_TOKENS:
        distinct_meaningful = {t for t in meaningful_intersection if len(t) > 3}
        if len(distinct_meaningful) >= DEDUP_OVERLAP_SET_MIN:
            return True, f"overlap ratio={overlap_ratio:.2f} with {len(distinct_meaningful)} distinct tokens"
    return False, ""


def _is_fuel_tourism_de_pl_border_beat(article: dict) -> bool:
    t = article.get("title", "")
    s = article.get("summary", "")
    bf = fold_pl(f"{t}\n{s}")
    if not any(x in bf for x in ("border", "granic", "tank", "paliw", "kraftstoff")):
        return False
    poland_anchor = re.search(r"(?:\bpolsk|polce|\bw\s+polsce|przygraniczn|lubieszyn|szczecin|polsko\s*-\s*niemieck|granica.{0,36}(?:pols|niemc)|קו\s+הגבול|בפולין|ובפולין|פולין)", bf, re.I)
    fuel_price = re.search(r"(?:paliw\w*|benzyn|diesel|ceny\s+paliw|stacj\w*\s*paliw|obniz|obniż|znizk|zniż|vat|mieś|podatk|taniej|דלק|מחיר|מעמ|מע\"מ|הנמוך|הפחת)", bf, re.I)
    return bool(poland_anchor and fuel_price)


def article_is_de_pl_fuel_tourism_beat(article: dict) -> bool:
    return _is_fuel_tourism_de_pl_border_beat(article)


def article_is_pl_weather_forecast_beat(article: dict) -> bool:
    bf = fold_pl(f"{article.get('title', '')}\n{article.get('summary', '')}")
    return bool(re.search(r"(?:pogod|prognoz|synop|temperatur|upał|upaly|burz|deszcz|opad|wiatr|IMGW|alert.*meteo|meteo)", bf, re.I))


def article_is_pl_tk_judge_oath_beat(article: dict) -> bool:
    bf = fold_pl(f"{article.get('title', '')}\n{article.get('summary', '')}")
    return bool(re.search(r"trybunal\s+konstytucyj|tk\b|sedzi.*przysieg|przysieg.*sedzi|zaprzysieg|sedzi.*trybun", bf, re.I))


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
