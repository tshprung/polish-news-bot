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
    _TOPIC_DEDUP_TAGS,  # must match every "#…" token added below in tokens_from_blob
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
        "minister",
        "partia",
        "posel",
        "poslowie",
        "biznes",
        "firma",
        "spolka",
        "pieniadze",
        "podatki",
        "kryzys",
        "afera",
        "skandal",
    )
)


def _dedup_word_shape(wf: str) -> str:
    if not wf.isalpha():
        return wf
    if len(wf) >= 6:
        return wf[:5]
    return wf


def _dedup_folded_blob(article: dict, limit: int = 3500) -> str:
    raw = f"{article['title']} {(article.get('summary') or '')}"
    return fold_pl(unicodedata.normalize("NFC", raw[:limit]))


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

    # IMGW / holiday-period / warning-style forecasts (many outlets, same synoptic beat).
    _wx_phenom = (
        r"pogod|prognoz|temperatur|burz|grzmot|deszcz|snieg|mroz|przymroz|"
        r"zimn|ochlodz|wiatr|oblod|uwaga\s+meteorolog"
    )
    _imgw_or_inst = re.search(
        r"imgw|instytut\s+meteorolog|meteorologiczn", bf
    )
    # Hebrew service copy often omits Polish wx vocab; keep IMGW + local warning cues aligned.
    _he_wx = re.search(
        r"אזהר|סער|סופות|מזג\s*אוויר|המטאורולוגי|המכון\s+המטאורולוגי|"
        r"התקררות|קמ[\"״\u05f4]ש|שירות\s+המזג|בצפון\b|חג\s+הפסחא",
        bf,
    )
    if _imgw_or_inst and _he_wx:
        out.add("#pl_weather_forecast")
    elif re.search(_wx_phenom, bf) and (
        _imgw_or_inst
        or re.search(r"wielkanoc|po\s+wielkanoc|swiat\w*\s+wielk", bf)
        or re.search(r"ostrze\w|alert\w", bf)
        or re.search(r"warunk\w|mapy\s", bf)
        or re.search(r"wichur|huragan|nawaln|90\s*km", bf)
        or re.search(r"\b-?\d{1,2}\s*(?:°|stopni|st\.)\b", bf)
        or re.search(r"temperatur\w*.{0,40}\b-?\d{1,2}\b", bf)
    ):
        out.add("#pl_weather_forecast")

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

    # Baltic coast whale / large cetacean stranding (same beat, different Hebrew taxonomic wording → low raw Jaccard).
    _baltic_whale_loc = (
        r"(?:ostsee|wismar|\bpoel\b|timmendorf|timmendorfer|usedom|"
        r"greifswald|stralsund|rügen|rugen|mecklen|vorpommer|"
        r"bałtyk|baltyk|baltyku|plaza\s+baltyku)"
    )
    _whale_terms = (
        r"(?:\bwal\b|wale\b|wieloryb|wieloryba|"
        r"לוויתן|whales?|orca|dolphin|delfin|"
        r"cachalot|potwal|sei\s*wal|fin\s*wal)"
    )
    if re.search(_whale_terms, bf) and re.search(_baltic_whale_loc, bf):
        out.add("#baltic_whale_stranding")
    elif re.search(r"(?:טימי|timmy)", bf) and re.search(_baltic_whale_loc, bf):
        out.add("#baltic_whale_stranding")

    # Katherina Reiche (CDU) fuel-price / Tempolimit row (HE phrasing splits בנזין vs תחנות דלק vs DE Sprit).
    _reiche_named = r"(?:reiche|רייכה|katherina)"
    _reiche_pol = r"(?:\bcdu\b|wirtschaftsminister(?:in)?|שר(ת)?\s+הכלכלה)"
    _reiche_fuel = (
        r"(?:tankrabatt|tank\s*rabat|\bsprit\b|spritfrust|kraftstoff|benzin|tempolimit|tempo[\s-]*limit|"
        r"בנזין|דלק|תחנות\s+הדלק|מהירות|kraftstoffprei|hohe\s+kraftstoff|הקלות\s+מס)"
    )
    if (
        re.search(_reiche_named, bf)
        and re.search(_reiche_pol, bf)
        and re.search(_reiche_fuel, bf)
    ):
        out.add("#de_reiche_fuel_policy")

    # Constitutional Tribunal (TK): president / Nawrocki judge oath wave — PL vs HE wording + slugs differ a lot.
    _tk_court = (
        r"trybunal\s+konstyt|trybunal\w*\s+konstyt|konstytucyjn.{0,16}trybunal|"
        r"sedzi\w*.{0,40}\btk\b|\btk\b.{0,10}sedzi\w*|"
        r"בית\s+המשפט\s+החוקתי|בית\s+משפט\s+חוקתי|"
        r"\bnawrocki\b.{0,120}\btrybunal\b|\btrybunal\b.{0,120}\bnawrocki\b"
    )
    _tk_oath = (
        r"(?:przysi|zaprzy|zloz|"
        r"שבוע|שבועה|השביע|שופטים|מינוי|מינויים|ששה\s+שופטים|שניים\s+מתוך|"
        r"mebluj|"
        r"tylko.{0,16}(?:dwoch|dwo|dwó|2\s+z\s+sz|2\s+sedz)|"
        r"dwoch\s+z\s+szesc|dwóch\s+z\s+sześci|szesc\w*.{0,12}sedz"
        r")"
    )
    _tk_exec = (
        r"(?:nawrocki|prezydent.{0,12}(?:rp|polsk)|prezydent\s+polsk|"
        r"נשיא\s+פולין|נבוארוקי|נברוקי|נוברוקי)"
    )
    if (
        re.search(_tk_court, bf)
        and re.search(_tk_oath, bf)
        and re.search(_tk_exec, bf)
    ):
        out.add("#pl_tk_judge_oath_row")

    # Poznań: infant with skull injuries / alleged violence; Georgia–Moldova arrests (PL + HE wires).
    if re.search(r"poznan|poznani|פוזנן", bf) and (
        re.search(
            r"niemow|niemowel|5\s*mies|pieciu\s*mies|czaszk|czerep|zlaman|przemoc|"
            r"zatrzyman|gruzj|gruzi|moldow|szpital",
            bf,
        )
        or re.search(
            r"תינוק|חודשים|גולגולת|שבר|אלימות|גאורגיה|מולדובה|נעצר|אושפז",
            bf,
        )
    ):
        out.add("#poznan_infant_abuse_beat")

    # Andrzej Poczobut — Belarus political prisoner / release beat (many outlets, same day).
    if re.search(r"poczobut", bf) and re.search(
        r"(?:"
        r"bialorus|bialorusi|minsk|lukaszen|"
        r"wiezien|wiezni|areszt|uwoln|zwoln|wypuszcz|wolnosci|na\s+wolnos"
        r"|wymian\w{0,14}\s+wiezni|wymian\w{0,14}\s+osob"
        r"|בלארוס|בלרוס|לוקשנקו|כלא|שיחרור|פוצובוט|פוצ'ובוט"
        r")",
        bf,
    ):
        out.add("#pl_by_poczobut_release")

    return out


