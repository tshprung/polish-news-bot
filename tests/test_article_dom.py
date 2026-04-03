from article_fetch import _article_body_from_dom


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
