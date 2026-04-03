import feedparser
import sqlite3
import requests
from openai import OpenAI
import html
import json
import time
import os
import re
import logging
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

FEEDS = [
    # General national (headlines from several editorial lenses)
    "https://tvn24.pl/rss/najwazniejsze.xml",
    "https://www.rmf24.pl/fakty/feed",
    "https://wiadomosci.onet.pl/.feed",
    "https://www.polsatnews.pl/rss/wszystkie.xml",
    "https://wydarzenia.interia.pl/feed",
    "https://wiadomosci.wp.pl/rss.xml",
    "https://wiadomosci.gazeta.pl/pub/rss/wiadomosci.xml",
    # PAP wire — domestic politics/society + economy (factual backbone; expect overlap with portals)
    "https://pap-mediaroom.pl/kategoria/polityka-i-społeczeństwo/rss.xml",
    "https://pap-mediaroom.pl/kategoria/biznes-i-finanse/rss.xml",
    # wyborcza.pl removed — paywalled, article body not accessible
    # rp.pl removed — JS-rendered content, not accessible via static scraping
]

# Drop near-duplicate stories across outlets (different headlines, same event).
DEDUP_WINDOW_HOURS = 8
DEDUP_JACCARD_MIN = 0.15
DEDUP_DICE_MIN = 0.38
DEDUP_DICE_RELAXED = 0.32  # with enough shared tokens; same beat, different wording
DEDUP_STRONG_INTERSECTION = 5  # with Jaccard >= DEDUP_JACCARD_RELAXED
DEDUP_JACCARD_RELAXED = 0.11
# Same event, different headline (different politician quoted): high overlap on smaller set
DEDUP_OVERLAP_MIN = 0.28  # |A∩B| / min(|A|, |B|)
DEDUP_OVERLAP_MIN_TOKENS = 4
DEDUP_OVERLAP_SET_MIN = 5  # min(|A|, |B|) must be at least this for overlap rule
DEDUP_OVERLAP_LOOSE = 0.26  # last-chance: same beat, very different phrasing
DEDUP_CONTENT_SUMMARY_CHARS = 4000  # wires often only share facts deep in RSS body

# Two-letter tokens are usually noise; keep abbreviations that headline many EU/Poland wires.
_DEDUP_SHORT_TOKENS_OK = frozenset({"ke", "tk", "ue", "lr"})

_PL_FOLD = str.maketrans(
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
    "acelnoszzacelnoszz",
)


def _fold_pl(token: str) -> str:
    """Fold Polish diacritics so sędziów / sedziow count as overlap."""
    return unicodedata.normalize("NFC", token).translate(_PL_FOLD).lower()


def _dedup_word_shape(wf: str) -> str:
    """Merge inflections for dedup (Pfizer/pfizera, zawiesz/zawieszony, Kłodzko/Kłodzku)."""
    if not wf.isalpha():
        return wf
    # Single 5-char stem for 6+ avoids 7-letter vs 8+ getting different slice lengths
    # (e.g. zawiesz vs zawieszony were zawie vs zawies and never matched).
    if len(wf) >= 6:
        return wf[:5]
    return wf


def _dedup_folded_blob(article: dict, limit: int = 3500) -> str:
    raw = f"{article['title']} {(article.get('summary') or '')}"
    return _fold_pl(unicodedata.normalize("NFC", raw[:limit]))


def _weather_beat_divergent(article: dict, seen: dict) -> bool:
    """Same RSS window can carry Friday cold + Monday storm; do not merge those."""
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
    storm_a = any(
        x in ba
        for x in (
            "wichur",
            "huragan",
            "nawalnic",
            "nawaln",
            "90 km",
            "90km",
            "predkosc",
            "porywy",
        )
    )
    storm_b = any(
        x in bb
        for x in (
            "wichur",
            "huragan",
            "nawalnic",
            "nawaln",
            "90 km",
            "90km",
            "predkosc",
            "porywy",
        )
    )
    return storm_a != storm_b


