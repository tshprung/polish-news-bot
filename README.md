# Polish news in Hebrew

The bot collects Polish RSS reporting, filters for relevance to residents of Poland,
and translates accepted stories into short Hebrew summaries for Telegram.
National developments and significant regional health, education, transport,
housing and public-safety news are eligible. Sports, lifestyle, routine minor
incidents and opinion polls remain excluded.

## Delivery and repeat prevention

- Delivery is daily-only by default, while ingestion continues on its existing
  schedule. Set `NEWS_TELEGRAM_ALERTS_ENABLED=1` only to opt into separate immediate
  alerts; these use `NEWS_TELEGRAM_MIN_SCORE` (default 40). Routine local crime
  receives no city bonus. Optional immediate alerts are separate from the digest's
  daily story budget.
- The daily brief uses up to `NEWS_DIGEST_MAX_ITEMS` existing Hebrew summaries
  (default 8, maximum 10), each with its own source. Concrete decisions, reports,
  emergency warnings and other observable developments rank above commentary
  and political reactions. Pending stories are re-ranked at delivery time.
  Category breadth is a small preference, not a hard limit on different events.
- A Hebrew copy editor checks only the stories about to be sent (one batch call
  for the brief, or one call per immediate alert). It checks sentence subjects,
  grammar, names and institutional terminology against the supplied title and
  draft. Unknown names can retain their original Latin spelling. Numeric changes,
  missing stories and invalid edits are rejected, leaving stories available for
  retry. `NEWS_HEBREW_EDIT_MODEL` defaults to the summary model. This adds a model
  call and is a quality safeguard, not independent factual verification.
- Only one completed daily brief can be sent per Warsaw calendar day, even if
  cron invokes it twice. Partial-send retries count stories already delivered
  against that day's configured limit. A long brief may still span several
  consecutive Telegram messages because of the platform's length limit.
- Only successfully delivered entries are marked sent. Omitted entries remain
  pending for up to 48 hours after ingestion; older entries expire separately
  and are never labelled delivered. Successful message chunks are committed
  before sending the next chunk.
- Shared story memory covers queued stories, alerts and daily digests from the
  preceding seven days. The newest 2,000 records are searched locally; up to 40
  candidates ranked by vocabulary overlap are compared with the incoming summary.
  The model rejects repeated facts and preserves material updates or uncertain
  matches. This is bounded, probabilistic duplicate detection, not a guarantee.
- `NEWS_NOVELTY_ENABLED=1` enables this comparison by default. It adds one model
  call per accepted article when history exists. `NEWS_NOVELTY_MODEL` defaults to
  the classifier model. Set `NEWS_NOVELTY_ENABLED=0` to disable semantic checks;
  identical-copy checks still run. API or parsing failures retain the article.
- Existing database history is reused. No database reset is needed. As with any
  remote send, a crash after Telegram accepts a message but before the database
  commit can cause a retry; Telegram sending and SQLite cannot be atomic.

## Setup and scheduling

Run `setup.sh <repository-ssh-url>`, configure `/opt/polish_news/.env`, and make
`run.sh` executable. Both ingestion and the daily brief need cron entries:

```cron
CRON_TZ=Europe/Warsaw
0 * * * * /opt/polish_news/run.sh
0 20 * * * /opt/polish_news/run.sh send-telegram-digest
```

This example sends the brief at 20:00 Warsaw time. Verify that your cron daemon
supports `CRON_TZ`, or configure the scheduler's timezone explicitly. The wrapper's
`TZ` setting controls application time, not a cron daemon that ignores `CRON_TZ`.
The shared lock prevents ingestion and digest jobs from updating state together.
Updating the repository does not install or change the VM's crontab.

Before merging onto `main`, review the PR and back up `seen.db` using SQLite's
backup facility. The deployment workflow installs dependencies and deploys only
after the tests pass. The new status column is added automatically on first run.

## Tests

```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use temporary databases and mocked model/Telegram calls. They do not send
messages or measure live-model duplicate accuracy. New regression cases cover
queued/sent history, material-update handling, delivery failures, chunking,
expiry, category breadth and national-policy alert scores.
