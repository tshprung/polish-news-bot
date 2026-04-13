"""Regression: JSON-LD body must not win if boilerplate trim deletes all useful text."""
import json
from unittest.mock import MagicMock

from article_fetch import fetch_article_body


def test_fetch_falls_back_to_dom_when_jsonld_trimmed_to_empty():
    """
    Onet-style: ld+json articleBody is mostly lines filtered by _trim_boilerplate (polecamy, etc.).
    Previously we logged 'Fetched 0 chars (JSON-LD)' and returned ''.
    """
    long_noise = "\n".join(
        [
            "Polecamy także inny artykuł o pogodzie w Europie i reklama partnera.",
            "Więcej na temat burz i alertów IMGW — przeczytaj również w serwisie.",
        ]
        * 40
    )
    ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "articleBody": long_noise,
        }
    )
    article_html = """
<article>
<p>Chmura pyłu saharyjskiego zbliża się do Polski; w kolejnych dniach zjawisko obejmie znaczną część kraju.</p>
<p>Stężenie będzie najwyższe na wysokości kilku kilometrów; wschody i zachody słońca przybiorą intensywniejszy kolor.</p>
<p>Instytut Meteorologii opisuje trasę przemieszczania się pyłu nad Europą Środkową wraz z mapami modeli.</p>
</article>
"""
    page = f"<html><head><script type=\"application/ld+json\">{ld}</script></head><body>{article_html}</body></html>"

    session = MagicMock()

    class Resp:
        content = page.encode("utf-8")
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    session.get.return_value = Resp()

    out = fetch_article_body(session, "https://wiadomosci.onet.pl/pogoda/example", (5, 15))
    assert len(out) >= 200
    assert "saharyjskiego" in out.lower() or "Polski" in out
