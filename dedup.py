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
    _DEDUP_SHORT_TOKENS_OK,
    _TOPIC_DEDUP_TAGS,  # must match every "#…" token added below in tokens_from_blob
    fold_pl,
)

log = logging.getLogger(__name__)


def _dedup_word_shape(wf: str) -> str:
    if not wf.isalpha():
        return wf
    if len(wf) >= 6:
        return wf[:5]
    return wf


def _dedup_folded_blob(article: dict, limit: int = 3500) -> str:
    raw = f"{article['title']} {(article.get('summary') or '')}"
    return fold_pl(unicodedata.normalize("NFC", raw[:limit]))


def _weather_beat_divergent(article: dict, seen: dict) -> bool:
    ba = _dedup_folded_blob(article)
    bb = _dedup_folded_blob(seen)
    weather_hints = (
        "pogod",
        "temperatur",
        "ochlodz",
        "zimn",
        "mroz",
        "deszcz",
        "wiatr",
        "prognoz",
        "opad",
    )
    if not any(h in ba for h in weather_hints) or not any(h in bb for h in weather_hints):
        return False
    storm_markers = (
        "wichur",
        "huragan",
        "nawalnic",
        "nawaln",
        "90 km",
        "90km",
        "predkosc",
        "porywy",
    )
    storm_a = any(x in ba for x in storm_markers)
    storm_b = any(x in bb for x in storm_markers)
    return storm_a != storm_b


def title_words(title):
    words = re.findall(r"[\w]+", re.sub(r"[^\w\s]", " ", title.lower()))
    out = set()
    for x in words:
        folded = fold_pl(x)
        if not folded:
            continue
        if len(folded) >= 5 and folded.isalpha():
            px = folded[:4]
            if len(px) >= 3 and px not in POLISH_STOPWORDS:
                out.add(px)
        wf = _dedup_word_shape(folded)
        if len(wf) > 0:
            out.add(wf)
    return out


def tokens_from_blob(blob: str) -> set:
    blob_n = unicodedata.normalize("NFC", blob.lower())
    words = re.findall(r"[\w]+|\d{4}", blob_n)
    out = set()
    for w in words:
        folded = fold_pl(w)
        if len(folded) < 2:
            continue
        if len(folded) < 3 and not (folded.isdigit() and len(folded) >= 4):
            if folded not in _DEDUP_SHORT_TOKENS_OK:
                continue
        if folded in POLISH_STOPWORDS:
            continue
        if len(folded) >= 5 and folded.isalpha():
            px = folded[:4]
            if len(px) >= 3 and px not in POLISH_STOPWORDS:
                out.add(px)
        wf = _dedup_word_shape(folded)
        if len(wf) < 2:
            continue
        if len(wf) < 3 and not (wf.isdigit() and len(wf) >= 4):
            if wf not in _DEDUP_SHORT_TOKENS_OK:
                continue
        out.add(wf)
    for m in re.finditer(r"(?<!\d)(\d{2,3})(?!\d)", blob_n):
        n = int(m.group(1))
        if n in (20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30) and len(m.group(1)) == 2:
            continue
        if 1900 <= n <= 2099:
            continue
        out.add("#" + m.group(1))

    bf = fold_pl(blob_n[:4000])

    if re.search(r"tramwaj", bf) and re.search(
        r"wykolej|wypadek|wypadku|zderzen|kolizj", bf
    ):
        out.add("#tram_accident")

    if re.search(r"komendant", bf) and re.search(r"policj", bf):
        if re.search(
            r"przemys|kiszk|zatrzyman|podwladn|predkos|km/h|ponad\s+100|"
            r"\b100\b|\b113\b|ciezk\w*\s+nog",
            bf,
        ):
            out.add("#komendant_speed")

    if re.search(r"lodz|lodzk|lodzkiej|\blodzi\b", bf) and re.search(
        r"gillette|strzal|strzel|zabic|zaboj|morder|areszt|"
        r"fabryc|byleg\w*\s+szef|uslyszal\s+zarzut",
        bf,
    ):
        out.add("#lodz_crime_factory")

    if re.search(r"wielkanoc|po\s+wielkanoc|swiat\w*\s+wielk", bf) and re.search(
        r"pogod|temperatur|burz|grzmot|deszcz|snieg|zimn|"
        r"wyjatko|warunk|prognoz|mapy",
        bf,
    ):
        out.add("#easter_weather")

    if re.search(r"\bnato\b", bf) and (
        re.search(r"kellog|kelog", bf)
        or (
            re.search(r"alternatyw", bf)
            and re.search(r"sojusz|general|genera", bf)
        )
        or (
            re.search(r"tchorz|czlowiek\s+trumpa", bf)
            and re.search(r"polsk|polce|polsce", bf)
        )
        or (re.search(r"rubio", bf) and re.search(r"polsk|polce|polsce", bf))
    ):
        out.add("#nato_us_poland")

    return out


def content_tokens(article):
    blob = (
        f"{article['title']} {(article.get('summary') or '')[:DEDUP_CONTENT_SUMMARY_CHARS]}"
    )
    return tokens_from_blob(blob)


