import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import database
from database import (get_recent_story_items, get_unsent_telegram_digest_items,
                      mark_telegram_digest_items_sent, store_email_digest_item)
from email_digest import score_and_classify_item
from story_memory import repeated_story_id
from telegram_digest import _diversify_items, send_daily_telegram_digest


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'news.db')
    connection = database.init_db()
    yield connection
    connection.close()


def add(conn, key, summary='סיכום בעברית עם עובדות על התפתחות חדשה בפולין', category='politics', score=25):
    article = {'id': key, 'link': 'https://example.test/' + key, 'title': key,
               'source': 'Source', 'date': '', 'sort_key': datetime.now(timezone.utc)}
    store_email_digest_item(conn, article, summary, score, category)
    conn.commit()
    return article


def model_result(value, finish='stop'):
    client = MagicMock()
    choice = client.chat.completions.create.return_value.choices.__getitem__.return_value
    choice.message.content = json.dumps({'duplicate_id': value})
    choice.finish_reason = finish
    return client


def test_novelty_uses_both_pending_and_delivered_stories(conn):
    add(conn, 'pending')
    add(conn, 'alert')
    mark_telegram_digest_items_sent(conn, [2], 'alert', datetime.now(timezone.utc).isoformat())
    assert {x['id'] for x in get_recent_story_items(conn)} == {1, 2}
    client = model_result(2)
    assert repeated_story_id(conn, client, {'title': 'Reworded headline'}, 'אותן עובדות בניסוח אחר') == 2
    payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
    assert {x['id'] for x in payload['recent']} == {1, 2}


@pytest.mark.parametrize('value,finish', [(None, 'stop'), (999, 'stop'), (True, 'stop'), (1, 'length')])
def test_updates_unknown_ids_and_incomplete_responses_are_retained(conn, value, finish):
    add(conn, 'law approved')
    assert repeated_story_id(conn, model_result(value, finish), {'title': 'law cancelled'}, 'ההחלטה בוטלה') is None


def test_api_failure_preserves_coverage(conn):
    add(conn, 'previous')
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError('unavailable')
    assert repeated_story_id(conn, client, {'title': 'new'}, 'עובדות חדשות') is None


def test_no_history_avoids_api_call(conn):
    client = MagicMock()
    assert repeated_story_id(conn, client, {'title': 'new'}, 'חדש') is None
    client.chat.completions.create.assert_not_called()


def test_digest_marks_only_delivered_items_and_records_history(conn, monkeypatch):
    for i in range(6):
        add(conn, str(i))
    monkeypatch.setenv('NEWS_DIGEST_MAX_ITEMS', '4')
    monkeypatch.setenv('NEWS_DIGEST_ENABLED', '1')
    sender = MagicMock()
    monkeypatch.setattr('telegram_digest.send_to_telegram', sender)
    client = MagicMock()
    assert send_daily_telegram_digest(conn, client, None, (1, 1))
    assert len(get_unsent_telegram_digest_items(conn)) == 2
    assert conn.execute('SELECT count(*) FROM dedup_recent').fetchone()[0] == 4
    assert conn.execute("SELECT count(*) FROM email_digest_items WHERE telegram_digest_status = 'sent'").fetchone()[0] == 4
    client.chat.completions.create.assert_not_called()
    # Omitted items remain available for the next digest, then stop repeating.
    assert send_daily_telegram_digest(conn, client, None, (1, 1))
    assert get_unsent_telegram_digest_items(conn) == []
    assert not send_daily_telegram_digest(conn, client, None, (1, 1))


def test_failed_send_leaves_stories_pending(conn, monkeypatch):
    add(conn, 'a')
    monkeypatch.setattr('telegram_digest.send_to_telegram', MagicMock(side_effect=RuntimeError('send failed')))
    with pytest.raises(RuntimeError):
        send_daily_telegram_digest(conn, MagicMock(), None, (1, 1))
    assert len(get_unsent_telegram_digest_items(conn)) == 1
    assert conn.execute('SELECT count(*) FROM dedup_recent').fetchone()[0] == 0