POLISH_STOPWORDS = frozenset(
    _fold_pl(w)
    for w in """
    a albo ani oraz jednak natomiast więc dlatego ponadto przy tym
    i lub czy też także również nadal już jeszcze bardzo bardziej
    nie tak tylko może pewnie
    to ta ten tego tej tych tym tą tę tam tamten
    że żeby żebym ze który która które których którym którymi
    jak jaki jaka jakie jakiś jakaś jakieś jakich jakim
    co czym czego
    kiedy gdy gdzie dokąd skąd dlaczego czemu
    kto kogo komu kim
    ci te jej jego ich im go mu ją nią nimi
    nas nasz wasz swój swoje swoją mój twój nasi nasze wasze
    być jest są był była było były będzie mogą ma mają musi muszą
    się sobie siebie sobą
    swoim
    mnie mi mną tobie cię ci tobą
    pod nad między bez wokół przez dla przeciw ku od do ze z za na w we u o
    po przy
    takie samo samą samym samych sam sama sami same
    dzisiaj dziś wczoraj jutro dnia godz min sek
    www http https com pl
    video zobacz czytaj więcej foto zdjęcie
    """.split()
)

SPORTS_KEYWORDS = re.compile(
    r"\b(sport|pi[łl]k|mecz|liga|transfer|fifa|ekstraklasa|kibic|trener|bramk|"
    r"mistrzostwa|turniej|olimp|zawodnik|skoczni|hokej|tenis|koszykówk|siatk[oó]wk|"
    r"lekkoatletyk|wy[śs]cig|formu[łl]a\s*1|tour\s+de|rugby|krykiet|boks|wrestling)\b",
    re.IGNORECASE,
)

PAYWALLED_DOMAINS = {"pro.rp.pl", "rp.pl", "wyborcza.pl"}

# Summaries: align model instruction, validation cap, and user-facing expectation.
MAX_SUMMARY_WORDS = 40
MAX_SUMMARY_WORDS_HARD = 48  # small slack above prompt limit (counts Latin names as words)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = Path(os.environ.get("DB_PATH", "/opt/polish_news/seen.db"))

SYSTEM_PROMPT = (
    "You are a Hebrew news editor for a Telegram channel.\n\n"
    "AUDIENCE\n"
    "- Hebrew speakers who live in Poland; they follow Polish national news.\n"
    "- Summarize in Hebrew so they grasp the story quickly; keep Polish context where needed.\n\n"
    "CONTEXT\n"
    "- Articles are from Polish media.\n"
    "- Assume Poland unless stated otherwise.\n"
    "- Polish people = פולנים (never ישראלים).\n\n"
    "TASK\n"
    "Return exactly one:\n"
    "1. SKIP — sports / not Polish internal affairs / no impact on life in Poland\n"
    "2. INSUFFICIENT — missing or unclear key facts\n"
    "3. Hebrew summary — one or two short sentences, "
    f"≤{MAX_SUMMARY_WORDS} words total\n\n"
    "RULES\n"
    "- Output only one option (no explanations, no preamble in Polish or English).\n"
    "- First significant output for a Hebrew summary must be Hebrew text "
    "(Latin only inside the sentence for names, places, acronyms).\n"
    "- SKIP / INSUFFICIENT must match exactly.\n"
    "- INSUFFICIENT only when the text adds almost no usable facts beyond the title.\n"
    "- Short wires and brief reports: if place, event, and outcome are stated, summarize.\n"
    "- Interviews/podcasts: you may summarize who said what and on which topic, factually.\n"
    "- Accidents involving minors: state facts dryly, no graphic or sensational detail.\n"
    "- No hallucinations or assumptions.\n"
    "- Do not repeat or quote the article; paraphrase.\n"
    "- If the headline is clear → summarize.\n\n"
    "HEBREW\n"
    "- Natural, fluent, factual.\n"
    "- Keep Polish place names (e.g. Warszawa).\n"
    "- Keep names/orgs in Latin (e.g. NATO, PiS).\n"
    "- No mixed scripts within a single word.\n"
    "- Use standard Hebrew words only.\n\n"
    "OUTPUT\n"
    f"SKIP / INSUFFICIENT / ≤{MAX_SUMMARY_WORDS}-word Hebrew summary"
)


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_articles "
        "(id TEXT PRIMARY KEY, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("DELETE FROM seen_articles WHERE sent_at < datetime('now', '-7 days')")
    conn.commit()
    return conn


