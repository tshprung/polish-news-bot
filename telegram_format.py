"""Count rendered Telegram text, not HTML markup or hidden link destinations."""
import html
from html.parser import HTMLParser
from urllib.parse import urlsplit


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def rendered_length(markup: str) -> int:
    parser = _Text()
    parser.feed(markup)
    # UTF-16 units are conservative for emoji/supplementary characters.
    return len("".join(parser.parts).encode("utf-16-le")) // 2


def source_label(item: dict) -> str:
    host = (urlsplit(item.get("url") or "").hostname or "").removeprefix("www.")
    names = {"rmf24.pl": "RMF24", "wiadomosci.onet.pl": "Onet", "wiadomosci.wp.pl": "WP",
             "wydarzenia.interia.pl": "Interia", "wiadomosci.gazeta.pl": "Gazeta.pl",
             "polsatnews.pl": "Polsat News", "tvn24.pl": "TVN24"}
    return names.get(host, host or item.get("source") or "מקור")


def format_digest_chunks(items: list[dict], date_label: str) -> list[tuple[str, list[dict]]]:
    header = f"🇵🇱 <b>חדשות פולין — {html.escape(date_label)}</b>"
    chunks = []
    message, batch = header, []
    for item in items:
        entry = "\n\n• " + html.escape(item["summary_he"], quote=False)
        entry += '\n<a href="' + html.escape(item["url"], quote=True) + '">' + html.escape(source_label(item)) + '</a>'
        if rendered_length(header + entry) > 4000:
            raise ValueError(f"Digest story {item['id']} exceeds Telegram's text limit")
        if batch and rendered_length(message + entry) > 4000:
            chunks.append((message, batch))
            message, batch = header, []
        message += entry
        batch.append(item)
    if batch:
        chunks.append((message, batch))
    return chunks
