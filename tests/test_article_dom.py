from article_fetch import _article_body_from_dom


def test_onet_intel_interview_pull_quote_then_line_broken_divs():
    """Regression: Tylko w Onecie — lead quote + body split across many short lines in divs."""
    # Mirrors pages where JSON-LD has no articleBody; main copy lives in divs with hard line breaks.
    inner = "\n".join(
        [
            '"Iran będzie wywierał presję" — zapowiedź dyplomatyczna otwiera skrótowy blok.',
            "Choć Europa nie bierze",
            "bezpośredniego udziału w konflikcie na Bliskim Wschodzie",
            ", to w przestrzeni publicznej coraz częściej pojawiają się obawy o zamachy.",
            "Były szef Agencji Wywiadu, płk Jan Kowalski, przyznaje, że służby monitorują scenariusze.",
        ]
        + [f"Akapit uzupełniający z konkretnymi faktami numer {i} o bezpieczeństwie." for i in range(25)]
    )
    stripped = f"""<html><body>
<div class="ods-article-body">
<div class="ods-a-body-text">{inner}</div>
<p>Krótki cytat z boxa.</p>
</div></body></html>"""
    text = _article_body_from_dom(stripped)
    assert len(text) >= 800
    assert "Agencji Wywiadu" in text
    assert "Bliskim Wschodzie" in text


def test_onet_breaking_news_short_fragments_and_paragraphs():
    """Regression: lokalna wiadomość — akapity często krótkie; część linii &lt; 13 znaków w surowym get_text."""
    stripped = f"""<html><body>
<article>
<div class="ods-article-body">
<p>Do groźnego incydentu doszło w piątek ok. godz. 15:30 przed kościołem na warszawskim Mokotowie.</p>
<div class="ods-a-body-text">Zapalił się tam krzyż</div>
<p>Na miejsce skierowani zostali strażacy oraz funkcjonariusze i trwa akcja ratunkowa opisana przez rzecznika.</p>
<div>ul. Przykładowa przy starej zabudowie</div>
<p>Kapłan prosił wiernych o spokój; policja wyjaśnia okoliczności i zbiera zeznania świadków z sąsiedztwa.</p>
{"<p>Kolejny akapit z opisem przebiegu akcji gaśniczej i stanu zabezpieczeń.</p>" * 8}
</div>
</article>
</body></html>"""
    text = _article_body_from_dom(stripped)
    assert len(text) >= 500
    assert "Mokotowie" in text or "warszawskim" in text
    assert "strażacy" in text


def test_dom_does_not_replace_long_primary_with_few_short_paragraphs():
    """Regression: Onet Politico — most copy in divs; <p> are only pull-quotes."""
    body_inner = ("Zdanie z treścią artykułu. " * 120)  # long running text as div-only
    stripped = f"""<html><body>
<div class="ods-article-body">
<div>{body_inner}</div>
<p>Krótki cytat jednorazowy do pull boxa w portalu.</p>
<p>Drugi krótki cytat nie będzie całym tekstem.</p>
</div></body></html>"""
    text = _article_body_from_dom(stripped)
    assert len(text) > 2000
    assert "Zdanie z treścią" in text
    assert "Krótki cytat" not in text or len(text) > 500