def content_tokens(article):
    blob = (
        f"{article['title']} {(article.get('summary') or '')[:DEDUP_CONTENT_SUMMARY_CHARS]} "
        f"{(article.get('link') or '')}"
    )
    return tokens_from_blob(blob)


def topic_anchors_from_blob(blob: str) -> set:
    """
    Extract "topic anchors" meant for 24h cooldown (looser than near-dup).

    We keep longer alpha tokens (names, orgs, distinctive nouns) and drop:
    - stopwords
    - very short tokens
    - generic news/legal/politics terms that would cause false "same topic"
    """
    blob_n = unicodedata.normalize("NFC", (blob or "").lower())
    words = re.findall(r"[\w]+", blob_n)
    out = set()
    for w in words:
        folded = fold_pl(w)
        if not folded or not folded.isalpha():
            continue
        if len(folded) < 6:
            continue
        if folded in POLISH_STOPWORDS:
            continue
        if folded in _GENERIC_ANCHORS:
            continue
        out.add(folded)
    return out


def topic_anchors(article: dict) -> set:
    blob = f"{article.get('title', '')} {(article.get('summary') or '')}"
    return topic_anchors_from_blob(blob)


def _topic_tag_dedup_min_lex(shared_topics: set) -> int:
    """Minimum non-tag token overlap for a near-dup / topic-cooldown hit when these #tags intersect."""
    if "#pl_weather_forecast" in shared_topics:
        return TOPIC_DEDUP_MIN_LEXICAL_WEATHER
    if "#baltic_whale_stranding" in shared_topics:
        return TOPIC_DEDUP_MIN_LEXICAL_WEATHER
    if "#de_reiche_fuel_policy" in shared_topics:
        return TOPIC_DEDUP_MIN_LEXICAL_WEATHER
    if "#pl_tk_judge_oath_row" in shared_topics:
        return 0
    if "#poznan_infant_abuse_beat" in shared_topics:
        return TOPIC_DEDUP_MIN_LEXICAL_WEATHER
    if "#pl_by_poczobut_release" in shared_topics:
        return 0
    return TOPIC_DEDUP_MIN_LEXICAL


