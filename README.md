# Cents & Sheets autopost

Scheduled jobs for the Cents & Sheets Instagram and Facebook Page:

- `post-reel.yml` posts the day's reel from `content/calendar.json` once a day.
- `comments.yml` replies to "BUDGET" comments every 10 minutes.

Secrets (Page token and IDs) live in the repository's Actions secrets, never in the code.
