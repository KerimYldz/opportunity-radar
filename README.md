# Opportunity Radar

Finds public posts where people ask for help with small digital tasks (Excel, PDFs, data cleanup,
simple websites, remote computer help, small scripts), filters out offers, job ads and scams,
and sends promising leads to **your own** Telegram chat.

It is a research tool. It never contacts posters, never replies, never applies, never follows
links inside posts, and never downloads attachments.

## Status

| Phase | Item | State |
|---|---|---|
| 1 | Reddit public Atom feeds (r/forhire, r/slavelabour, r/DoneDirtCheap, search, Philly/NJ subs) | working |
| 1 | Rule-based filtering (intent, category, exclusions, complexity, location, age) | working |
| 1 | Scam-risk scoring with evidence and risk bands | working |
| 1 | Dedup: canonical URL, exact fingerprint, near-duplicate similarity (reposts) | working |
| 1 | SQLite store, Telegram alerts, retry-on-failure, cold-start protection | working |
| 1 | GitHub Actions every 15 min, DB persisted via Actions cache | ready (needs your repo + secrets) |
| 1 | Manual import CLI (Facebook / Nextdoor / anything you can't legally scrape) | working (CLI) |
| 2 | AI analysis (summary, structured JSON, schema validation) | not yet; `analysis_mode` = `rules` |
| 3 | Streamlit dashboard, more sources | not yet |

### Sources

* **Reddit public Atom feeds** — the only automated source. No login, no JSON API, no HTML
  scraping. Subreddits are batched into one request, and the client honours Reddit's
  `X-Ratelimit-*` headers. Anonymous feed access is limited to roughly one request per ~10 s, so a
  run makes at most 12 requests. For anything heavier or commercial, register an app and move to
  the official OAuth API (Reddit's Data API terms apply).
* **Craigslist — disabled.** Craigslist removed RSS in 2024 and answers automated searches with
  HTTP 403. There is no permitted programmatic access, so there is no connector.
* **Facebook / Nextdoor — manual import only** (`radar import`). No scrapers, no logins.

## Quick start (local)

```bash
cd opportunity-radar
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill in the two Telegram values (see below)
.venv/bin/python -m pytest -q
./radar run --dry-run          # collects and stores, sends nothing
./radar list                   # top leads that passed Stage 1
```

`./radar` is a small wrapper that runs `python -m opportunity_radar` with `src/` on the path.
(On macOS with Python 3.13, an editable `pip install -e .` can silently stop working because the
`.pth` file gets the "hidden" flag; the wrapper avoids that.)

### Telegram setup

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Put it in `.env` as `TELEGRAM_BOT_TOKEN=...` (never in code, never in chat logs).
3. Send `/start` to your new bot, then run `./radar chat-id` and copy your id into
   `TELEGRAM_CHAT_ID=...`.
4. `./radar test-notify` — you should receive a test message.

### Commands

| Command | What it does |
|---|---|
| `./radar run [--dry-run]` | Collect → filter → score → store → alert |
| `./radar test-notify` | Send a test Telegram message |
| `./radar chat-id` | Show chat ids that messaged your bot |
| `./radar import --platform facebook --url URL --text "..." [--published 2026-11-02T10:00] [--notify]` | Analyze a post you copied manually |
| `./radar list [--all]` | Show leads by priority |
| `./radar status LEAD_ID reviewed` | Manual tracking: new, reviewed, interesting, contacted, rejected, archived |
| `./radar stats` | Counts |

## Cloud scheduling (GitHub Actions)

1. Create a GitHub repo and push this folder. `.env` and `data/*.db` are git-ignored.
2. Repo → Settings → Secrets and variables → Actions → add secrets
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Actions tab → **collect** → *Run workflow* → choose `test-notify`, then `run`.
4. After that it runs every 15 minutes. Your Mac can be off.

**Persistence.** Runners are ephemeral. The SQLite file is restored from the newest
`radar-db-*` Actions cache entry at the start of each run and saved as a new entry at the end
(the DB is never committed). A `concurrency` group prevents two runs from overlapping. Cache
entries are evicted after 7 days without use or when the repo passes 10 GB; with runs every 15
minutes neither should happen. If the cache is lost anyway, **cold-start protection** applies:
on an empty DB at most `cold_start_max` (default 3) alerts are sent and everything else is marked
`suppressed`, so you are never flooded with old leads.

**Reddit from cloud IPs.** Reddit sometimes blocks data-centre IP ranges. If the Actions log
shows `HTTP 403` from reddit.com, the collector stops politely for that run. The real fix is the
official OAuth API (free tier for non-commercial use, needs an approved app).

### Costs

| Item | Cost |
|---|---|
| GitHub Actions, **public** repo | free (standard runners are unlimited for public repos) |
| GitHub Actions, private repo | 2,000 free min/month. A run takes ~2–4 min because of Reddit's rate limit, so every 15 min ≈ 8,000+ min/month — **over the free tier** (~$0.008/min beyond). Use a public repo, or change the cron to hourly. |
| Telegram Bot API | free |
| Reddit public feeds | free |
| AI API (Phase 2, optional) | not used yet; Claude Code subscriptions do **not** include API credits |

Public repo notes: code and workflow logs are public (they contain only public post titles and
counts — never secrets, GitHub masks them). The DB stays in the cache, which outsiders cannot
download. DB artifacts are off by default (`UPLOAD_DB_ARTIFACT` repo variable) because public-repo
artifacts are downloadable by any signed-in user. Run manual imports of Facebook/Nextdoor posts
locally only.

## How a post is judged

**Stage 1 (rules, always on)**

* *Intent*: `[Hiring]` / `[Task]` → request; `[For Hire]` / `[Offer]` / "hire me" → offer (rejected).
* *Category*: a specific keyword (Excel, PDF, data entry, website build/fix, …) must appear in
  the title or in a sentence that asks for something — incidental mentions do not count.
* *Hard exclusions*: full-time jobs, unpaid/volunteer, internships, MLM/affiliate/referral,
  paid surveys, crypto promos, AI-training recruitment, suspicious requests (fake documents,
  account hacking, license cracking / reverse engineering, homework-for-hire).
* *Location*: in-person work is allowed only around South Jersey / Philadelphia.
* *Age*: older than 7 days is stored but never "new"; alerts need ≤ 48 h by default. Reddit's
  publish time comes from the feed and is marked as source-verified.
* *Outside task subreddits* a post must show hiring intent ("willing to pay", "know someone who
  can…", "need someone to…"), otherwise suitability is capped at 60 (it is free-advice territory).

**Scam risk** (0–100) adds weighted signals, each with a text snippet as evidence: upfront fees,
fake-check language, gift cards, crypto payment, bank details, ID documents, buy-equipment-and-get-
reimbursed, money movement, off-platform chat, earnings hype, recruitment wording, link shorteners,
pay far too high for trivial work, repeated identical ads. A single weak signal is capped at 15.
Bands: 0–25 low apparent risk · 26–50 some concerns · 51–75 high concern · 76–100 very high
concern. **A low score never means the poster is verified.** Very short posts are flagged
"uncertain".

**Priority** = suitability 30% + recency 25% + economics 20% + scam safety 15% + remote fit 10%
(configurable in `config/settings.yaml`; must sum to 1). Unknown publish dates get a low recency
score. Price/time estimates are per-category rule-of-thumb figures that include communication,
QA, revisions and delivery, and are always labelled as estimates. *Advertised budget* is only ever
copied from the post text.

**Alert gate** (defaults): passed Stage 1, not a duplicate/repost, suitability ≥ 75,
scam ≤ 40 (unless `include_high_risk: true`), published ≤ 48 h ago. A lead is marked `sent` only
after Telegram confirms delivery; failures are retried next run.

## Security

* Secrets only via `.env` (local) or Actions secrets. The Telegram token is redacted from error
  messages; urllib3 debug logging is off.
* Post text is untrusted. It is HTML-escaped before going to Telegram, XML is parsed with
  `defusedxml`, and links inside posts are never fetched.
* Phase 2 AI analysis will send only post text (no customer documents), wrap it as data with
  instructions to ignore embedded commands, and validate the JSON against a schema.

## Layout

```
config/settings.yaml          thresholds, weights, search terms, sources
src/opportunity_radar/
  sources/reddit_rss.py       Reddit Atom collector
  http.py                     rate limiting, retry/backoff, request budget
  filters.py                  Stage 1 rules and estimates
  scam.py                     scam-risk signals
  dedup.py                    canonical URLs, fingerprints, similarity
  scoring.py                  recency, economics, priority
  storage.py                  SQLite
  notifier.py                 Telegram
  pipeline.py                 orchestration and alert gate
  cli.py                      commands
tests/                        pytest, MOCK data only
.github/workflows/            collect (every 15 min) and tests
```