def test_chunked_delivery_commits_each_successful_chunk(conn, monkeypatch):
    for i in range(4):
        add(conn, str(i), summary=('חדשות <בדיקה> & עובדות ' * 35))
    sender = MagicMock(side_effect=[None, RuntimeError('second chunk failed')])
    monkeypatch.setattr('telegram_digest.send_to_telegram', sender)
    with pytest.raises(RuntimeError):
        send_daily_telegram_digest(conn, MagicMock(), None, (1, 1))
    pending = get_unsent_telegram_digest_items(conn)
    assert 0 < len(pending) < 4
    message = sender.call_args_list[0].args[1]
    assert len(message) <= 3500
    assert '&lt;בדיקה&gt;' in message and message.count('<a ') == message.count('</a>')


def test_expired_queue_is_not_marked_delivered(conn):
    add(conn, 'stale')
    old = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    conn.execute('UPDATE email_digest_items SET created_at = ?', (old,))
    conn.commit()
    refreshed = database.init_db()
    assert get_unsent_telegram_digest_items(refreshed) == []
    assert refreshed.execute('SELECT telegram_digest_status, telegram_digest_sent_at FROM email_digest_items').fetchone() == ('expired', None)
    assert get_recent_story_items(refreshed) == []
    refreshed.close()


def test_breadth_is_soft_not_a_limit_on_distinct_events():
    items = [{'id': i, 'category': 'security', 'summary_he': text} for i, text in enumerate(
        ['רכישת ספינות לצבא', 'הקמת מקלטים בבתי ספר', 'אזהרת סייבר לבתי חולים'])]
    assert _diversify_items(items, 8) == items


@pytest.mark.parametrize('title,category', [
    ('Sejm uchwalił ustawę o ochronie zdrowia', 'health'),
    ('Rząd zatwierdził reformę szkół', 'education'),
    ('Rząd wprowadza zmiany podatków', 'economy'),
    ('NBP obniża stopy procentowe', 'economy'),
])
def test_national_decisions_qualify_for_alerts(title, category):
    score, actual_category, _ = score_and_classify_item(title, '', '', '')
    assert score >= 40 and actual_category == category


def test_city_name_does_not_boost_routine_crime_into_alert():
    score, _, region = score_and_classify_item('Wrocław: policja zatrzymała sprawcę napadu', '', '', '')
    assert score < 40 and region


def test_regional_emergency_is_not_discarded_before_fetch():
    from config import should_skip_non_national_poland_teaser
    assert not should_skip_non_national_poland_teaser('Ewakuacja szpitala w Katowicach', 'Awaria zasilania. Pacjenci są ewakuowani.')


def test_short_regional_rss_fetches_body_before_rejecting(monkeypatch):
    from summarize import summarize_in_hebrew
    fetch = MagicMock(return_value='Ewakuacja szpitala w Katowicach po awarii zasilania. Pacjenci przewiezieni do innych placówek.')
    monkeypatch.setattr('summarize.fetch_article_body', fetch)
    client = MagicMock()
    responses = []
    for text in ['GO', 'בית חולים בקטוביץ פונה בעקבות תקלה בחשמל. המטופלים הועברו לבתי חולים אחרים.']:
        response = MagicMock()
        response.choices[0].message.content = text
        response.choices[0].finish_reason = 'stop'
        responses.append(response)
    client.chat.completions.create.side_effect = responses
    summary, reason = summarize_in_hebrew(client, MagicMock(), (1, 1), {
        'title': 'Ewakuacja szpitala w Katowicach. Pacjenci przewożeni do innych placówek',
        'summary': '', 'link': 'https://example.test/evacuation',
    })
    assert summary and reason is None
    fetch.assert_called_once()


def test_existing_statusless_database_migrates_without_resending_history(conn):
    add(conn, 'sent')
    add(conn, 'pending')
    mark_telegram_digest_items_sent(conn, [1], 'alert', datetime.now(timezone.utc).isoformat())
    conn.execute('ALTER TABLE email_digest_items DROP COLUMN telegram_digest_status')
    conn.commit()
    migrated = database.init_db()
    assert [x['article_id'] for x in get_unsent_telegram_digest_items(migrated)] == ['pending']
    assert migrated.execute('SELECT telegram_digest_status FROM email_digest_items WHERE id=1').fetchone()[0] == 'sent'
    migrated.close()
