import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from editorial import select_editorial_items
from hebrew_editor import edit_hebrew_items, numeric_tokens
from retry_queue import (is_translation_failure, schedule_article_retry, retry_articles_and_states,
                         resolve_article_retry)
from summarize import _postprocess_hebrew_summary
from telegram_format import format_digest_chunks, rendered_length


def response_client(payload):
    client = MagicMock()
    choice = client.chat.completions.create.return_value.choices[0]
    choice.finish_reason = 'stop'
    choice.message.content = json.dumps(payload, ensure_ascii=False)
    return client


@pytest.mark.parametrize('hyphen', ['-', '־', '‐', '‑'])
def test_valid_hebrew_prefixes_do_not_trigger_non_hebrew_failure(hyphen):
    summary = f'לפי דוח ה{hyphen}NIK, נמצאו ליקויים בתפקוד כוחות ההגנה הטריטוריאלית בפולין.'
    result, reason = _postprocess_hebrew_summary(summary, 'NIK skontrolowała WOT')
    assert result and reason is None
    assert 'NIK' in result


def test_hidden_urls_and_html_do_not_force_an_unnecessary_split():
    items = [{'id': i, 'summary_he': ' '.join(['חדשות חשובות לתושבי פולין'] * 9),
              'url': 'https://www.rmf24.pl/news/' + 'a' * 250 + '?a=1&b=2', 'source': 'Very long source title ' * 5}
             for i in range(8)]
    chunks = format_digest_chunks(items, '28.10.2026')
    assert len(chunks) == 1 and len(chunks[0][1]) == 8
    assert len(chunks[0][0]) > 4096
    assert rendered_length(chunks[0][0]) < 4000
    assert '>RMF24</a>' in chunks[0][0]


def test_rendered_emoji_units_and_escaped_angles_are_counted():
    assert rendered_length('<b>😀</b> &lt;x&gt; <a href="https://x.test/very-long">מקור</a>') == 11


def test_source_can_correct_people_to_families():
    source = 'Budynek zamieszkiwany przez dziewięć rodzin. Ewakuowało się 13 dorosłych oraz 3 dzieci.'
    text = 'בבניין התגוררו תשע משפחות. בעקבות השריפה התפנו ממנו 13 מבוגרים ו-3 ילדים.'
    client = response_client({'items': [{'id': '1', 'verified': True,
        'evidence': ['Budynek zamieszkiwany przez dziewięć rodzin.', 'Ewakuowało się 13 dorosłych oraz 3 dzieci.'],
        'summary_he': text}]})
    result = edit_hebrew_items(client, [{'id': 1, 'title': 'Pożar budynku', 'source_text': source,
        'summary_he': 'בבניין התגוררו תשעה בני משפחה. התפנו ממנו 13 מבוגרים ו-3 ילדים.'}])
    assert result[0]['summary_he'] == text
    assert 'source_text' in json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])['items'][0]


@pytest.mark.parametrize('verified,evidence,text', [
    (True, ['Invented quotation not in the source.'], 'בפולין הוצע שינוי בחוק שיחול משנת 2027.'),
    (True, ['Projekt ustawy wejdzie w życie w 2027 roku.'], 'בפולין הוצע שינוי בחוק שיחול משנת 2028.'),
])
def test_false_evidence_and_unsupported_numbers_cannot_publish(verified, evidence, text):
    client = response_client({'items':[{'id':'1','verified':verified,'evidence':evidence,'summary_he':text}]})
    assert edit_hebrew_items(client, [{'id':1,'title':'Projekt','source_text':'Projekt ustawy wejdzie w życie w 2027 roku.',
            'summary_he':'בפולין הוצע שינוי בחוק שיחול משנת 2027.'}]) == []


def test_unverifiable_item_stays_pending_instead_of_sending_corrupt_text():
    client = response_client({'items':[{'id':'1','verified':False,'evidence':[],'summary_he':''}]})
    assert edit_hebrew_items(client,[{'id':1,'source_text':'Original source without sufficient facts.', 'summary_he':'סיכום חסר'}]) == []


def test_polish_and_english_number_formatting_matches():
    assert numeric_tokens('2 047,34 zł') == numeric_tokens('2,047.34 זלוטי')


def test_source_evidence_accepts_outer_polish_quotation_marks():
    source = 'Policjant ma 43 lata i został zatrzymany.'
    client = response_client({'items': [{'id': '1', 'verified': True,
        'evidence': ['„Policjant ma 43 lata i został zatrzymany.”'],
        'summary_he': 'שוטר בן 43 נעצר בפולין.'}]})
    result = edit_hebrew_items(client, [{'id': 1, 'source_text': source,
        'summary_he': 'שוטר בן 43 נעצר בפולין.'}])
    assert len(result) == 1