def _topic_cooldown_hit(article: dict, seen: dict, window: timedelta) -> tuple[bool, str]:
    """
    True when an earlier *sent* item likely covered the same topic within the window.

    This is intentionally looser than _is_near_duplicate: it is meant to prevent
    "updates" on the same story from being posted again within 24h.
    """
    dt = abs((article["sort_key"] - seen["sort_key"]).total_seconds())
    if dt > window.total_seconds():
        return False, ""

    ca, cs = content_tokens(article), content_tokens(seen)
    shared_topics = (ca & cs) & _TOPIC_DEDUP_TAGS
    if shared_topics:
        min_lex = _topic_tag_dedup_min_lex(shared_topics)
        if _lexical_token_overlap(ca, cs) >= min_lex:
            tag = ",".join(sorted(shared_topics))
            return True, f"topic-tag {tag}"

    a = topic_anchors(article)
    b = topic_anchors(seen)
    if not a or not b:
        return False, ""

    inter = a & b
    if not inter:
        return False, ""

    # One very distinctive shared anchor (e.g., Zondacrypto) is enough.
    longest = max((len(x) for x in inter), default=0)
    if longest >= 9:
        return True, f"topic-anchor '{sorted(inter, key=len, reverse=True)[0]}'"

    # Otherwise require at least two shared anchors to reduce flukes.
    if len(inter) >= 2:
        tops = ", ".join(sorted(inter)[:3])
        return True, f"topic-anchors {tops}"

    return False, ""


def topic_cooldown_filter(sent_snapshots: list[dict], articles: list[dict], window_hours: int) -> tuple[list[dict], list[tuple[dict, str]]]:
    """
    Filter out articles whose topic was covered recently (by *sent* snapshots).

    Returns (kept, dropped_with_reason).
    """
    window = timedelta(hours=window_hours)
    kept: list[dict] = []
    dropped: list[tuple[dict, str]] = []
    for article in articles:
        hit = False
        reason = ""
        for seen in sent_snapshots + kept:
            ok, reason = _topic_cooldown_hit(article, seen, window)
            if ok:
                hit = True
                break
        if hit:
            dropped.append((article, reason))
        else:
            kept.append(article)
    return kept, dropped


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

    ca, cs = content_tokens(article), content_tokens(seen)
    j, dice, n_inter = token_similarity(ca, cs)
    shared_topics = (ca & cs) & _TOPIC_DEDUP_TAGS
    if shared_topics:
        min_lex = _topic_tag_dedup_min_lex(shared_topics)
        if _lexical_token_overlap(ca, cs) >= min_lex:
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


def article_is_pl_weather_forecast_beat(article: dict) -> bool:
    """True if title/summary match the #pl_weather_forecast cluster (IMGW / holiday warnings)."""
    blob = f"{article.get('title', '')} {(article.get('summary') or '')}"
    return "#pl_weather_forecast" in tokens_from_blob(blob)


def article_is_pl_tk_judge_oath_beat(article: dict) -> bool:
    """President / Nawrocki + TK judge oath instalment — high-volume multi-outlet beat."""
    return "#pl_tk_judge_oath_row" in content_tokens(article)


def article_is_de_pl_fuel_tourism_beat(article: dict) -> bool:
    """
    German motorists refuelling in Poland (border / VAT / “fuel tourism”) — many near-identical wires.
    Uses title + RSS summary only (PL, DE, or Hebrew phrasing).
    """
    raw = f"{article.get('title', '')} {(article.get('summary') or '')}"
    bf = fold_pl(unicodedata.normalize("NFC", raw.lower()))
    deutsch_motors = re.search(
        r"(?:"
        r"turystyk\w*\s+paliw|paliw\w*\s+turyst|fuel\s+tourism|תיירות\s+דלק|"
        r"kierowc\w*.{0,48}niemiec|niemieck.{0,40}(?:stacj|paliw|tank|kolejk|kolej)|"
        r"z\s+niemiec.{0,48}(?:pols|polsk|paliw|granic|stacj)|"
        r"niemc\w*.{0,32}(?:tank|tanku|stacj|paliw)|"
        r"נהגים\s+גרמנים|גרמנים.{0,56}דלק|תושבי\s+גרמניה.{0,48}(?:פולין|גבול)"
        r")",
        bf,
        re.I,
    )
    if not deutsch_motors:
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
        r"paliw\w*|benzyn|diesel|ceny\s+paliw|stacj\w*\s*paliw|"
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
