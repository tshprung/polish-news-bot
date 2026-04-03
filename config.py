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

DEDUP_WINDOW_HOURS = 8
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

_DEDUP_SHORT_TOKENS_OK = frozenset({"ke", "tk", "ue", "lr"})

_TOPIC_DEDUP_TAGS = frozenset({
    "#tram_accident",
    "#komendant_speed",
    "#lodz_crime_factory",
    "#easter_weather",
    "#nato_us_poland",
})
# Shared topic tag alone is too loose; require this many overlapping non-tag tokens too.
TOPIC_DEDUP_MIN_LEXICAL = 2

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

PAYWALLED_DOMAINS = {"pro.rp.pl", "rp.pl", "wyborcza.pl"}

MAX_SUMMARY_WORDS = 40
MAX_SUMMARY_WORDS_HARD = 48

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = Path(os.environ.get("DB_PATH", "/opt/polish_news/seen.db"))

_SUMMARY_CAP = str(MAX_SUMMARY_WORDS)
SYSTEM_PROMPT = (
    "Hebrew Telegram blurbs from Polish media. Readers: Hebrew speakers in Poland; national news; keep Polish context. "
    "Assume Poland unless stated otherwise. Polish people = פולנים (never ישראלים).\n"
    "GEO: Every article is Polish domestic news unless the text explicitly says another country. "
    "Polish cities, towns, and regions: keep the Polish (Latin) spelling from the article "
    "(e.g. Przemyśl, Warszawa, Kraków, Łódź, Gdańsk)—do not write them in Hebrew letters (wrong: פרזמישל for Przemyśl). "
    "Never put תל אביב or ירושלים (or other Israeli places) in place of Polish locations. "
    "Syrenka / pomnik Syrenki = Warsaw mermaid monument in Warszawa, not Israel.\n\n"
    "Reply with exactly one line, no preamble:\n"
    "SKIP - sports; or no Polish internal angle; or no practical impact on life in Poland\n"
    "INSUFFICIENT - key facts missing/unclear, or body adds almost nothing beyond the title\n"
    f"Hebrew - 1-2 sentences, ≤{_SUMMARY_CAP} words\n\n"
    "Hebrew line must start with Hebrew; Latin for personal names, Polish place names (as in source), acronyms (NATO, PiS). "
    "No mixed scripts inside one word; standard Hebrew; paraphrase, no quotes. "
    "No hallucinations. If place+event+outcome are clear (wires, TV/radio guest listings with names/shows/times, interviews: who said what), summarize. "
    "Diplomacy and foreign-policy wires (e.g. US ambassador in Poland, EU/Iran/NATO): if officials are named and quoted or paraphrased, summarize factually; not INSUFFICIENT. "
    "Clear headline - summarize. Accidents with minors: dry facts only, not sensational.\n\n"
    f"Labels exactly: SKIP | INSUFFICIENT | Hebrew (≤{_SUMMARY_CAP} words)"
)

CLASSIFY_PROMPT = (
    "Filter for a Poland-focused channel; feed is already Polish outlets.\n"
    "SKIP only: foreign story with zero Poland tie, or sports. "
    "GO for politics, crime, economy, society, weather, accidents, or any Poland/Poles angle; if unsure, GO.\n"
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