def test_malformed_age_gets_one_targeted_retry_with_feedback():
    source = 'Policjant ma 43 lata i został zatrzymany.'
    client = response_client({})
    responses = []
    for text in ['שוטר 43-לטי נעצר בפולין.', 'שוטר בן 43 נעצר בפולין.']:
        response = MagicMock()
        response.choices[0].finish_reason = 'stop'
        response.choices[0].message.content = json.dumps({'items': [{'id': '1', 'verified': True,
            'evidence': [source], 'summary_he': text}]}, ensure_ascii=False)
        responses.append(response)
    client.chat.completions.create.side_effect = responses
    result = edit_hebrew_items(client, [{'id': 1, 'source_text': source, 'summary_he': 'שוטר 43שנה בן נעצר בפולין.'}])
    assert result[0]['summary_he'] == 'שוטר בן 43 נעצר בפולין.'
    assert client.chat.completions.create.call_count == 2
    assert 'validation_feedback' in client.chat.completions.create.call_args.kwargs['messages'][1]['content']


def test_translation_retries_are_bounded_and_not_editorial_skips(monkeypatch):
    import sqlite3
    conn = sqlite3.connect(':memory:')
    current = int(datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr('retry_queue.time.time', lambda: current)
    article = {'id':'a','title':'NIK WOT','sort_key':datetime.now(timezone.utc)}
    assert is_translation_failure('mixed-script formatting after retry')
    assert is_translation_failure('GEO mismatch (Warsaw vs Tel Aviv)')
    assert not is_translation_failure('rss teaser: public opinion poll')
    assert schedule_article_retry(conn, article, 'mixed-script formatting after retry')
    due, states = retry_articles_and_states(conn)
    assert not due and states['a']=='pending'
    monkeypatch.setattr('retry_queue.time.time', lambda: current + 1801)
    due, _ = retry_articles_and_states(conn)
    assert due[0]['id']=='a' and isinstance(due[0]['sort_key'],datetime)
    assert schedule_article_retry(conn, due[0], 'non-Hebrew prose')
    assert not schedule_article_retry(conn, due[0], 'non-Hebrew prose')
    assert retry_articles_and_states(conn)[1]['a']=='exhausted'
    conn.close()


def test_success_resolves_retry(monkeypatch):
    import sqlite3
    conn=sqlite3.connect(':memory:')
    schedule_article_retry(conn, {'id':'a','title':'NIK WOT'}, 'runtime')
    resolve_article_retry(conn,'a')
    assert retry_articles_and_states(conn)[1]['a']=='resolved'
    conn.close()


def test_ingestion_failure_is_retried_then_resolved_without_losing_story(tmp_path, monkeypatch):
    import database, main
    import sqlite3
    path=tmp_path/'news.db'
    monkeypatch.setattr(database,'DB_PATH',path)
    article={'id':'NIK-source','title':'NIK skontrolowała WOT','summary':'Raport kontroli wojsk.',
             'link':'https://example.test/report','source':'News','date':'',
             'sort_key':datetime.now(timezone.utc),'source_text':'NIK wykazała nieprawidłowości w WOT.'}
    monkeypatch.setattr(main,'get_new_articles',lambda conn:[dict(article)])
    monkeypatch.setattr(main,'openai_client',MagicMock())
    monkeypatch.setattr(main,'make_http_session',MagicMock())
    notify=MagicMock()
    monkeypatch.setattr(main,'notify_admin',notify)
    monkeypatch.setattr(main,'summarize_in_hebrew',lambda *args:(None,'mixed-script formatting after retry'))
    monkeypatch.setenv('NEWS_TELEGRAM_ALERTS_ENABLED','0')
    main.run_ingestion()
    conn=sqlite3.connect(path)
    assert conn.execute('SELECT count(*) FROM seen_articles').fetchone()[0]==0
    assert conn.execute('SELECT status FROM article_retries').fetchone()[0]=='pending'
    conn.close()
    notify.assert_not_called()
    monkeypatch.setattr(main,'summarize_in_hebrew',lambda *args:('רשות הביקורת מצאה ליקויים בתפקוד כוחות ההגנה הטריטוריאלית בפולין.',None))
    monkeypatch.setattr(main,'repeated_story_id',lambda *args:None)
    main.run_ingestion()
    conn=sqlite3.connect(path)
    assert conn.execute('SELECT status FROM article_retries').fetchone()[0]=='resolved'
    assert conn.execute('SELECT count(*) FROM seen_articles').fetchone()[0]==1
    assert conn.execute('SELECT source_text FROM email_digest_items').fetchone()[0]==article['source_text']
    conn.close()


def test_editor_can_choose_fewer_stories_without_filler():
    client=response_client({'selected_ids':['2']})
    items=[{'id':1,'title':'Dog bite','summary_he':'תקרית מקומית','importance_score':12},
           {'id':2,'title':'NIK skontrolowała WOT','summary_he':'ביקורת לאומית על הצבא','importance_score':60}]
    assert select_editorial_items(client,items,8)==[items[1]]


@pytest.mark.parametrize('ids', [['unknown'],['1','1'],[True],['1','2','3']])
def test_editor_cannot_invent_ids_or_exceed_limit(ids):
    with pytest.raises(ValueError):
        select_editorial_items(response_client({'selected_ids':ids}), [{'id':1,'title':'title','summary_he':'עברית'}],2)
