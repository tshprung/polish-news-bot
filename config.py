"""Static config, env, prompts (no I/O)."""
import os
import re
import unicodedata
from pathlib import Path

FEEDS = [
    "https://tvn24.pl/rss/najwazniejsze.xml",
    "https://www.rmf24.pl/fakty/feed",
    "https://wiadomosci.onet.pl/.feed",
    "https://www.polsatnews.pl/rss/wszystkie.xml",
    "https://wydarzenia.interia.pl/feed",
    "https://wiadomosci.wp.pl/rss.xml",
    "https://wiadomosci.gazeta.pl/pub/rss/wiadomosci.xml",
    "https://pap-mediaroom.pl/kategoria/polityka-i-społeczeństwo/rss.xml",
    "https://pap-mediaroom.pl/kategoria/biznes-i-finanse/rss.xml",
]

# Only ingest RSS items from the last N hours (published time).
MAX_ARTICLE_AGE_HOURS = int(os.environ.get("MAX_ARTICLE_AGE_HOURS", "48"))

# Longer horizon so same-day beats (wires hours apart) collapse to one post.
DEDUP_WINDOW_HOURS = 24
DEDUP_JACCARD_MIN = 0.15
DEDUP_DICE_MIN = 0.38
DEDUP_DICE_RELAXED = 0.32
DEDUP_STRONG_INTERSECTION = 5
DEDUP_JACCARD_RELAXED = 0.11
DEDUP_OVERLAP_MIN = 0.28
DEDUP_OVERLAP_MIN_TOKENS = 4
DEDUP_OVERLAP_SET_MIN = 5
DEDUP_OVERLAP_LOOSE = 0.26
DEDUP_CONTENT_SUMMARY_CHARS = 4000

# Channel rate limits: post at most once per interval (UTC epoch), per topic key below.
WEATHER_POST_MIN_INTERVAL_SEC = int(os.environ.get("WEATHER_POST_MIN_INTERVAL_SEC", str(24 * 3600)))
FUEL_TOURISM_POST_MIN_INTERVAL_SEC = int(
    os.environ.get("FUEL_TOURISM_POST_MIN_INTERVAL_SEC", str(24 * 3600))
)
# Nawrocki / TK judge-instalment beat: one post per window unless env overrides (major news only).
TK_JUDGE_OATH_POST_MIN_INTERVAL_SEC = int(
    os.environ.get("TK_JUDGE_OATH_POST_MIN_INTERVAL_SEC", str(7 * 24 * 3600))
)
RATE_LIMIT_KEY_WEATHER = "weather_pl_imgw"
RATE_LIMIT_KEY_FUEL_TOURISM_DE_PL = "fuel_tourism_de_pl_border"
RATE_LIMIT_KEY_TK_JUDGE_OATH = "pl_tk_judge_oath_row"

_DEDUP_SHORT_TOKENS_OK = frozenset({"ke", "tk", "ue", "lr"})

_TOPIC_DEDUP_TAGS = frozenset({
    "#tram_accident",
    "#komendant_speed",
    "#lodz_crime_factory",
    "#pl_weather_forecast",
    "#nato_us_poland",
    "#baltic_whale_stranding",
    "#de_reiche_fuel_policy",
    "#pl_tk_judge_oath_row",
    "#poznan_infant_abuse_beat",
    "#pl_by_poczobut_release",
})
# Shared topic tag alone is too loose; require this many overlapping non-tag tokens too.
TOPIC_DEDUP_MIN_LEXICAL = 2
# Synoptic / IMGW wires share vocabulary; allow lighter overlap so one beat does not flood the channel.
TOPIC_DEDUP_MIN_LEXICAL_WEATHER = 1

_PL_FOLD = str.maketrans(
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
    "acelnoszzacelnoszz",
)


def fold_pl(token: str) -> str:
    return unicodedata.normalize("NFC", token).translate(_PL_FOLD).lower()


