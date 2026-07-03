"""Cross-outlet near-duplicate detection from title + RSS summary."""
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone

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
        # Avoid suppressing unrelated stories that share only generic institutions/verbs.
        "prokuratura",
        "sledztwo",
        "sledztwa",
        "policja",
        "sad",
        "sejm",
        "rzad",
        "ustawa",
        "ustawy",
        "weto",
        "prezydent",
        "premier",
        "minister",
        "ministerstwo",
        "posel",
        "poslowie",
        "senat",
        "polska",
        "polski",
        "polsce",
        "kraj",
        "kraju",
        "decyzja",
        "zmiany",
        "nowe",
        "nowelizacja",
        "chodzi",
        "sprawa",
        "sprawy",
        "zarzuty",
        "zatrzymany",
        "areszt",
        "wypadek",
        "oglosil",
        "poinformowal",
        "szef",
        "lider",
        "partia",
        "wybory",
        "glosowanie",
    )
)


def load_dedup_snapshots(conn: sqlite3.Connection, window_hours: int) -> list:
    cutoff = int(time.time()) - (window_hours * 3600)
    cursor = conn.execute(
        "SELECT article_id, title, summary, sort_epoch FROM dedup_recent WHERE sort_epoch >= ?",
        (cutoff,),
    )
    rows = cursor.fetchall()
    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "title": r[1],
            "summary": r[2],
            "sort_epoch": r[3],
        })
    return results


def save_dedup_snapshot(conn: sqlite3.Connection, article_id: str, title: str, summary: str, epoch: int):
    # Slice summary to reduce long text storage, but keep enough for Dice / overlap testing.
    trunc_summary = (summary or "")[:DEDUP_CONTENT_SUMMARY_CHARS]
    conn.execute(
        "INSERT OR REPLACE INTO dedup_recent (article_id, title, summary, sort_epoch) "
        "VALUES (?, ?, ?, ?)",
        (article_id, title or "", trunc_summary, epoch),
    )


def tokens_from_blob(text: str) -> list:
    if not text:
        return []
    raw_tokens = re.findall(r"\b[a-ząćęłńóśźż0-9_-]{2,24}\b", text.lower())
    res = []
    for t in raw_tokens:
        f = fold_pl(t)
        if f in POLISH_STOPWORDS:
            continue
        res.append(f)
    return res


def _is_near_duplicate(a: dict, b: dict) -> tuple[bool, str]:
    t_a = tokens_from_blob(f"{a.get('title', '')} \n {a.get('summary', '')}")
    t_b = tokens_from_blob(f"{b.get('title', '')} \n {b.get('summary', '')}")

    if not t_a or not t_b:
        return False, ""

    set_a = set(t_a)
    set_b = set(t_b)

    intersection = set_a.intersection(set_b)
    # Filter generic verbs/nouns to measure actual story overlap
    meaningful_intersection = intersection.difference(_GENERIC_ANCHORS)
    meaningful_len = len(meaningful_intersection)

    if meaningful_len >= DEDUP_STRONG_INTERSECTION:
        # Check if they share a specific multi-token name or compound entity (e.g., 'tomasz szmydt')
        non_short = [t for t in meaningful_intersection if len(t) > 3 or t in _DEDUP_SHORT_TOKENS_OK]
        if len(non_short) >= 2:
            return True, f"strong intersection (len={meaningful_len})"

    union_len = len(set_a.union(set_b))
    jaccard = meaningful_len / union_len if union_len > 0 else 0.0

    len_a = len(set_a)
    len_b = len(set_b)
    dice = (2 * meaningful_len) / (len_a + len_b) if (len_a + len_b) > 0 else 0.0

    # Loose cross-check for brief wires that vary slightly in trailing summary words
    smaller_len = min(len_a, len_b)
    overlap_ratio = meaningful_len / smaller_len if smaller_len > 0 else 0.0

    if jaccard >= DEDUP_JACCARD_MIN and dice >= DEDUP_DICE_MIN:
        return True, f"jaccard={jaccard:.2f}, dice={dice:.2f}"

    # If they both carry explicit matching topic tags (e.g., #tram_accident), relax the thresholds
    tags_a = {t for t in t_a if t.startswith("#")}
    tags_b = {t for t in t_b if t.startswith("#")}
    shared_tags = tags_a.intersection(tags_b)

    if shared_tags:
        min_lex = TOPIC_DEDUP_MIN_LEXICAL_WEATHER if "#pl_weather_forecast" in shared_tags else TOPIC_DEDUP_MIN_LEXICAL
        if meaningful_len >= min_lex:
            if jaccard >= DEDUP_JACCARD_RELAXED or dice >= DEDUP_DICE_RELAXED or overlap_ratio >= DEDUP_OVERLAP_LOOSE:
                return True, f"topic tag match {list(shared_tags)} with relaxed metrics"

    if overlap_ratio >= DEDUP_OVERLAP_MIN and meaningful_len >= DEDUP_OVERLAP_MIN_TOKENS:
        # Ensure intersection contains something distinct, not just a single word repeated or broad location
        distinct_meaningful = {t for t in meaningful_intersection if len(t) > 3}
        if len(distinct_meaningful) >= DEDUP_OVERLAP_SET_MIN:
            return True, f"overlap ratio={overlap_ratio:.2f} with {len(distinct_meaningful)} distinct tokens"

    return False, ""


import time


def _is_fuel_tourism_de_pl_border_beat(article: dict) -> bool:
    t = article.get("title", "")
    s = article.get("summary", "")
    bf = fold_pl(f"{t}\n{s}")
    if not ("border" in bf or "granic" in bf or "tank" in bf or "paliw" in bf or "kraftstoff" in bf):
        return False
    poland_anchor = re.search(
        r"(?:"
        r"\bpolsk|polce|\bw\s+polsce|przygraniczn|lubieszyn|szczecin|"
        r"polsko\s*-\s*niemieck|granica.{0,36}(?:pols|niemc)|"
        r"קו\s+הגבול|בפולין|ובפולין|פולין"
        r")",
        bf,
        re.I,
    )
    fuel_price = re.search(
        r"(?:"
        r"paliw\w*|benzyn|diesel|ceny\s+paliw|stacj\w*\\s*paliw|"
        r"obniz|obniż|znizk|zniż|vat|mieś|podatk|taniej|"
        r"דלק|מחיר|מעמ|מע\"מ|הנמוך|הפחת"
        r")",
        bf,
        re.I,
    )
    return bool(poland_anchor and fuel_price)


def deduplicate(conn: sqlite3.Connection, articles: list) -> list:
    window = timedelta(hours=DEDUP_WINDOW_HOURS)
    prior = load_dedup_snapshots(conn, DEDUP_WINDOW_HOURS)
    kept = []
    for article in articles:
        is_duplicate = False
        detail = ""
        candidates = kept + prior
        for seen in candidates:
            dup, detail = _is_near_duplicate(article, seen)
            if dup:
                is_duplicate = True
                break
        if is_duplicate:
            log.info(f"Skipping near-duplicate: '{article.get('title')}' -> matches ID {seen.get('id')} ({detail})")
            continue
        kept.append(article)
    return kept
    
