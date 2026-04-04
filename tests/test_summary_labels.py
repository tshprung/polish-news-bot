from summarize import strip_leading_summary_labels


def test_strip_ibrit_prefix():
    s = "עברית: שריפה ב-Cottbus נמשכת."
    assert strip_leading_summary_labels(s) == "שריפה ב-Cottbus נמשכת."