POLISH_STOPWORDS = frozenset(
    fold_pl(w)
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

# Very short RSS items are often headlines without facts; skipping them saves tokens.
_HARD_NEWS_SIGNALS = re.compile(
    r"(?is)"
    r"(?:"
    r"\b\d{2,}\b|"
    r"areszt|zatrzym|prokuratur|sąd|wyrok|oskarż|"
    r"zgin|rann|"
    r"sejm|rząd|minister|"
    r"wybuch|pożar|pozar|"
    r"strajk|"
    r"\bue\b|nato|"
    r")"
)


def should_skip_ultra_short_rss_item(title: str | None, summary: str | None) -> bool:
    t = (title or "").strip()
    s = (summary or "").strip()
    combined_len = len(t) + len(s)
    if combined_len >= 160:
        return False
    if len(s) >= 120:
        return False
    if _HARD_NEWS_SIGNALS.search(f"{t}\n{s}"):
        return False
    return combined_len >= 60


def ultra_short_rss_skip_reason() -> str:
    return "rss teaser: too short to summarize (skip to save tokens)"


# Opinion polls / “what Poles think” + percentages — not hard news for this channel.
_POLLSTER_NAMES = (
    r"(?:\bcbos\b|\bibris\b|\bkantar\b|\bipsos\b|\bestymator\b|united[-\s]+surveys|\bsocjogram\b|sw[-\s]+research|"
    r"ogolnopolsk\w{0,22}\s+grup\w{0,14}\s+badawcz\w{0,18}|\bogb\b|"
    r"\bopinia24\b|\bpollster\b|\biusz\b|\barytmometr\b)"
)
# Shares like 31%, 31,8%, 31.8 proc. (plain \d{1,3} misses decimal comma/dot shares).
# Allow 1–3 fractional digits (e.g. 56.37%, 81.49%) — still bounded so random IDs don’t match.
_POLL_SHARE_NUM = r"(?:\d{1,2}[,.]\d{1,3}|\d{1,3})\s*(?:%|proc\.?|procent\b|pkt\s+proc\b)"
_PUBLIC_OPINION_POLL = re.compile(
    r"(?is)"
    r"(?:"
    r"\bsondaz\w*|"
    r"\bsonda\b|\bsonde\b|"
    r"badan\w{0,14}\s+opinii|"
    r"badan\w{0,14}\s+spoleczn|"
    r"\bbadan\w{0,22}\s+cbos\b.{0,700}?"
    + _POLL_SHARE_NUM
    + r"|"
    r"\bcbos\b.{0,900}?"
    + _POLL_SHARE_NUM
    + r"|"
    + _POLL_SHARE_NUM
    + r".{0,700}?\bcbos\b|"
    r"(?:"
    + _POLLSTER_NAMES
    + r").{0,920}?(?:"
    + _POLL_SHARE_NUM
    + r"|(?:popier|nie\s*popier|uwaza\w*|zadeklar|wybral\w*|glosowa\w*|poparcie|notowania))|"
    + r"(?:"
    + _POLL_SHARE_NUM
    + r").{0,720}?(?:"
    + _POLLSTER_NAMES
    + r")|"
    r"\bankiet\w*"
    r".{0,140}?"
    r"(?:polak\w*|wyborc\w*|mieszkanc\w*)"
    r".{0,140}?"
    r"(?:"
    + _POLL_SHARE_NUM
    + r"|popier|nie\s*popier)|"
    r"\bgdyby\s+wybory\b|"
    r"\b(?:prognoz\w{0,16}\s+wyborcz\w*|symulacj\w{0,16}\s+wyborcz\w*)\b|"
    r"\bpoparcie\s+partyjn\w*|"
    r"\bnotowan\w{0,14}\s+partyjn\w*|"
    r"\bprzebadan\w{0,18}\s+\d{3,5}\s+osob\b|"
    # Sample size line (“na próbie 1000 osób”) near headline percentages — common without naming CBOS.
    + r"prob\w{0,22}\s+\d{3,5}\s+osob\b.{0,500}?"
    + _POLL_SHARE_NUM
    + r"|"
    + _POLL_SHARE_NUM
    + r".{0,500}?prob\w{0,22}\s+\d{3,5}\s+osob\b|"
    # WP.pl slug clichés; \\bsondaz can miss odd hyphen boundaries in some feeds.
    + r"nowy-sondaz|"
    r"(?:"
    + _POLLSTER_NAMES
    + r"|\bsondaz\w*)"
    r".{0,760}?"
    r"\b\d{2,3}\s+mandat\w{0,20}\b|"
    + r"(?:"
    + _POLL_SHARE_NUM
    + r").{0,520}?"
    + r"\b\d{2,3}\s+mandat\w{0,22}\b|"
    # Gazeta.pl (and similar) reader polls: slug "zapytalismy-o-…" without the word "sondaż".
    + r"zapytalismy-o-(?:[a-z0-9-]|,){6,320}|"
    + r"\bzapytalismy.{0,180}?czytelnik\w*|"
    + r"tak-oceniono(?:\.html)?|"
    + r"\bzapytalismy\b.{0,620}?"
    + _POLL_SHARE_NUM
    + r"|"
    + r"polacy-zabrali-glos|"
    + r"wyborach-sondaz|"
    + r"sondaz-daje-wskaz|"
    + r"\bpolacy\s+zabral\w{0,14}\s+glos\b.{0,680}?"
    + _POLL_SHARE_NUM
    + r"|(?:\bסקר\b|בסקר|הסקר).{0,80}?(?:opinia24|cbos|ibris|kantar|ipsos|pollster|wp)\b"
    + r"|(?:\bסקר\b|בסקר|הסקר).{0,120}?(?:\bפולנים\b|בפולין|של\s+הפולנים).{0,120}?(?:"
    + _POLL_SHARE_NUM
    + r"|אחוז)"
    + r"|(?:(?:\d{1,2}[,.]\d{1,3}|\d{1,3})\s*(?:%|אחוז)).{0,90}?"
    + r"(?:מה(?:נשאלים|משתתפים)|מהמשיבים|נשאלים|משתתפים|במדגם|במשאל).{0,260}?"
    + r"(?:(?:\d{1,2}[,.]\d{1,3}|\d{1,3})\s*(?:%|אחוז))"
    + r")",
  )


def should_skip_public_opinion_poll_blob(blob: str) -> bool:
    """True for public-opinion polls / surveys (Poles’ views + percentages), title/summary or longer excerpt."""
    raw = (blob or "").strip()
    if len(raw) < 28:
        return False
    f = fold_pl(unicodedata.normalize("NFC", raw))
    return bool(_PUBLIC_OPINION_POLL.search(f))


def should_skip_public_opinion_poll_teaser(title: str, summary: str, link: str = "") -> bool:
    return should_skip_public_opinion_poll_blob(
        f"{(title or '').strip()}\n{(summary or '').strip()}\n{(link or '').strip()}"
    )


def public_opinion_poll_skip_reason() -> str:
    return "rss teaser: public opinion poll / survey (Poles’ percentages)"


# Lifestyle listicles, coupon/shopping wire copy, and obvious advertorial markers (any language in feeds).
_COMMERCIAL_CLICKBAIT = re.compile(
    r"(?i)"
    r"(?:"
    # "10 Tipps…", "5 ways to save…" — small leading number + consumer/advice cluster in the same title
    r"^\d{1,2}\s*[\.\):\-–]?\s*[^\n]{0,180}?(?:"
    r"tipps?|tips?|tricks?|hacks?|life\s*hack|porad(?:y|nik|niku)?\s*.{0,20}zakup|"
    r"sposob(?:ów|y)\s|"
    r"rad\s*[,;\s]\s*jak\b|"
    r"\brad\b|"
    r"sparen|spartipp\w*|einkaufs?|shopping|shoppen|kaufgutschein|gutschein\w*|"
    r"oszczędz(?:ać|aj|anie|ając)|taniej\s+zakup|zakup\w{0,15}(?:oszczęd|taniej)|"
    r"rabat(?:y|ów)?|promocj\w*|wyprzedaż|outlet|kupon(?:y|ów)?|coupon|black\s+friday|cyber\s+monday|"
    r"ways\s+to\s+save|how\s+to\s+save|save\s+money|money[- ]sav|"
    r"astuces?\s|économis|economis|consejos?\s|ahorrar|"
    r"clever\s+sparen|smart\s+shop"
    r")"
    r"|"
    # German consumer-advice hook ("wie Sie … sparen/einkaufen")
    r"\bwie\s+sie\b[^\n]{0,120}(?:sparen|einkauf|kaufen|shoppen|geld)"
    r"|"
    # Standalone advertorial / sponsored labels
    r"\b(?:"
    r"sponsored|advertorial|paid\s+partnership|native\s+ad|"
    r"reklama|partnerem\s+(?:jest|serwisu|wirtualnej)|"
    r"artykuł\s+sponsor|treści\s+komercyjn|werbung"
    r")\b"
    r"|"
    # Classic engagement-bait openers (usually not hard news)
    r"^(?:you\s+won'?t\s+believe|this\s+(?:one\s+)?weird\s+trick|one\s+weird\s+trick)\b"
    r")",
)


def should_skip_commercial_clickbait_title(title: str) -> bool:
    """True for shopping/savings listicles, coupon copy, and similar non-news headlines."""
    t = (title or "").strip()
    if not t:
        return False
    return bool(_COMMERCIAL_CLICKBAIT.search(t))


# DIE ZEIT Jahrgang index (year hub), not a single article; RSS may link here by mistake.
# Must not match paths like /2026-04/... (date slug under /news/ etc.).
# Allow mobile / other subdomains and scheme-less links seen in feeds.
_ZEIT_JAHRGANG_INDEX = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?zeit\.de/2026(?:/|$|\?)", re.I
)