def get_new_articles(conn):
    new_articles = []
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                article_id = entry.get("id") or entry.get("link")
                if not article_id:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM seen_articles WHERE id = ?", (article_id,)
                ).fetchone()
                if not exists:
                    published = entry.get("published_parsed")
                    if published:
                        dt = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        dt = datetime.now(timezone.utc)
                    dt_local = dt.astimezone(ZoneInfo("Europe/Warsaw"))
                    new_articles.append({
                        "id": article_id,
                        "link": entry.get("link") or article_id,
                        "title": entry.get("title", ""),
                        "summary": re.sub(r"<[^>]+>", "", entry.get("summary", "")),
                        "source": feed.feed.get("title", feed_url),
                        "date": dt_local.strftime("%d.%m.%Y %H:%M"),
                        "sort_key": dt,
                    })
        except Exception as e:
            log.error(f"Failed to fetch {feed_url}: {e}")
    return new_articles


def title_words(title):
    """Return a set of folded words from a title (diacritics normalized for dedup)."""
    words = re.findall(r"[\w]+", re.sub(r"[^\w\s]", " ", title.lower()))
    out = set()
    for x in words:
        wf = _fold_pl(x)
        if not wf:
            continue
        wf = _dedup_word_shape(wf)
        if len(wf) > 0:
            out.add(wf)
    return out


def tokens_from_blob(blob: str) -> set:
    """Content words for similarity: folded, length ≥3, stopwords removed."""
    blob_n = unicodedata.normalize("NFC", blob.lower())
    words = re.findall(r"[\w]+|\d{4}", blob_n)
    out = set()
    for w in words:
        wf = _fold_pl(w)
        if len(wf) < 2:
            continue
        if len(wf) < 3 and not (wf.isdigit() and len(wf) >= 4):
            if wf not in _DEDUP_SHORT_TOKENS_OK:
                continue
        if wf in POLISH_STOPWORDS:
            continue
        wf = _dedup_word_shape(wf)
        if len(wf) < 2:
            continue
        if len(wf) < 3 and not (wf.isdigit() and len(wf) >= 4):
            if wf not in _DEDUP_SHORT_TOKENS_OK:
                continue
        out.add(wf)
    # Standout counts in wires (e.g. 64 mln dawek) — 2–3 digits, not a calendar year
    for m in re.finditer(r"(?<!\d)(\d{2,3})(?!\d)", blob_n):
        n = int(m.group(1))
        if n in (20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30) and len(m.group(1)) == 2:
            continue  # likely day-of-month in dates
        if 1900 <= n <= 2099:
            continue
        out.add("#" + m.group(1))
    return out


def content_tokens(article) -> set:
    blob = (
        f"{article['title']} {(article.get('summary') or '')[:DEDUP_CONTENT_SUMMARY_CHARS]}"
    )
    return tokens_from_blob(blob)


def token_similarity(a: set, b: set) -> tuple:
    """Return (Jaccard, Dice, |intersection|)."""
    if not a or not b:
        return 0.0, 0.0, 0
    inter = len(a & b)
    union = len(a | b)
    j = inter / union if union else 0.0
    d = (2 * inter / (len(a) + len(b))) if (a or b) else 0.0
    return j, d, inter


