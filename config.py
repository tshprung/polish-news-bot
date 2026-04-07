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

# Only ingest RSS items from the last 24 hours.
MAX_ARTICLE_AGE_HOURS = 24

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


# Admin DM noise: main.py skips Telegram notify when skip_reason starts with any of these prefixes.
SKIP_NOTIFY_EXEMPT_PREFIXES = (
    "rss teaser:",
    "pan-eu guide:",
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


PAYWALLED_DOMAINS = {"pro.rp.pl", "rp.pl", "wyborcza.pl"}

MAX_SUMMARY_WORDS = 50
MAX_SUMMARY_WORDS_HARD = 60

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = Path(os.environ.get("DB_PATH", "/opt/polish_news/seen.db"))

# Weekly community message (cron in Europe/Warsaw or set WEEKLY_ANNOUNCE_TZ); Sunday 18:00 default.
WEEKLY_ANNOUNCE_ENABLED = os.environ.get("WEEKLY_ANNOUNCE_ENABLED", "1") == "1"
WEEKLY_ANNOUNCE_TZ = os.environ.get("WEEKLY_ANNOUNCE_TZ", "Europe/Warsaw")
WEEKLY_ANNOUNCE_WEEKDAY = int(os.environ.get("WEEKLY_ANNOUNCE_WEEKDAY", "6"))
WEEKLY_ANNOUNCE_HOUR = int(os.environ.get("WEEKLY_ANNOUNCE_HOUR", "18"))
WEEKLY_ANNOUNCE_SUPPORT_EMAIL = os.environ.get(
    "WEEKLY_ANNOUNCE_SUPPORT_EMAIL", "tshprung@gmail.com"
)
WEEKLY_ANNOUNCE_KOFI_URL = os.environ.get(
    "WEEKLY_ANNOUNCE_KOFI_URL", "https://ko-fi.com/talshprung"
)

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
    "**Channel scope — Poland national news:** Cover **Poland** first. International, EU, or third-country stories are **GO** "
    "only when the excerpt **directly** involves Poland: Polish institutions or officials, Polish citizens where the story is "
    "about them as **Poland**, border, economy or security **for Poland**, bilateral rows naming PL, or Polish government position "
    "on an external event. If the same wire would fit readers in another country with no Poland-specific facts—**SKIP**, even on Onet/TVN/etc.\n\n"
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
    "SKIP - entertainment / Unterhaltung chat (e.g. BILD MayWay) whose teaser is only ‘show X hosted politician Y’ "
    "with no bill, vote, scandal fact, or policy outcome stated.\n"
    "SKIP - private **medical fundraiser** or family **donation appeal** (zbiórka / zrzutka / help pay for therapy abroad) — not NFZ, "
    "ministerial programs, or law.\n"
    "SKIP - service/lifestyle and low-signal noise: shopping/coupons/listicles, horoscopes/quizzes, travel/restaurant 'what to do', "
    "celebrity/showbiz, and micro-local updates like minor traffic closures or small incidents without broader public impact.\n"
    "SKIP - weather micro-updates: keep only major warnings/extremes or rate-limited forecast beats.\n"
    "SKIP - markets daily churn (crypto/stock up-down today) unless there is a concrete enforcement/regulatory decision, major platform outage, "
    "or clear Poland impact.\n"
    "INSUFFICIENT - only when the body truly adds almost nothing beyond the title: "
    "no names, no agencies, no dates or numbers, no quoted/attributed claims, no decision you can state in one clause.\n"
    f"Hebrew - 1-2 sentences, ≤{_SUMMARY_CAP} words\n\n"
    "If the Polish text includes any of: named people or agencies, dates, figures/statistics, permits/bans/decisions, "
    "or who said what— you must output Hebrew summarizing those facts; do not answer INSUFFICIENT. "
    "Interviews, diplomacy, and regional/environmental regulation count as enough to summarize.\n\n"
    "Every Hebrew-line answer must contain Hebrew script; never reply with English-only or Polish-only Latin sentences. "
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
    "Polish **MSWiA** = *Ministerstwo Spraw Wewnętrznych i Administracji* (interior + public administration): say "
    "**משרד הפנים והמינהל** in Hebrew, or keep **MSWiA** in Latin after a short Hebrew gloss—**never** output **פקולטה** "
    "(that word means a university faculty; it is a wrong gloss for MSWiA).\n"
    "If there is no short standard term, use a plain periphrasis (e.g. חילזון היין / איסוף חילזונים). "
    "No hallucinations. If place+event+outcome are clear (wires, TV/radio guest listings with names/shows/times, interviews: who said what), summarize. "
    "Diplomacy and foreign policy: **GO** only when Poland is explicitly in the story (Polish MFA, Sejm, government position, "
    "US ambassador **in Poland**, eastern flank **for PL**, EU row **naming Poland**). "
    "If other countries' officials debate among themselves and Poland never appears—SKIP, not Hebrew. "
    "Clear headline - summarize. Accidents with minors: dry facts only, not sensational.\n\n"
    f"Labels exactly: SKIP | INSUFFICIENT | Hebrew (≤{_SUMMARY_CAP} words)"
)

CLASSIFY_PROMPT = (
    "**Poland — national news channel.** Feeds are Polish outlets but include world wires.\n"
    "**GO** if the excerpt clearly concerns **Poland**: events on PL territory, Polish actors and institutions, or an international/EU story "
    "where **Poland is explicitly involved** (named, affected, border, policy position, citizens as the Polish angle).\n"
    "**SKIP** if: sports; or the story **lacks a direct Poland tie** (another country's internal affairs only, generic EU/Brussels desk, "
    "generic foreign-power politics) — **even when a Polish site syndicates it**; or **Hungary-only** rhetoric on Russia sanctions, "
    "EU energy, or oil pipelines (e.g. Orbán vs Brussels, Przyjaźń) **without Poland named or a Polish policy stake**.\n"
    "**SKIP** also for: celebrity/showbiz, lifestyle/service listicles (shopping/coupons/tips), horoscopes/quizzes, "
    "micro-local traffic/minor incidents without wider impact, and routine markets churn with no concrete decision.\n"
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