def is_zeit_jahrgang_index_url(url: str | None) -> bool:
    """True for zeit.de/2026 archive hub URLs only."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if u.startswith("//"):
        u = "https:" + u
    elif not re.match(r"^https?://", u, re.I) and re.match(
        r"(?:[a-z0-9-]+\.)?zeit\.de/", u, re.I
    ):
        u = "https://" + u
    return bool(_ZEIT_JAHRGANG_INDEX.match(u))


def zeit_jahrgang_index_skip_reason() -> str:
    return "rss teaser: ZEIT year hub (zeit.de/2026)"


def hebrew_scope_meta_summary_skip_reason() -> str:
    """Stage 2 sometimes echoes 'no Poland tie' as the whole Hebrew line instead of SKIP."""
    return "scope meta: Hebrew line only states missing Poland angle (should be SKIP)"


def should_reject_hebrew_scope_meta_summary(hebrew: str) -> bool:
    """
    Reject short meta-summaries that describe channel scope instead of reporting facts.
    Example (seen on channel): 'אין מעורבות פולנית ישירה במידע המסופק.'
    """
    t = (hebrew or "").strip()
    if len(t) > 260:
        return False
    needles = (
        "אין מעורבות פולנית",
        "אין מעורבות ישירה של פולין",
        "אין קשר ישיר לפולין",
        "אין קשר ישיר לפולנים",
        "ללא מעורבות פולנית",
        "ללא קשר ישיר לפולין",
        "אינה עוסקת בפולין",
        "אינו עוסק בפולין",
        "לא עוסקת בפולין",
        "לא עוסק בפולין",
        "ללא זיקה לפולין",
        "אין זיקה לפולין",
        "חסר קשר לפולין",
        "ללא קשר לפולין",
    )
    for n in needles:
        if n in t:
            return True
    if "מידע המסופק" in t and len(t) < 280:
        if re.search(r"(?:אין|ללא|חסר)\s+.+(?:פולין|פולנית|פולנים)", t):
            return True
    return False


# Admin DM noise: main.py skips Telegram notify when skip_reason starts with any of these prefixes.
SKIP_NOTIFY_EXEMPT_PREFIXES = (
    "rss teaser:",
    "pan-eu guide:",
    "scope meta:",
    "scope:",
    "fuel price:",
)


def skip_admin_notify_for_reason(reason: str | None) -> bool:
    if not reason:
        return False
    r = reason.lower()
    return any(r.startswith(p) for p in SKIP_NOTIFY_EXEMPT_PREFIXES)


def skip_admin_notify_for_article(article: dict | None, reason: str | None = None) -> bool:
    """Skip admin DM for known-noise skips (rss teaser, etc.) and ZEIT year-hub URLs."""
    if skip_admin_notify_for_reason(reason):
        return True
    link = (article or {}).get("link")
    return bool(is_zeit_jahrgang_index_url(link))

# Interview / lifestyle teasers that name a person and invite a click but state no event, figure, or decision.
_RSS_TEASER_SOFT_PROFILE = re.compile(
    r"(?is)"
    r"(?:"
    r"im\s+interview|im\s+gespräch|gespräch\s+mit|"
    r"w\s+wywiadzie|wywiad\s+z|rozmowa\s+z|"
    r"speaks\s+about|talks\s+about|reflects\s+on|looks\s+back|sums?\s+up|"
    r"offers?\s+(?:tips|advice|rat|ratschläge)|healthy\s+living|life\s+tips|lebensstil|wellness|"
    r"erklärt(?:e)?,?\s*warum|spricht\s+über|gibt\s+(?:tipps|ratschläge)|"
    r"(?:fasse|fassen|fasst)\s+zusammen|zusammenfassend|blickt\s+zurück|"
    r"discusses\s+(?:improvements|treatment|therapy|the\s+fight)|"
    r"(?:significant|bedeutend|wesentliche)\s+(?:improvements|fortschritte|verbesserungen)|"
    r"(?:improvements|fortschritte|verbesserungen)\s+(?:in|bei|im|an)\s+(?:der\s+|die\s+)?(?:treatment|therapy|behandlung|therapie)|"
    r"מסכם|מסביר\s+מדוע|מציע\s+עצות|מדבר\s+על|בשיחה\s+עם|שנות\s+עבודה|ניסיונו\b|"
    r"שיפורים\s+משמעותיים|עצות\s+לחיים|"
    r"explains\s+why|years?\s+of\s+(?:work|practice|experience)|"
    r"\bjahren?\s+(?:berufserfahrung|praxis|erfahrung)\b"
    r"|^(?:interview|wywiad|portrait|porträt|gespräch)\b"
    r")",
)

_RSS_TEASER_HARD_NEWS = re.compile(
    r"(?is)"
    r"(?:"
    r"\d+(?:[.,]\d{3})+\b|"
    r"\d+\s*%|\d+\s*proz\.?\b|"
    r"[€$]|\beur\b|\busd\b|\bpln\b|\bzł\b|złot|million|millionen|miliard|mio\.|mrd\.|"
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|"
    r"\b(?:[3-9]\d{2,}|[1-9]\d{4,})\b|"
    r"\b\d+\s*(?:osób|rannych|zabitych|ofiar|ludzi|dzieci|kart|punktów)\b|"
    r"\b(?:zginę|zabito|zabił|areszt|wyrok|skazan|uchwal|podpis\w{0,24}ustaw|"
    r"wypad|wybuch|eksploz|strajk|ewaku|kolej.{0,24}wypad|"
    r"killed|injured|arrested|sentenced|verurteil|urteil|tote|verletzte|festnahme|"
    r"מעצר|הרוג|הרוגים|פצוע|פצועים|אחוז\s|נפגעים)"
    r"|"
    r"(?:\u201e|„|«|\u201c)(?:[^\n]{18,}?)(?:\u201c|”|“|»|\"|\u201d)"
    r")",
)


def should_skip_information_poor_rss_teaser(title: str, summary: str) -> bool:
    """
    True when title + RSS summary look like profile/interview fluff: reflective language,
    tips/lifestyle hooks, but no dateline-style facts (counts, %, money, verdicts, quotes with
    substance, etc.). Skipping avoids spend on fetch + LLM when the teaser is inherently empty.
    """
    t = (title or "").strip()
    s = (summary or "").strip()
    combined = f"{t}\n{s}".strip()
    if len(combined) < 88:
        return False
    if _RSS_TEASER_HARD_NEWS.search(combined):
        return False
    return bool(_RSS_TEASER_SOFT_PROFILE.search(combined))


def rss_teaser_skip_reason() -> str:
    return "rss teaser: no extractable facts"


# Essay / podcast backstory (anthem, symbols, “history of…”): no vote, law, or dated incident in the teaser.
_EVERGREEN_CULTURE_TEASER = re.compile(
    r"(?is)"
    r"(?:"
    r"(?:הממלכה\s+הגרמנית|חילוקי\s+דעות).{0,240}המנון\s+ה?לאומי.{0,140}"
    r"(?:נבחנת|היסטור|מחלוק|סביב\s+קסמי|לאחר\s+איחוד)|"
    r"המנון\s+ה?לאומי.{0,200}(?:היסטור|מחלוק|חילוקי|נבחנת|סביב\s+קסמי|לאחר\s+איחוד)|"
    r"(?:nationalhymne|deutschlandlied|lied\s+der\s+deutschen).{0,140}"
    r"(?:geschicht|kontrovers|streit|podcast|hintergrund|debatte)|"
    r"hymn\w*.{0,100}(?:history|controvers|podcast)"
    r")",
)
_NEWS_DECISION_IN_TEASER = re.compile(
    r"(?is)"
    r"(?:"
    r"bundestag|bundesregierung|beschloss|verabschiedet|neues\s+gesetz|urteil|urtei|"
    r"anklag|ermittlung|verbot|abstimmung|referendum|referend|"
    r"החליט|אושר ב|חקיקה|פסק דין|הכרעת דין|כתב אישום|מעצרים"
    r")",
)


def should_skip_evergreen_culture_teaser(
    title: str, summary: str, link: str | None = None,
) -> bool:
    """True for national-symbol / history-podcast teasers with no concrete news decision in the excerpt."""
    combined = f"{(title or '').strip()}\n{(summary or '').strip()}\n{(link or '').strip()}".strip()
    if len(combined) < 70:
        return False
    if _NEWS_DECISION_IN_TEASER.search(combined):
        return False
    if _EVERGREEN_CULTURE_TEASER.search(combined):
        return True
    path = (link or "").lower()
    if re.search(r"(?i)(?:geschichte|/wissen/).{0,50}podcast|podcast.{0,40}geschichte", path):
        if re.search(
            r"(?i)nationalhymne|deutschlandlied|hymn|lied\s+der|המנון\s+ה?לאומי",
            combined,
        ):
            return True
    return False


def evergreen_culture_skip_reason() -> str:
    return "rss teaser: evergreen culture piece (no news hook)"


# Baltic / North German coast: centuries-long human interest in whales (church art, dissection history)
# — not a current incident, no Poland tie. Matches ZEIT-style slugs and German/Hebrew teasers.
_WILDLIFE_HISTORY_URL = re.compile(
    r"(?i)(?:"
    r"wale-bewegten-schon-vor-jahrhunderten|"
    r"vor-jahrhunderten-die-mensch|"
    r"ostsee[-_]wale[^/?#]{0,50}jahrhundert|"
    r"jahrhundert[^/?#]{0,50}(?:wal|wale)\b"
    r")",
)
_WHALE_BREAKING_TEASER = re.compile(
    r"(?is)"
    r"(?:"
    r"gestrandet|strandung|angeschwemmt|"
    r"\b(?:schwerer\s+|tierischer\s+)?unfall\b|einsatzkräfte|rettung|"
    r"polizei.{0,32}(?:sperr|absperr)|"
    r"\bcarcass\b|gestorben\w*|"
    r"veterinär.{0,20}(?:untersuch|obduzi)|"
    r"(?:martwy|martwa|martw\w*)\s+wieloryb|"
    r"wieloryb\w*.{0,40}(?:utkn|plaż|brzeg|strand|znalez|wyłow|"
    r"znalaz|śmiert|nie\s*żyje)|"
    r"חילוץ|להציל\s+את|גופת\s+לוויתן|לוויתן\s+מת(?:\s|$)"
    r")",
)
_BALTIC_COAST_WILDLIFE = re.compile(
    r"(?is)"
    r"(?:"
    r"\bostsee\b|ostsee-ufer|binnen(?:meer|ostsee)|"
    r"\b(?:wismar|greifswald|stralsund|rostock|lübeck|lubeck)\b|"
    r"rügen|rugen|vorpommer|mecklen|timmendorf|usedom|"
    r"\bbałtyk|baltyk|baltic\b|"
    r"מפרץ|הבלטי|גרייפסוואלד|וויסמר"
    r")",
)
_WHALE_LEXEME = re.compile(
    r"(?is)(?:\bwale?\b|wieloryb\w*|wal\s*strand|לוויתן|whales?|orca\b)",
)
_WILDLIFE_HISTORY_FRAMING = re.compile(
    r"(?is)"
    r"(?:"
    r"jahrhundert\w*|vor\s+jahrhunderten|schon\s+vor\s+jahrhundert|"
    r"beweg\w{0,16}.{0,80}(?:jahrhundert|menschen)|"
    r"(?:kirchen|kirche).{0,60}(?:malerei|gemälde|fresk)|"
    r"geschicht\w*.{0,50}(?:whale|wale|wal\b|ostsee)|"
    r"(?:for|over)\s+centuries\b|centur(?:y|ies)\s+of|"
    r"מאות\s+שנים|לפני\s+מאות|"
    r"היסטורי\w?.{0,40}(?:לוויתן|חיות\s+ים)|"
    r"(?:לוויתן|חיות\s+הים).{0,100}(?:לאורך\s+ההיסטור|במאות)"
    r")",
)


def should_skip_baltic_wildlife_history_teaser(
    title: str, summary: str, link: str | None = None,
) -> bool:
    """
    True for Baltic/DE coast whale ecology-as-cultural-history (centuries, church art),
    not a current stranding or operational response — no Poland national-news hook.
    """
    t = (title or "").strip()
    s = (summary or "").strip()
    u = (link or "").strip()
    combined = f"{t}\n{s}\n{u}".strip()
    if len(combined) < 48:
        return False
    if _WHALE_BREAKING_TEASER.search(combined):
        return False
    if _WILDLIFE_HISTORY_URL.search(u):
        if _WHALE_LEXEME.search(combined) or _WHALE_LEXEME.search(u):
            return True
        return False
    if not (
        _BALTIC_COAST_WILDLIFE.search(combined)
        and _WHALE_LEXEME.search(combined)
        and _WILDLIFE_HISTORY_FRAMING.search(combined)
    ):
        return False
    return True


def baltic_wildlife_history_skip_reason() -> str:
    return "rss teaser: baltic wildlife history (no current incident)"


# Baltic Sea whale / dolphin / large cetacean rescue or death wires syndicated as „świat” —
# skip when no Poland-specific hook anywhere in title + teaser + fetched body prefix.
_BALTIC_SEA_CONTEXT = re.compile(
    r"(?is)(?:"
    r"bałtyk|baltyk|baltyku|morze\s+bałty|morze\s+balty|plaza\s+baltyku|"
    r"\bbaltic\b|\bostsee\b|ostsee-?ufer|"
    r"ים\s+הבלטי|הבלטי\b"
    r")",
)
_LARGE_CETACEAN_TEASER = re.compile(
    r"(?is)(?:"
    r"wieloryb\w*|humbak\w*|karłowaty|karlowaty|"
    r"delfin\w*|orca\b|kaszalot\w*|kaszalota|"
    r"\bwalu\b|\bwalem\b|\bwhale\b|humpback|"
    r"לוויתן|גובהנן|צדפי"
    r")",
)
_POLAND_HOOK_FOR_BALTIC_WILDLIFE = re.compile(
    r"(?is)(?:"
    r"(?<![a-z])polsk\w*|w\s+polsce|"  # Polish actors / territory (never match TLD .pl in URLs)
    r"minister\w*.{0,40}polsk|"
    r"gdans|gdyni|sopot|trójmiasto|trojmiasto|ustka|"
    r"kołobrz|kolobrz|świnouj|swinouj|"
    r"wybrzeż\w*.{0,24}(?:polsk|polski)|"
    r"panstwowe\w*gospodar|pgw\b|"
    r"פולין|פולנים|פולני|בפולין|"
    r"(?<![a-z])gdansk\b|(?<![a-z])gdynia\b"
    r")",
)


def should_skip_baltic_marine_wildlife_without_poland_blob(blob: str) -> bool:
    """
    True when the text is clearly about the Baltic + a large marine mammal (whale, dolphin, etc.),
    but Polish institutions, territory, or citizens never appear — not Poland national news.
    """
    raw = (blob or "").strip()
    if len(raw) < 42:
        return False
    sample = raw[:14000]
    f = fold_pl(sample)
    sea = _BALTIC_SEA_CONTEXT.search(sample) or _BALTIC_SEA_CONTEXT.search(f)
    mammal = _LARGE_CETACEAN_TEASER.search(sample) or _LARGE_CETACEAN_TEASER.search(f)
    if not (sea and mammal):
        return False
    if _POLAND_HOOK_FOR_BALTIC_WILDLIFE.search(sample) or _POLAND_HOOK_FOR_BALTIC_WILDLIFE.search(
        f
    ):
        return False
    return True


def baltic_marine_wildlife_no_poland_skip_reason() -> str:
    return "rss teaser: baltic marine mammal story without Poland hook"


def should_skip_entertainment_politician_chat_teaser(
    title: str, summary: str, link: str | None = None,
) -> bool:
    """
    Celebrity / Unterhaltung talk shows that only list a politician as guest (BILD MayWay, etc.)
    with no policy outcome in the teaser.
    """
    u = (link or "").lower()
    if "bild.de" not in u:
        return False
    if "/unterhaltung/" not in u and "mayway" not in u:
        return False

    combined = f"{(title or '').strip()}\n{(summary or '').strip()}".strip()
    if len(combined) < 36:
        return False
    if _NEWS_DECISION_IN_TEASER.search(combined):
        return False

    if re.search(
        r"(?is)תוכנית.{0,90}(?:bild|בילד).{0,110}אירחה|(?:bild|בילד).{0,70}תוכנית.{0,90}אירחה",
        combined,
    ):
        return True
    if re.search(
        r"(?is)אירחה.{0,130}(?:בונדסטאג|בבונדסטאג|יו\"ר\s+סיעת|bundestag|cducsu)",
        combined,
    ):
        return True
    if re.search(r"mayway|zu\s+gast|talkshow|star-?talk", u) and re.search(
        r"(?is)(?:spahn|merz|bundestag|בונדסטאג|אירחה|תוכנית|fraktion)",
        combined,
    ):
        return True
    return False


def entertainment_chat_skip_reason() -> str:
    return "rss teaser: entertainment TV guest spot (no policy facts)"


# EU-wide regulatory / property explainer with “what owners should do” — skip if teaser never ties to PL or DE.
_PAN_EU_WHOLE_SCOPE = re.compile(
    r"(?is)"
    r"(?:"
    r"בכל האיחוד האירופי|במדינות\s+האיחוד|"
    r"in\s+der\s+gesamten\s+(?:EU|Europäischen\s+Union)|"
    r"in\s+allen\s+EU[\s-]?(?:Staaten|Mitglied|Ländern?)?|"
    r"EU[\s-]weit|eu[\s-]weit|"
    r"g(?:anse|esamte)?\s+Europäischen\s+Union|"
    r"across\s+the\s+(?:EU|European\s+Union)|throughout\s+the\s+EU|EU-wide|"
    r"w[e]?\s+całej\s+UE|w[e]?\s+całej\s+Unii\s+Europejskiej|na\s+terenie\s+całej\s+UE|"
    r"całej\s+Unii(?:\s+Europejskiej)?"
    r")",
)

_PROPERTY_ENERGY_OWNER_TOPIC = re.compile(
    r"(?is)"
    r"(?:"
    r"נכסים|נדל[\"״\u05f4]ן|שווי\s+נכס|דירוג|תעוד(?:ות)?\s+אנרגיה|בעלים\s+עשויים|"
    r"Immobilien(?:eigentümer)?|\bEigentümer\w*|Energieausweis|Gebäudeenergie|"
    r"new\s+energy\s+certificate|energy\s+performance|EPC\s+certificate|"
    r"real\s+estate|property\s+(?:owners|values|ratings)|home\s*owners|"
    r"nieruchomości|certyfikat(?:ów)?\s+energetyczn|świadectw\w*\s+energetyczn"
    r")",
)

_EXPLAINER_OR_ACTION_GUIDE = re.compile(
    r"(?is)"
    r"(?:"
    r"מסביר\s+כיצד|מסביר(?:ים)?\s+מה|(?:^|\s)WELT\s+מסביר|"
    r"erklärt(?:,\s*)?(?:wie|was)|so\s+(?:reagieren|handeln)\s+Sie|"
    r"wissen\s+sollten|wissen\s+müssen|jetzt\s+wissen|handeln\s+sollten|eigentuemer\w*.{0,24}wissen|"
    r"immobilien\w*.{0,32}(?:wissen|tun)\s+sollten|"
    r"what\s+.{0,40}need\s+to\s+know|how\s+to\s+(?:act|respond)|"
    r"wyjaśnia,?\s*co|powinni\s+wiedzieć|trzeba\s+wiedzieć"
    r")",
)

_COUNTRY_HOOK_POLAND_OR_GERMANY = re.compile(
    r"(?is)"
    r"(?:"
    r"פולין|פולנים|בפולין|פולני|"
    r"Polska|Polsce|polski|polskiej|polskich|polscy|polską|polskim|polsk\w+|Sejmu|Warszaw|Krakow|Kraków|Wrocław|Poznań|Katowic|Gdańsk|"
    r"גרמניה|בגרמניה|גרמנים|"
    r"Deutschland|deutsche[rn]?|deutsch\w*|\bBRD\b|Bundes\w+|Berlin|München|"
    r"Hamburg|Frankfurt|Köln|NRW|Bayern|niemieck|Niemc\w+"
    r")",
)


def should_skip_pan_eu_generic_property_guide(title: str, summary: str) -> bool:
    """
    Pan-EU regulatory or property stories framed for generic “owners” plus an outlet explainer,
    with no Poland or Germany hook in title/summary — typical syndicated consumer desk filler.
    """
    t = (title or "").strip()
    s = (summary or "").strip()
    combined = f"{t}\n{s}".strip()
    if len(combined) < 72:
        return False
    if not _PAN_EU_WHOLE_SCOPE.search(combined):
        return False
    if not _PROPERTY_ENERGY_OWNER_TOPIC.search(combined):
        return False
    if not _EXPLAINER_OR_ACTION_GUIDE.search(combined):
        return False
    if _COUNTRY_HOOK_POLAND_OR_GERMANY.search(combined):
        return False
    return True


def pan_eu_property_guide_skip_reason() -> str:
    return "pan-eu guide: EU-wide explainer without PL/DE hook in teaser"


# Family / patient crowdfunding: zbiórka, zrzutka, appeals for treatment costs — not national news.
_CROWDFUND_REQUEST = re.compile(
    r"(?is)"
    r"(?:"
    r"zbiork\w*|zrzutk\w*|wesprzyj|wsparcie\s+finansow|darowizn\w*|"
    r"wpłac\s+na|wplac\s+na|przekaz\s+(?:datek|darowizn)|"
    r"apel\w*\s+o\s+(?:pomoc|wspar|pieniadz|fundusz)|"
    r"prosz\w*\s+o\s+(?:pomoc|wspar|datek)|"
    r"potrzeb(?:uj\w*|a)\s+(?:\d|pieniadz|fundus|zł|zl)|"
    r"zebr\w*\s+(?:jeszcze|brakuje|kwot|ponad|zł|zl|milion|mln)|"
    r"zbieram\w*\s+na|zbiorka\s+charytatywn|"
    r"gofundme|crowdfund|zrzutka\.pl"
    r")",
)
_MEDICAL_FAMILY_STORY = re.compile(
    r"(?is)"
    r"(?:"
    r"leczen\w*|terapi\w*|operacj\w*|chorob\w*|chorego|genetyczn\w*|"
    r"dystrofi|mukowisc|oddział\w*\s+szpital|szpital\w*\s+w\s+usa|\busa\b.{0,50}(?:dol|leczen|terapi|koszt)|"
    r"koszt\w*\s+(?:leczen|terapi|operac)|dzieck\w*|syn\w*|cork\w*|rodzin\w*|walczy\s+o\s+zyc|"
    r"ratowac\s+zyc|ratuje|najstarsze\s+dziecko"
    r")",
)
_MONEY_GOAL = re.compile(
    r"(?is)"
    r"(?:\d+[.,]?\d*\s*(?:mln|milion|tys\.|tysiac)\s*(?:zł|zl|złot|eur|usd|dol)|"
    r"złotych|milion\w*\s+dol|dol\w*\s+.*leczen)"
)
_OFFICIAL_HEALTH_PROGRAM = re.compile(
    r"(?is)"
    r"(?:"
    r"\bnfz\b|minister(stwo)?\s+zdrowia|refundacj\w*\s+(?:lek|program|leku)|"
    r"rzad\w*\s+(?:przyzn|przeznacz|zdecyd|zatwierdz|wprowadz)|"
    r"uchwalon\w*\s+(?:w\s+)?sejm|ustaw\w*\s+o\s+(?:zdrow|refund)|"
    r"program\s+lekowy|budzet\w*\s+(?:państw|ochrony)"
    r")",
)


def should_skip_private_medical_fundraiser_blob(blob: str) -> bool:
    """True for donation / treatment-cost appeals (zbiórka, family seeks funds), not policy/refund news."""
    raw = (blob or "").strip()
    if len(raw) < 50:
        return False
    f = fold_pl(raw[:12000])
    if _OFFICIAL_HEALTH_PROGRAM.search(f):
        return False
    if _CROWDFUND_REQUEST.search(f) and _MEDICAL_FAMILY_STORY.search(f):
        return True
    if _MONEY_GOAL.search(f) and _MEDICAL_FAMILY_STORY.search(f) and re.search(
        r"(?is)(?:zbiork|zrzutk|wspar|darowizn|apel|zbier|potrzeb|wplac|przekaz)", f
    ):
        return True
    return False


def should_skip_private_medical_fundraiser_teaser(title: str, summary: str) -> bool:
    return should_skip_private_medical_fundraiser_blob(
        f"{(title or '').strip()}\n{(summary or '').strip()}"
    )


def crowdfunding_medical_skip_reason() -> str:
    return "rss teaser: private medical fundraiser / donation appeal"


_PL_NATIONAL_HOOK = re.compile(
    r"(?is)\b(?:"
    r"polsk\w*|polsce|polacy|polak\w*|"
    r"sejm|senat|rz[aą]d|premier|prezydent|ustaw\w*|trybuna[łl]|tk\b|"
    r"mswia|msz\b|mon\b|nbp\b|zus\b|krs\b|pk\b|pis\b|ko\b|po\b|lewica|konfederacj"
    r")\b"
)
_FOREIGN_WORLD_WIRE = re.compile(
    r"(?is)\b(?:"
    r"ukrain\w*|kij[oó]w|kyiv|zelensk\w*|"
    r"rosj\w*|putin\w*|moskw\w*|kreml\w*|"
    r"naddniestrz\w*|naddniestrze|tr?ansnistr\w*|"
    r"bia[łl]oru[śs]\w*|iran\w*|izrael\w*|gaza\b|hamas\b|"
    r"trump\w*|usa\b|waszyngton\w*|chiny|pekin\w*|"
    r"nato\b|ue\b|bruksela|komisj\w*\s+europej"
    r")\b"
)
_PL_LOCAL_ONLY_MARKERS = re.compile(
    r"(?is)\b(?:"
    r"wroc[łl]aw|krak[oó]w|gd[aą]sk|gdy[nń]ia|pozn[ań]|\blodz\b|ł[oó]d[zź]|"
    r"bialystok|rzesz[oó]w|katowic\w*|szczecin|lublin|bydgoszcz|toru[nń]|"
    r"olsztyn|opole|kielc\w*|zielona\s+g[oó]ra|gorz[oó]w|"
    r"dolno[śs]l[aą]sk\w*|mazowieck\w*|ma[łl]opolsk\w*|podlask\w*|"
    r"podkarpack\w*|[śs]l[aą]sk\w*|wielkopolsk\w*|pomorsk\w*"
    r")\b"
)


def should_skip_non_national_poland_teaser(title: str, summary: str, link: str = "") -> bool:
    blob = f"{(title or '').strip()}\n{(summary or '').strip()}\n{(link or '').strip()}".strip()
    if len(blob) < 32:
        return False
    f = fold_pl(blob[:12000])
    if _PL_NATIONAL_HOOK.search(f):
        return False
    if _FOREIGN_WORLD_WIRE.search(f):
        return True
    if _PL_LOCAL_ONLY_MARKERS.search(f):
        return True
    return False


def non_national_poland_skip_reason() -> str:
    return "scope: not Poland national (foreign wire or local-only without national institutions)"


# Routine pump-price tables (ministerial max PLN/l, KAS fines) — not channel news.
_FUEL_PRICE_MAJOR_EXCEPTION = re.compile(
    r"(?is)"
    r"(?:"
    r"niedobor\w*\s+paliw|brak\s+paliw|kryzys\s+paliw|"
    r"(?:sejm|senat).{0,100}(?:ustaw|głosow|uchwal|projekt).{0,40}(?:paliw|benzyn|akcyz|energ)|"
    r"(?:ustaw|projekt).{0,60}(?:paliw|benzyn|akcyz).{0,40}(?:sejm|senat)|"
    r"(?:wypadek|pożar|eksploz).{0,80}(?:rafiner|orlen|płock)|"
    r"embargo|sankcj\w*.{0,40}(?:ropa|paliw)|"
    r"strajk.{0,60}(?:orlen|rafiner)"
    r")",
)
_FUEL_PRICE_ROUTINE_CHURN = re.compile(
    r"(?is)"
    r"(?:"
    r"maksymaln\w*\s+cen\w*\s+paliw|"
    r"maxymaln\w*\s+cen\w*\s+paliw|"
    r"nowe\s+maksymaln\w*\s+cen\w*\s+paliw|"
    r"ceny\s+(?:maksymaln\w*|najwyższ\w*|najwyzs\w*|detaliczn\w*)\s+paliw|"
    r"kosmetyczn\w*\s+zmian\w*|"
    r"(?:minister\w*\s+energii|ministr\s+energii).{0,100}(?:cen\w*\s+paliw|maksymaln\w*\s+cen)|"
    r"(?:cen\w*\s+paliw|maksymaln\w*\s+cen).{0,100}(?:minister\w*\s+energii|krajow\w*\s+administracj\w*\s+skarbow)|"
    r"krajow\w*\s+administracj\w*\s+skarbow\w*.{0,80}(?:paliw|benzyn|stacj|kary|mandat)|"
    r"cena\s+(?:detaliczna|maksymalna)\s+paliw|"
    r"tabela\s+cen\s+paliw|"
    r"maksymaln\w*-ceny-paliw|ceny-paliw-w-polsce|"
    r"מחיר(?:י|י\s+ה)?\s*(?:ה)?דלק\s*(?:ה)?מרביים|"
    r"תקר(?:ה|ת)\s+מחיר(?:י)?\s*דלק|"
    r"שר\s+האנרגיה.{0,120}(?:דלק|בנזין|סולר)|"
    r"בנזין\s*(?:95|98).{0,40}(?:סולר|זלוטי)"
    r")",
)
_FUEL_PRICE_FUEL_CONTEXT = re.compile(
    r"(?is)"
    r"(?:"
    r"paliw|benzyn|diesel|olej\s+nap|\bon\b\s*(?:95|98)|"
    r"דלק|בנזין|סולר"
    r")",
)


def should_skip_fuel_price_churn_blob(blob: str) -> bool:
    """True for periodic max pump-price tables, not fuel crises or fuel-tax legislation."""
    raw = blob or ""
    if not raw.strip():
        return False
    if _FUEL_PRICE_MAJOR_EXCEPTION.search(raw):
        return False
    if not _FUEL_PRICE_FUEL_CONTEXT.search(raw):
        return False
    folded = fold_pl(raw[:12000])
    if _FUEL_PRICE_ROUTINE_CHURN.search(raw) or _FUEL_PRICE_ROUTINE_CHURN.search(folded):
        return True
    # Minister sets PLN/l for 95/98/diesel on specific dates — typical wire shape.
    if re.search(
        r"(?is)"
        r"(?:minister\w*\s+energii|ministr\s+energii).{0,160}"
        r"(?:\d+[.,]\d{2}\s*zł|zł\s*[/]?\s*l|"
        r"benzyn\w*\s*(?:95|98)|on\s*(?:95|98)|diesel|olej\s+nap)",
        folded,
    ):
        return True
    return False


def should_skip_fuel_price_churn_teaser(title: str, summary: str, link: str = "") -> bool:
    return should_skip_fuel_price_churn_blob(
        f"{(title or '').strip()}\n{(summary or '').strip()}\n{(link or '').strip()}"
    )


def fuel_price_churn_skip_reason() -> str:
    return "fuel price: routine max pump price table (not channel news)"


PAYWALLED_DOMAINS = {"pro.rp.pl", "rp.pl", "wyborcza.pl"}

MAX_SUMMARY_WORDS = 50
MAX_SUMMARY_WORDS_HARD = 60

# Reduce OpenAI spend by limiting stage2 input size.
STAGE2_INPUT_CHARS_DEFAULT = int(os.environ.get("STAGE2_INPUT_CHARS_DEFAULT", "2200"))
STAGE2_INPUT_CHARS_LONG_BODY = int(os.environ.get("STAGE2_INPUT_CHARS_LONG_BODY", "2800"))

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = Path(os.environ.get("DB_PATH", "/opt/polish_news/seen.db"))

# Append raw article URL so Telegram can build link preview (og:image); HTML <a> alone often has no preview.
TELEGRAM_LINK_PREVIEW_ENABLED = os.environ.get("TELEGRAM_LINK_PREVIEW_ENABLED", "1") == "1"

_SUMMARY_CAP = str(MAX_SUMMARY_WORDS)
SYSTEM_PROMPT = (
    "Hebrew Telegram blurbs from Polish media. Readers: Hebrew speakers in Poland; national news; keep Polish context. "
    "Assume Poland unless stated otherwise. Polish people = פולנים (never ישראלים).\n"
    "GEO: Every article is Polish domestic news unless the text explicitly says another country. "
    "Catholic/Easter processions, pilgrimages, and night services in Polish cities = Poland; do not map them to Israel.\n"
    "Polish cities, towns, and regions: always write them in Latin exactly as in the article, inside the Hebrew line—"
    "never as Hebrew-only placenames (wrong: פרזמישל for Przemyśl; wrong: בגדה or Hebrew phonetics for Gdańsk—reads like unrelated geography). "
    "Right pattern: Hebrew words + Latin city (e.g. …ב-Gdańsk, …ב-Warszawa, …ב-Kraków). "
    "For the country as a whole, use Hebrew פולין (e.g. בפולין, תושבי פולין)—not the Polish word 'Polska' or ב-Polska (confusing hybrid). "
    "Do not put Israeli cities (תל אביב, ירושלים, etc.) instead of Polish ones. "
    "Syrenka / pomnik Syrenki = Warsaw mermaid monument in Warszawa, not Israel.\n\n"
    "**Channel scope — Poland national news (domestic-first):** Cover **Poland's national-level domestic affairs**. "
    "**GO** when it is clearly about Poland as a state: government/Sejm/Senate, presidency, courts, nationwide economy/price policy, "
    "nationwide security for Poland, and other country-wide issues. "
    "**SKIP** foreign wars/diplomacy and world wires (Russia/Ukraine/US/EU etc.) unless Poland's national institutions or officials are "
    "explicitly central in the excerpt (Polish government position/decision, Polish MFA/MON, Sejm vote, Polish agencies). "
    "Also **SKIP** purely local city/regional incidents unless the excerpt clearly frames it as a national issue.\n\n"
    "Reply with exactly one line, no preamble:\n"
    "SKIP - sports.\n"
    "SKIP - no direct Poland tie (per scope above): another country's **purely domestic** affairs only; **generic EU/Brussels** desk "
    "(bloc-wide cyber, Commission IT briefings, pan-EU consumer explainers) without Polish officials, agencies, parties, or a PL-specific incident; "
    "**foreign politics** where only other states' actors appear and Poland does not; "
    "**Hungary-only** calls on Russia sanctions, EU energy crisis, or reopening oil pipelines without Polish officials or a PL angle.\n"
    "SKIP - profile or interview setup that in the excerpt only introduces someone’s career arc, reflections, or generic "
    "themes (e.g. treatment ‘improvements’, healthy-living tips) without a datable event, statistic, binding decision, "
    "or a quoted concrete claim you could relay.\n"
    "SKIP - evergreen culture / symbolic history (e.g. national anthem rows, ‘history of the hymn’, podcast backstory) "
    "when there is no current decision, vote, law, investigation, or dated incident—only commentary on past controversies.\n"
    "SKIP - Baltic/German **wildlife history or cultural reception** (e.g. Ostsee whales “moved people for centuries”, church murals, "
    "historical dissections as curiosity) **without** a **current** incident (stranding response, official veterinary probe, transport ban) "
    "and **without** Poland or Poles in the excerpt.\n"
    "SKIP - **Baltic Sea** whale / dolphin / large marine-mammal rescue or death when the excerpt **never** ties to **Poland**: "
    "no Polish Baltic coast (Gdańsk, Gdynia, etc.), no Polish agencies or responders named, no Polish citizens as the story’s stake—"
    "generic „świat” or German/Danish coast only.\n"
    "SKIP - entertainment / Unterhaltung chat (e.g. BILD MayWay) whose teaser is only ‘show X hosted politician Y’ "
    "with no bill, vote, scandal fact, or policy outcome stated.\n"
    "SKIP - private **medical fundraiser** or family **donation appeal** (zbiórka / zrzutka / help pay for therapy abroad) — not NFZ, "
    "ministerial programs, or law.\n"
    "SKIP - service/lifestyle and low-signal noise: shopping/coupons/listicles, horoscopes/quizzes, travel/restaurant 'what to do', "
    "celebrity/showbiz, and micro-local updates like minor traffic closures or small incidents without broader public impact.\n"
    "SKIP - weather micro-updates: keep only major warnings/extremes or rate-limited forecast beats.\n"
    "SKIP - routine **fuel pump price tables** (Polish maksymalne ceny paliw / minister energii sets max PLN/l for benzyna 95/98/on/diesel, "
    "Krajowa Administracja Skarbowa fines for selling above cap, 'kosmetyczna zmiana') — not fuel crises, refinery accidents, or new fuel-tax legislation.\n"
    "SKIP - markets daily churn (crypto/stock up-down today) unless there is a concrete enforcement/regulatory decision, major platform outage, "
    "or clear Poland impact.\n"
    "SKIP - opinion polls / surveys (sondaż, CBOS/IBRiS/Kantar/Opinia24-style headlines, “what share of Poles think”) "
    "and any political analysis/simulations based on such polls, without a binding vote outcome, law, or investigation as the news.\n"
    "INSUFFICIENT - only when the body truly adds almost nothing beyond the title: "
    "no names, no agencies, no dates or numbers, no quoted/attributed claims, no decision you can state in one clause.\n"
    f"Hebrew - 1-2 sentences, ≤{_SUMMARY_CAP} words\n\n"
    "If the Polish text includes any of: named people or agencies, dates, figures/statistics, permits/bans/decisions, "
    "or who said what— you must output Hebrew summarizing those facts; do not answer INSUFFICIENT. "
    "Interviews, diplomacy, and regional/environmental regulation count as enough to summarize.\n\n"
    "Every Hebrew-line answer must contain Hebrew script; never reply with English-only or Polish-only Latin sentences. "
    "Write the full summary in Hebrew prose — never paste or lightly edit Polish/German/English sentences from the source; "
    "Latin script is only for proper nouns (people, brands, cities, acronyms), never for Polish verbs or grammar. "
    "When outputting Hebrew, write only the summary text—never prefix with עברית:, תרגום:, Hebrew:, Summary:, or similar. "
    "Hebrew line must start with Hebrew; Latin for personal names, all Polish place names (Gdańsk, Gdynia, Trójmiasto, etc.—as in source), acronyms (NATO, PiS). "
    "Polish age headlines **N-latka** / **N-latek** (years old, feminine/masculine): write **בת N** or **בן N** from context, "
    "or **נערה בת N** / **נער בן N** — **never** hyphen junk like **17-למת** or other fake Hebrew-number mashups. "
    "No mixed scripts inside one word; standard Hebrew; paraphrase, no quotes. "
    "Vocabulary: use real Modern Hebrew words only—never invent pseudo-Hebrew that looks like a calque of Polish "
    '(e.g. Polish „zbiory"/„zbiór" = gathering/harvest → say איסוף or ליקוט, not nonsense like ״זבירות״). '
    "German names: read carefully—do not substitute look-alike cities (e.g. Koblenz is not München/Munich). "
    "German *Schleuse* in rivers/canals = a navigation lock: say תא נעילה or סכר נעילה (never meaningless strings like "
    "שעשוע connected to נעילה; *Moselschleuse* = lock on the Moselle—use Hebrew תא נעילה + Latin Mosel/Koblenz as in the source). "
    "If the article is German wire (dpa, ZEIT, etc.), keep German place names in Latin where Hebrew would be ambiguous.\n"
    "Marine mammals: **humpback** (*Humbak* / *humpback*) in Hebrew use **לוויתן גובהנן** or **לוויתן צדפי**, "
    "or **לוויתן** + Latin **Humbak** — not nonsense phonetic coinages. "
    "**Dramatic / serious condition** = **מצב חמור**, **חדשות דרמטיות**, **מאמצי הצלה** — **never** use **חבט חמור** "
    "(that reads as a physical blow; it is not Polish „dramatyczny”).\n"
    "Polish titles: **wiceminister** / **wice-** = **סגן שר** (deputy minister). Do not transliterate it as 'וויצה'.\n"
    "Polish **MSWiA** = *Ministerstwo Spraw Wewnętrznych i Administracji* (interior + public administration): say "
    "**משרד הפנים והמינהל** in Hebrew, or keep **MSWiA** in Latin after a short Hebrew gloss—**never** output **פקולטה** "
    "(that word means a university faculty; it is a wrong gloss for MSWiA).\n"
    "If there is no short standard term, use a plain periphrasis (e.g. חילזון היין / איסוף חילזונים). "
    "No hallucinations. **Single coherent story:** every sentence must follow only from the **same** article excerpt "
    "(title + body you were given). Do not invent an opening clause (scenes, crimes, places, or people not named there). "
    "If you output two sentences, both must describe this article only—never mix the main story with unrelated 'see also' "
    "or sidebar headlines. "
    "If place+event+outcome are clear (wires, TV/radio guest listings with names/shows/times, interviews: who said what), summarize. "
    "Diplomacy and foreign policy: **GO** only when Poland is explicitly in the story (Polish MFA, Sejm, government position, "
    "US ambassador **in Poland**, eastern flank **for PL**, EU row **naming Poland**). "
    "If other countries' officials debate among themselves and Poland never appears—SKIP, not Hebrew. "
    "Clear headline - summarize. Accidents with minors: dry facts only, not sensational.\n"
    "**Never** answer with Hebrew that **only** says there is no Polish involvement, no direct Poland tie, or that the supplied text "
    "does not concern Poland—that is **not** a channel summary; reply **SKIP** (one word) so the item is dropped.\n\n"
    f"Labels exactly: SKIP | INSUFFICIENT | Hebrew (≤{_SUMMARY_CAP} words)"
)

CLASSIFY_PROMPT = (
    "**Poland — national news channel (domestic-first).** Feeds are Polish outlets but include world wires and local crime.\n"
    "**GO** only if the excerpt clearly concerns **Poland at a national level**: Polish government/Sejm/Senate/presidency, "
    "national courts/constitutional issues, nationwide economy/price policy, nationwide security for Poland, or other country-wide issues.\n"
    "**GO** for foreign/security topics only when Poland's national institutions or officials are explicitly central (MFA/MON, "
    "Sejm vote, government decision, Polish agencies), not just that it happened in a Polish city.\n"
    "**SKIP** if: sports; or the story **lacks a direct Poland tie** (another country's internal affairs only, generic EU/Brussels desk, "
    "generic foreign-power politics) — **even when a Polish site syndicates it**; or **Hungary-only** rhetoric on Russia sanctions, "
    "EU energy, or oil pipelines (e.g. Orbán vs Brussels, Przyjaźń) **without Poland named or a Polish policy stake**; "
    "or **space/science foreign mission** stories (NASA/ESA missions, capsules, Artemis, launches, reentries) where Poland is mentioned only "
    "because a Polish observer (e.g. a university observatory in Warszawa) photographed it — treat that as **incidental** and **SKIP** unless "
    "there is a concrete Poland stake (Polish government/agency role, Polish funding/contract, Polish astronaut/mission role, or Poland policy/impact).\n"
    "or **Baltic/German coastal wildlife as long-history culture** (how people centuries ago reacted to whales, church art, general ecology essays) "
    "with **no current stranding, rescue, death toll, law, or Polish angle**; or a **Baltic-only** whale/dolphin rescue or death wire "
    "**with no Polish coast, agency, or citizens** in the excerpt.\n"
    "**SKIP** also for: celebrity/showbiz, lifestyle/service listicles (shopping/coupons/tips), horoscopes/quizzes, "
    "micro-local traffic/minor incidents without wider impact, and routine markets churn with no concrete decision; "
    "or **routine fuel max-price tables** (maksymalne ceny paliw, minister energii PLN/l caps, KAS pump fines); "
    "or **opinion polls / surveys** (sondaż, CBOS-style institutes, Opinia24, OGB / “Ogólnopolska Grupa Badawcza”, “what % of Poles think”, "
    "Gazeta-style reader URLs *zapytalismy-o-…*) "
    "including analysis or simulations based on them, rather than a dated decision or event.\n"
    "One word: SKIP or GO."
)

# HTTP client
REQUEST_CONNECT_TIMEOUT = 5
REQUEST_READ_TIMEOUT = 20
HTTP_RETRY_TOTAL = 3
HTTP_RETRY_BACKOFF = 0.5
HTTP_STATUS_FORCELIST = (502, 503, 504)

# OpenAI SDK
OPENAI_TIMEOUT_SEC = 90.0
OPENAI_MAX_RETRIES = 2

OPENAI_MODEL_CLASSIFY = os.environ.get("OPENAI_MODEL_CLASSIFY", "gpt-5.4-nano")
OPENAI_MODEL_SUMMARIZE = os.environ.get("OPENAI_MODEL_SUMMARIZE", "gpt-5.4-mini")
OPENAI_MODEL_EMAIL_DIGEST = os.environ.get("OPENAI_MODEL_EMAIL_DIGEST", OPENAI_MODEL_SUMMARIZE)

EMAIL_DIGEST_ENABLED = os.environ.get("EMAIL_DIGEST_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
EMAIL_TO = os.environ.get("EMAIL_TO", "tshprung@gmail.com")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "")

MIDDAY_MIN_ITEMS = 3
MIDDAY_HIGH_IMPORTANCE_SCORE = 35
MIDDAY_MIN_HIGH_IMPORTANCE_ITEMS = 1
