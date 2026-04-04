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
    "#pl_weather_forecast",
    "#nato_us_poland",
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
    "Catholic/Easter processions, pilgrimages, and night services in Polish cities = Poland; do not map them to Israel.\n"
    "Polish cities, towns, and regions: always write them in Latin exactly as in the article, inside the Hebrew line—"
    "never as Hebrew-only placenames (wrong: פרזמישל for Przemyśl; wrong: בגדה or Hebrew phonetics for Gdańsk—reads like unrelated geography). "
    "Right pattern: Hebrew words + Latin city (e.g. …ב-Gdańsk, …ב-Warszawa, …ב-Kraków). "
    "For the country as a whole, use Hebrew פולין (e.g. בפולין, תושבי פולין)—not the Polish word 'Polska' or ב-Polska (confusing hybrid). "
    "Do not put Israeli cities (תל אביב, ירושלים, etc.) instead of Polish ones. "
    "Syrenka / pomnik Syrenki = Warsaw mermaid monument in Warszawa, not Israel.\n\n"
    "Reply with exactly one line, no preamble:\n"
    "SKIP - sports; or no Polish internal angle; or no practical impact on life in Poland; OR wire that is only generic "
    "great-power/US politics (e.g. Trump and NATO, US senators of both parties warning the White House) where "
    "only American actors are named and the text does not state Polish institutions, Polish officials, or a concrete Polish stake. "
    "A Polish outlet republishing Reuters/AP is still SKIP if the facts are US-only with no Poland hook.\n"
    "INSUFFICIENT - only when the body truly adds almost nothing beyond the title: "
    "no names, no agencies, no dates or numbers, no quoted/attributed claims, no decision you can state in one clause.\n"
    f"Hebrew - 1-2 sentences, ≤{_SUMMARY_CAP} words\n\n"
    "If the Polish text includes any of: named people or agencies, dates, figures/statistics, permits/bans/decisions, "
    "or who said what— you must output Hebrew summarizing those facts; do not answer INSUFFICIENT. "
    "Interviews, diplomacy, and regional/environmental regulation count as enough to summarize.\n\n"
    "Every Hebrew-line answer must contain Hebrew script; never reply with English-only or Polish-only Latin sentences. "
    "When outputting Hebrew, write only the summary text—never prefix with עברית:, תרגום:, Hebrew:, Summary:, or similar. "
    "Hebrew line must start with Hebrew; Latin for personal names, all Polish place names (Gdańsk, Gdynia, Trójmiasto, etc.—as in source), acronyms (NATO, PiS). "
    "No mixed scripts inside one word; standard Hebrew; paraphrase, no quotes. "
    "Vocabulary: use real Modern Hebrew words only—never invent pseudo-Hebrew that looks like a calque of Polish "
    '(e.g. Polish „zbiory"/„zbiór" = gathering/harvest → say איסוף or ליקוט, not nonsense like ״זבירות״). '
    "If there is no short standard term, use a plain periphrasis (e.g. חילזון היין / איסוף חילזונים). "
    "No hallucinations. If place+event+outcome are clear (wires, TV/radio guest listings with names/shows/times, interviews: who said what), summarize. "
    "Diplomacy and foreign policy: summarize when Polish or EU-with-clear-PL actors appear, or when Polish government/opposition "
    "reactions or risks to Poland are explicit. If the article is only US officials debating among themselves about NATO/US alliances "
    "and Poland is not part of the story—answer SKIP, not Hebrew. "
    "US ambassador in Poland, Polish MFA, Sejm, eastern flank affecting PL: those are GO material when facts are present; not INSUFFICIENT. "
    "Clear headline - summarize. Accidents with minors: dry facts only, not sensational.\n\n"
    f"Labels exactly: SKIP | INSUFFICIENT | Hebrew (≤{_SUMMARY_CAP} words)"
)

CLASSIFY_PROMPT = (
    "Filter for a Poland-focused channel; the feed is Polish outlets but includes global wires.\n"
    "SKIP if: (1) sports; OR (2) story is mostly US domestic US politics / US Congress / both US parties on Trump or NATO, "
    "and the excerpt does NOT mention Polish officials, Polish institutions, or a concrete consequence for Poland; OR "
    "(3) other foreign items with no Poland/Poles/Polish policy angle.\n"
    "GO if: events in Poland, Polish actors, EU/NATO stories where Poland's role, border, government position, or domestic impact is in the text, "
    "or crime/economy/weather/accidents tied to PL.\n"
    "Rule of thumb: if the only named politicians are American and the topic is generic transatlantic debate without Poland—SKIP (do not default to GO).\n"
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
