import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from hebrew_editor import edit_hebrew_items
from summarize import _HEBREW_RETRY_SENTINEL, _postprocess_hebrew_summary
from email_digest import score_and_classify_item
from database import telegram_digest_day_state, complete_telegram_digest_day
from telegram_digest import _max_items, _diversify_items


def client_for(items, finish='stop'):
    client = MagicMock()
    choice = client.chat.completions.create.return_value.choices[0]
    choice.finish_reason = finish
    choice.message.content = json.dumps({'items': items}, ensure_ascii=False)
    return client


def test_latin_subject_is_not_deleted():
    text = 'Sejm דן ביוזמת PSL לבטל את מגבלת שתי הקדנציות לראשי רשויות מקומיות.'
    result, reason = _postprocess_hebrew_summary(text, 'Sejm debatuje nad projektem')
    assert result == text and reason is None


def test_mixed_script_is_retried_without_deleting_letters():
    text = 'מDowództwo החלו לתת גיבוי לעובדי המחוז ולהתרעות האוויריות באזור.'
    result, reason = _postprocess_hebrew_summary(text, '')
    assert result == text and reason == _HEBREW_RETRY_SENTINEL


def test_complete_hebrew_sentences_and_institutions_are_used():
    inputs = [
        {'id': 1, 'title': 'Sejm może powiedzieć tak', 'summary_he': 'דן ביוזמת PSL לבטל את מגבלת שתי הקדנציות לראשי רשויות מקומיות.'},
        {'id': 2, 'title': 'Alert RCB', 'summary_he': 'רכזת ביטחון הממשלה (RCB) שלחה התרעת חירום לתושבי חלקים ממחוז פודקרפצקיה.'},
        {'id': 3, 'title': 'Wsparcie Dowództwa', 'summary_he': 'מבר\'ודב החלו לתת גיבוי לעובדי המחוז שמאזינים לאזהרות אוויריות.'},
    ]
    edits = [
        {'id': '1', 'summary_he': 'הסיים דן ביוזמת מפלגת PSL לבטל את מגבלת שתי הקדנציות לראשי רשויות מקומיות.'},
        {'id': '2', 'summary_he': 'המרכז הממשלתי לביטחון (RCB) שלח התרעת חירום לתושבי חלקים ממחוז פודקרפצקיה.'},
        {'id': '3', 'summary_he': 'פיקוד Dowództwo החל לסייע לעובדי המחוז בניטור התרעות אוויריות.'},
    ]
    client = client_for(list(reversed(edits)))
    result = edit_hebrew_items(client, inputs)
    assert [item['id'] for item in result] == [1, 2, 3]
    assert [item['summary_he'] for item in result] == [item['summary_he'] for item in edits]
    # Verify originals are retained so the editor can repair subjects and names.
    payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
    assert payload['items'][0]['title'] == inputs[0]['title']
    assert inputs[0]['summary_he'].startswith('דן')


@pytest.mark.parametrize('edits', [
    [],
    [{'id': '999', 'summary_he': 'דיווח בעברית ארוך מספיק ומתאר אירוע בפולין.'}],
    [{'id': '1', 'summary_he': 'השינוי ייכנס לתוקף בשנת 2028, לפי ההודעה הרשמית.'}],
    [{'id': '1', 'summary_he': 'Polish-only wstrzymano obrot natychmiast we wszystkich seriach 2027'}],
    [{'id': '1', 'summary_he': 'דיווח לשנת 2027'}, {'id': '1', 'summary_he': 'דיווח נוסף לשנת 2027'}],
])
def test_bad_or_fact_changing_edit_is_never_delivered(edits):
    with pytest.raises(ValueError):
        edit_hebrew_items(client_for(edits), [{'id': 1, 'title': 'Plan na rok 2027',
            'summary_he': 'התוכנית תיכנס לתוקף בשנת 2027, לפי ההודעה הרשמית.'}])


def test_incomplete_edit_cannot_drop_stories():
    with pytest.raises(ValueError):
        edit_hebrew_items(client_for([], finish='length'), [{'id': 1, 'title': '', 'summary_he': 'עובדות'}])


def score(title):
    return score_and_classify_item(title, '', '', '')[0]


def test_concrete_developments_outrank_political_reactions():
    statement = score('Prezydent Nawrocki twierdzi, że nie ma z kim rozmawiać o sprawach Polski')
    criticism = score('Ekonomistka o ustawie o wynagrodzeniach lekarzy: To tylko plaster na jeden problem')
    assert score('Raport komisji śledczej ds. Pegasusa przyjęty') > statement
    assert score('Alert RCB w związku z atakiem na Ukrainę') > statement
    assert score('Sejm przyjął ustawę o wynagrodzeniach lekarzy') > criticism
    assert score('Ban na media społecznościowe. Projekt ustawy prawie gotowy') > statement


def test_commentary_mentioning_a_decision_is_still_commentary():
    assert score('Prezydent skrytykował decyzję rządu') < score('Rząd zatwierdził reformę szkół')


def test_category_breadth_never_evicts_major_news_for_trivial_reaction():
    major = [{'id': i, 'importance_score': 80, 'category': 'politics'} for i in range(4)]
    reaction = {'id': 5, 'importance_score': 20, 'category': 'other'}
    assert _diversify_items(major + [reaction], 4) == major


@pytest.mark.parametrize('configured,expected', [('8',8), ('10',10), ('100',10), ('bad',8)])
def test_eight_default_ten_maximum(monkeypatch, configured, expected):
    monkeypatch.setenv('NEWS_DIGEST_MAX_ITEMS', configured)
    assert _max_items() == expected


def test_default_eight(monkeypatch):
    monkeypatch.delenv('NEWS_DIGEST_MAX_ITEMS', raising=False)
    assert _max_items() == 8


def test_daily_only_by_default_even_with_old_alert_score_setting(monkeypatch):
    from main import _immediate_alerts_enabled
    monkeypatch.delenv('NEWS_TELEGRAM_ALERTS_ENABLED', raising=False)
    monkeypatch.setenv('NEWS_TELEGRAM_MIN_SCORE', '40')
    assert not _immediate_alerts_enabled()
    monkeypatch.setenv('NEWS_TELEGRAM_ALERTS_ENABLED', '1')
    assert _immediate_alerts_enabled()


def test_calendar_day_count_excludes_alerts_and_handles_warsaw_midnight(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'news.db')
    conn = database.init_db()
    now = datetime(2026, 10, 21, 20, tzinfo=ZoneInfo('Europe/Warsaw'))
    for aid, stamp, slot in [('digest', '2026-10-20T22:15:00+00:00', 'evening'),
                             ('old', '2026-10-20T20:00:00+00:00', 'evening'),
                             ('alert', now.isoformat(), 'alert')]:
        database.store_email_digest_item(conn, {'id': aid, 'link': 'https://ex.test/' + aid,
             'title': aid, 'source': 'News'}, 'סיכום עברי ארוך מספיק המתאר אירוע בפולין')
        item_id = conn.execute('SELECT id FROM email_digest_items WHERE article_id = ?', (aid,)).fetchone()[0]
        database.mark_telegram_digest_items_sent(conn, [item_id], slot, stamp)
    assert telegram_digest_day_state(conn, now) == (False, 1)
    complete_telegram_digest_day(conn, now)
    assert telegram_digest_day_state(conn, now) == (True, 1)
    assert telegram_digest_day_state(conn, now + timedelta(days=1)) == (False, 0)
    conn.close()