def _overlap_coefficient(a: set, b: set) -> float:
    """Szymkiewicz–Simpson: how much of the smaller article's vocabulary is shared."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _is_near_duplicate(article, seen, window: timedelta) -> tuple[bool, str]:
    dt = abs((article["sort_key"] - seen["sort_key"]).total_seconds())
    if dt > window.total_seconds():
        return False, ""

    if _weather_beat_divergent(article, seen):
        return False, ""

    ca, cs = content_tokens(article), content_tokens(seen)
    j, dice, n_inter = token_similarity(ca, cs)
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

    # Title-only content tokens: same story, different lead phrasing in RSS summary
    tta = tokens_from_blob(article["title"])
    tts = tokens_from_blob(seen["title"])
    tj, td, tn = token_similarity(tta, tts)
    if tj >= 0.40 or td >= 0.48:
        return True, f"title-tokens j={tj:.2f}"

    return False, ""


def deduplicate(conn, articles):
    """Skip articles that match an earlier one within DEDUP_WINDOW_HOURS (cross-outlet).

    Uses title + RSS summary tokens (Jaccard / Dice), not headline identity alone.
    Dropped duplicates are marked seen so the same RSS id is not retried every run.
    """
    window = timedelta(hours=DEDUP_WINDOW_HOURS)
    kept = []
    for article in articles:
        is_duplicate = False
        detail = ""
        for seen in kept:
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


def _article_body_from_jsonld(page_html: str) -> str:
    """Pull articleBody from schema.org JSON-LD (used by Gazeta.pl and many CMSs)."""
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            candidates = data.get("@graph", [data])
        elif isinstance(data, list):
            candidates = data
        else:
            continue
        for item in candidates:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if isinstance(t, list):
                types = t
            elif isinstance(t, str):
                types = [t]
            else:
                types = []
            if not any(x in ("NewsArticle", "Article") for x in types):
                continue
            body = item.get("articleBody")
            if isinstance(body, str) and len(body.strip()) > 150:
                return body.strip()
    return ""


def _article_body_from_dom(stripped_html: str) -> str:
    """Sites like Onet (Astro) put copy in div.ods-a-body-text, not <p>; JSON-LD may omit articleBody."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""

    def cleanup_root(r):
        for sel in (
            "ad-default",
            "aside",
            ".ods-m-bullet-list",
            ".ods-o-authorship-bottom",
            ".ods-c-share-buttons-wrapper",
            ".ods-m-socials-stream",
            ".ods-m-tts-player",
            ".ods-o-authorship-top",
            ".ods-c-actionbar",
            ".ods-c-modal-premium",
            ".ods-o-onetchat-widget-chat",
        ):
            for tag in r.select(sel):
                tag.decompose()

    soup = BeautifulSoup(stripped_html, "html.parser")
    for jid in ("pianoOffer", "pianoInfo"):
        for tag in soup.find_all(id=jid):
            tag.decompose()

    root = soup.select_one("[class*='ods-article-body']")
    if root is None:
        root = soup.find("article")
    if root is None:
        return ""
    scope = root

    cleanup_root(scope)
    block = scope.get_text(separator="\n", strip=True)
    lines = [ln for ln in (x.strip() for x in block.splitlines()) if len(ln) > 12]
    primary = "\n".join(lines)

    # Real copy is usually in <p>; full article get_text also pulls dates, share lines, side teasers (WP.pl).
    paragraph_chunks = []
    for p in scope.find_all("p"):
        if p.find_parent("aside"):
            continue
        chunk = p.get_text(separator=" ", strip=True)
        if len(chunk) >= 20:
            paragraph_chunks.append(chunk)
    paragraph_body = "\n".join(paragraph_chunks)

    # Onet podcast/premium: copy is often only in div.ods-a-body-text; also avoids piano/UI drowning the start.
    body_chunks = []
    for div in scope.select("div.ods-a-body-text"):
        chunk = div.get_text(separator=" ", strip=True)
        if len(chunk) > 25:
            body_chunks.append(chunk)
    fallback = "\n".join(body_chunks)

    best = primary
    if len(fallback) > len(best):
        best = fallback
    if len(paragraph_body) >= 180:
        if len(paragraph_body) > len(best):
            best = paragraph_body
        elif best is primary and len(primary) > len(paragraph_body) + 80:
            best = paragraph_body
    return best


def fetch_article_body(url):
    """Fetch full article text from URL. Returns plain text, stripped of HTML tags."""
    paywall_signals = [
        "zaloguj się",
        "zarejestruj się",
        "prenumerata",
        "subskrypcja",
        "kup dostęp",
        "płatna treść",
    ]
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=10, headers=headers)
        resp.raise_for_status()
        page_html = resp.text

        text = _article_body_from_jsonld(page_html)
        if len(text) >= 200:
            if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return ""
            log.info(f"Fetched {len(text)} chars (JSON-LD) from {url}")
            return text

        # Strip scripts/styles so <p> regex cannot match inside JS bundles (Gazeta etc.).
        stripped = re.sub(
            r"<script\b[^>]*>.*?</script>", " ", page_html, flags=re.DOTALL | re.IGNORECASE
        )
        stripped = re.sub(
            r"<style\b[^>]*>.*?</style>", " ", stripped, flags=re.DOTALL | re.IGNORECASE
        )

        text = _article_body_from_dom(stripped)
        if len(text) >= 250:
            if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return ""
            log.info(f"Fetched {len(text)} chars (DOM) from {url}")
            return text.strip()

        def extract_paragraphs(source):
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", source, re.DOTALL)
            return " ".join(
                re.sub(r"<[^>]+>", "", p).strip() for p in paragraphs if len(p) > 40
            )

        article_match = re.search(r"<article[^>]*>(.*?)</article>", stripped, re.DOTALL)
        if not article_match:
            article_match = re.search(
                r'<section[^>]*class="[^"]*\bart_content\b[^"]*"[^>]*>(.*?)</section>',
                stripped,
                re.DOTALL | re.IGNORECASE,
            )
        text = ""
        if article_match:
            text = extract_paragraphs(article_match.group(1)).strip()
        if len(text) < 300:
            text = extract_paragraphs(stripped).strip()
        if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
            log.warning(f"Paywall detected at {url}, ignoring fetched content")
            return ""
        log.info(f"Fetched {len(text)} chars from {url}")
        return text.strip()
    except Exception as e:
        log.warning(f"Could not fetch article body from {url}: {e}")
        return ""