def token_similarity(a: set, b: set) -> tuple:
    if not a or not b:
        return 0.0, 0.0, 0
    inter = len(a & b)
    union = len(a | b)
    j = inter / union if union else 0.0
    d = (2 * inter / (len(a) + len(b))) if (a or b) else 0.0
    return j, d, inter


def _overlap_coefficient(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _lexical_token_overlap(ca: set, cs: set) -> int:
    """Intersection size excluding hand-picked topic tags (those need lexical backup)."""
    return len((ca & cs) - _TOPIC_DEDUP_TAGS)


def _is_near_duplicate(article, seen, window: timedelta) -> tuple[bool, str]:
    dt = abs((article["sort_key"] - seen["sort_key"]).total_seconds())
    if dt > window.total_seconds():
        return False, ""

    if _weather_beat_divergent(article, seen):
        return False, ""

    ca, cs = content_tokens(article), content_tokens(seen)
    j, dice, n_inter = token_similarity(ca, cs)
    shared_topics = (ca & cs) & _TOPIC_DEDUP_TAGS
    if shared_topics and _lexical_token_overlap(ca, cs) >= TOPIC_DEDUP_MIN_LEXICAL:
        tag = ",".join(sorted(shared_topics))
        return True, f"topic-tag {tag}"

    oc = _overlap_coefficient(ca, cs)
    mn = min(len(ca), len(cs))

    tw_a, tw_s = title_words(article["title"]), title_words(seen["title"])
    title_frac = (
        len(tw_a & tw_s) / max(len(tw_a), len(tw_s)) if tw_a and tw_s else 0.0
    )

    if j >= DEDUP_JACCARD_MIN or dice >= DEDUP_DICE_MIN:
        return True, f"j={j:.2f} dice={dice:.2f} ({n_inter} shared tokens)"
    if dice >= DEDUP_DICE_RELAXED and n_inter >= 4 and mn >= 5:
        return True, f"dice={dice:.2f} j={j:.2f} ({n_inter} shared, relaxed)"
    if n_inter >= DEDUP_STRONG_INTERSECTION and j >= DEDUP_JACCARD_RELAXED:
        return True, f"j={j:.2f} dice={dice:.2f} ({n_inter} shared tokens)"
    if (
        oc >= DEDUP_OVERLAP_MIN
        and n_inter >= DEDUP_OVERLAP_MIN_TOKENS
        and mn >= DEDUP_OVERLAP_SET_MIN
    ):
        return True, f"overlap={oc:.2f} j={j:.2f} ({n_inter} shared)"
    if oc >= 0.46 and n_inter >= 4 and mn >= 5:
        return True, f"overlap={oc:.2f} j={j:.2f} ({n_inter} shared, tight)"
    if (
        oc >= DEDUP_OVERLAP_LOOSE
        and n_inter >= 4
        and mn >= 4
    ):
        return True, f"overlap={oc:.2f} j={j:.2f} ({n_inter} shared, loose)"
    if title_frac >= 0.58:
        return True, f"title={title_frac:.0%} overlap"

    tta = tokens_from_blob(article["title"])
    tts = tokens_from_blob(seen["title"])
    tj, td, _ = token_similarity(tta, tts)
    if tj >= 0.40 or td >= 0.48:
        return True, f"title-tokens j={tj:.2f}"

    return False, ""


def load_dedup_snapshots(conn: sqlite3.Connection, window_hours: int):
    """Rows recently sent for cross-run dedup (title/summary/sort_key only)."""
    cutoff = int(datetime.now(timezone.utc).timestamp()) - window_hours * 3600
    cur = conn.execute(
        "SELECT article_id, title, summary, sort_epoch FROM dedup_recent WHERE sort_epoch >= ?",
        (cutoff,),
    )
    rows = []
    for article_id, title, summary, sort_epoch in cur.fetchall():
        rows.append({
            "id": article_id,
            "title": title or "",
            "summary": summary or "",
            "link": "",
            "source": "",
            "date": "",
            "sort_key": datetime.fromtimestamp(int(sort_epoch), tz=timezone.utc),
        })
    return rows


def record_sent_snapshot(conn: sqlite3.Connection, article: dict):
    """Persist a sent article so later runs can dedupe against it."""
    sk = int(article["sort_key"].timestamp())
    summary = (article.get("summary") or "")[:DEDUP_CONTENT_SUMMARY_CHARS]
    conn.execute(
        "INSERT OR REPLACE INTO dedup_recent (article_id, title, summary, sort_epoch) "
        "VALUES (?, ?, ?, ?)",
        (article["id"], article["title"], summary, sk),
    )


def deduplicate(conn: sqlite3.Connection, articles: list) -> list:
    window = timedelta(hours=DEDUP_WINDOW_HOURS)
    prior = load_dedup_snapshots(conn, DEDUP_WINDOW_HOURS)
    kept = []
    for article in articles:
        is_duplicate = False
        detail = ""
        candidates = kept + prior
        for seen in candidates:
            dup, detail = _is_near_duplicate(article, seen, window)
            if dup:
                is_duplicate = True
                log.info(
                    "Near-duplicate (%s): '%s' ~ '%s'",
                    detail,
                    article["title"][:65],
                    seen["title"][:65],
                )
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                break
        if not is_duplicate:
            kept.append(article)
    conn.commit()
    return kept