CLASSIFY_PROMPT = (
    "You are a filter for a news channel about Poland.\n"
    "All articles come from Polish news sources.\n\n"
    "Reply with SKIP only if the article is clearly about:\n"
    "- Foreign news with no connection to Poland\n"
    "- Sports\n\n"
    "Reply with GO for everything else — including Polish politics, crime, economy, society, "
    "weather, accidents, and any story where Poland or Polish people are involved.\n"
    "When in doubt, reply GO.\n\n"
    "Reply with only one word: SKIP or GO."
)


def classify(client, text):
    """Stage 1: cheap model decides SKIP / GO."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=5,
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": f"Article: {text[:500]}"},
        ],
    )
    result = response.choices[0].message.content.strip().upper()
    if result.startswith("SKIP") or "סקיפ" in result:
        return "SKIP"
    return "GO"


def summarize_in_hebrew(client, article):
    """Returns (hebrew_text, skip_reason).
    hebrew_text is None if the article should be skipped.
    skip_reason is None on success, or a string describing why it was skipped.
    """
    rss_text = article["title"]
    if article["summary"]:
        rss_text += ". " + article["summary"]

    # Skip fetching for known paywalled domains
    domain = urlparse(article["link"]).netloc.lstrip("www.")
    if domain in PAYWALLED_DOMAINS:
        return None, f"paywalled domain ({domain})"

    # Always fetch the full article body
    body = fetch_article_body(article["link"])
    text = (article["title"] + ". " + body) if body else rss_text
    body_available = bool(body)

    # Stage 1: classify with cheap model — only filters obvious non-Poland/sports
    decision = classify(client, text)
    if decision == "SKIP":
        return None, None  # silent skip, not Poland-related

    # Longer slice: Onet UI/piano can eat the first ~2k chars; interviews need more context.
    stage2_limit = 4000

    def call_stage2(user_blob: str):
        return client.chat.completions.create(
            model="gpt-4o",
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_blob},
            ],
        )

    insufficient_retry_note = (
        "Note: Summarize any concrete facts in the text, even if the piece is short. "
        "Broadcast schedules (who is a guest on which Polish TV or radio show, program titles, times) "
        "are enough — write a short factual Hebrew summary of the guests. "
        "If the article states what happened elsewhere, where, and the main outcome, summarize that. "
        "Reply INSUFFICIENT only if the body adds almost nothing beyond the headline."
    )
    short_retry_note = (
        "Note: You must output a Hebrew summary sentence (not empty, not only punctuation). "
        f"Max {MAX_SUMMARY_WORDS} words."
    )

    result = ""
    used_insuf_retry = False
    for attempt in range(2):
        user_blob = f"Article: {text[:stage2_limit]}"
        if attempt == 1 and used_insuf_retry:
            user_blob = f"{user_blob}\n\n{insufficient_retry_note}"
        elif attempt == 1 and len(result) > 0 and len(result) < 15:
            user_blob = f"{user_blob}\n\n{short_retry_note}"

        response = call_stage2(user_blob)
        finish = response.choices[0].finish_reason
        if finish == "content_filter":
            return None, "blocked by content policy (content_filter)"
        if finish == "length":
            return None, "response truncated"
        result = (response.choices[0].message.content or "").strip()

        if result.upper().startswith("SKIP") or result.startswith("סקיפ"):
            return None, None

        is_insuf = result.upper().startswith("INSUF") or result.startswith("לא מספיק")
        if is_insuf:
            if not body_available:
                return None, "body not accessible (paywall or blocked)"
            if body_available and not used_insuf_retry and attempt == 0:
                used_insuf_retry = True
                log.info("Stage 2 INSUFFICIENT — retry with hint (schedule/thin body)")
                continue
            return None, "insufficient content even with full article"

        if len(result) >= 15:
            break
        log.warning(f"Stage 2 response too short (attempt {attempt + 1}): '{result}'")
        if attempt >= 1:
            return None, "response too short after retry"

    if len(result) < 15:
        return None, "response too short after retry"

    # Allow Hebrew, Latin, digits, Polish diacritics (ą ć ę ł ń ó ś ź ż etc.), punctuation
    result = re.sub(r"[^\u0590-\u05FF\uFB1D-\uFB4FA-Za-z0-9\u00C0-\u024F\s,.:;!?%()\"\'-]", "", result).strip()
    if not result:
        return None, "sanitization left empty result"
    if not re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result):
        return None, "no Hebrew characters in result"
    # Allow Latin prefixes (quoted show titles, names, PiS/NATO) before the Hebrew sentence.
    # Drop echoed Polish only when almost no real Hebrew remains after the prefix.
    m_heb = re.search(r"[\u0590-\u05FF\uFB1D-\uFB4F]", result)
    result = result[m_heb.start() :].strip()
    if len(result) < 15:
        return None, "Hebrew too short after removing leading non-Hebrew (likely echoed input)"

    # Model/RTL glitches: stray Hebrew letter stuck to a Polish placename (e.g. בŁódź).
    _hebrew_glue = r"\u0590-\u05FF\uFB1D-\uFB4F"
    _latin_glue = r"A-Za-z\u00C0-\u024F"
    result = re.sub(rf"[{_hebrew_glue}]+(?=[{_latin_glue}])", "", result)
    result = re.sub(rf"(?<=[{_latin_glue}])[{_hebrew_glue}]+", "", result)
    result = result.strip()

    hebrew_re = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")
    latin_re = re.compile(r"[A-Za-z]")
    for token in re.split(r"[\s\-]+", result):  # split on spaces and hyphens
        if hebrew_re.search(token) and latin_re.search(token):
            return None, f"mixed-script word detected: '{token}'"

    word_count = len(result.split())
    if word_count > MAX_SUMMARY_WORDS_HARD:
        return None, f"summary too long ({word_count} words, max {MAX_SUMMARY_WORDS})"

    return result, None


def _telegram_html_anchor(url: str, label: str) -> str:
    """Build <a href> for Telegram HTML; escape entities in URL and label."""
    return (
        f"<a href=\"{html.escape(url, quote=True)}\">"
        f"{html.escape(label, quote=False)}</a>"
    )


def send_to_telegram(message, chat_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id or CHANNEL_ID, "text": message, "parse_mode": "HTML"},
        timeout=10,
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


def notify_admin(article, reason):
    if not ADMIN_TELEGRAM_ID:
        return
    reason_esc = html.escape(str(reason), quote=False)
    title_esc = html.escape(article["title"], quote=False)
    msg = f"⚠️ Skipped article ({reason_esc}):\n<b>{title_esc}</b>\n{article['link']}"
    try:
        send_to_telegram(msg, chat_id=ADMIN_TELEGRAM_ID)
    except Exception as e:
        log.error(f"Failed to notify admin: {e}")


def main():
    conn = init_db()
    client = OpenAI()  # reads OPENAI_API_KEY from env

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
            hebrew, skip_reason = summarize_in_hebrew(client, article)
            if hebrew is None:
                if skip_reason:
                    log.info(f"Skipped ({skip_reason}): {article['title'][:70]}")
                    notify_admin(article, skip_reason)
                else:
                    log.info(f"Skipped (not Poland-related): {article['title'][:70]}")
                conn.execute(
                    "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
                )
                conn.commit()
                continue
            body = html.escape(hebrew, quote=False)
            footer_label = f"{article['source']} | {article['date']}"
            message = f"{body}\n\n{_telegram_html_anchor(article['link'], footer_label)}"
            send_to_telegram(message)
            conn.execute(
                "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],)
            )
            conn.commit()
            log.info(f"Sent: {article['title'][:70]}")
            time.sleep(5)
        except Exception as e:
            log.exception("Error on article %s", article["id"])
            try:
                notify_admin(article, f"runtime error: {e}")
            except Exception:
                pass

    conn.close()


if __name__ == "__main__":
    main()
