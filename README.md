# Local Housing Searcher

Local Housing Searcher is a local-first rental monitoring tool for Dutch housing sites. You configure the sites you care about, define your own match criteria, and run the tool on your laptop or a small VPS. It polls listing pages, normalizes the results, deduplicates them, stores everything in SQLite, and sends notifications only when a newly discovered listing matches your filters.

This project is designed for personal monitoring, not for massive scraping. The focus is a small set of real adapters, predictable local operation, and easy self-hosting.

## What this tool does

- Polls supported rental sites on demand or on a schedule
- Normalizes listings into one internal format
- Filters listings by city, rent, area, furnishing, rental type, bedrooms, and keywords
- Scores each matching listing so you can separate strong matches from weak ones
- Deduplicates across repeated runs
- Stores results in a local SQLite database
- Sends desktop notifications and/or Telegram notifications
- Exports data to JSON or CSV
- Exposes a small optional FastAPI dashboard API

## What this tool does not do

- It does not auto-apply to listings
- It does not guarantee bypassing anti-bot protections
- It is not intended to crawl every Dutch housing platform
- It does not ship with a full web UI; the dashboard is a lightweight API only

## Supported adapters

Current adapters:

- `pararius`
- `funda`
- `huurwoningen`
- `directwonen`
- `vbt`
- `vanderlinden`
- `mock` for local testing

Notes:

- `mock` is the safest way to test your configuration and notification flow without touching real sites.
- `vbt` supports an extra `city` filter in the source config.
- `funda` has explicit challenge detection and supports advanced browser options such as `stealth`, `persistent_profile`, `profile_dir`, and `proxy`.

## How it works

The runtime flow is:

1. Load `config.yaml` and optionally a nearby `.env` file.
2. Initialize the SQLite database if it does not exist yet.
3. Build one adapter per enabled source.
4. Fetch listing pages with Playwright.
5. Parse listings into a shared schema.
6. Compute a dedupe fingerprint for each listing.
7. Apply filters and calculate a score.
8. Upsert the listing into SQLite.
9. Send notifications only for newly created listings that match your criteria.
10. Record source health so you can inspect what happened later.

Dry-run mode stops before persistence and notifications. It is the safest way to validate new configs.

## Project layout

Key files and directories:

- `src/local_housing_searcher/cli.py`: CLI entrypoint
- `src/local_housing_searcher/service.py`: main polling orchestration
- `src/local_housing_searcher/adapters/`: source-specific parsers
- `src/local_housing_searcher/db.py`: SQLite schema and exports
- `src/local_housing_searcher/filtering.py`: filters and scoring
- `src/local_housing_searcher/notifications.py`: desktop and Telegram notifications
- `config.example.yaml`: starter config for local use
- `config.vps.example.yaml`: starter config for VPS/container use
- `compose.yaml`: Docker Compose service
- `scripts/container.sh`: wrapper for common container operations
- `docs/architecture.md`: short implementation notes

## Requirements

- Python `3.12+`
- `pip`
- Chromium installed through Playwright
- macOS or Linux is the practical target for desktop notifications
- Docker and Docker Compose if you want the containerized setup

## Local installation

Create a virtual environment and install the project:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

That gives you the `housing-monitor` CLI command.

If you want the optional dashboard API as well:

```bash
pip install -e ".[dev,dashboard]"
```

## Quick start

Initialize a config and database:

```bash
housing-monitor init --config ./config.yaml
```

This command:

- creates `config.yaml` from `config.example.yaml` if the file does not already exist
- creates the SQLite database defined by `database_path`

Then edit the generated config for your own needs.

Run a safe first test:

```bash
housing-monitor poll-once --config ./config.yaml --dry-run
```

If that looks correct, run a real poll:

```bash
housing-monitor poll-once --config ./config.yaml
```

To run continuously:

```bash
housing-monitor run --config ./config.yaml
```

## Recommended first-run workflow

For a clean setup, use this order:

1. Run `housing-monitor init --config ./config.yaml`
2. Edit `config.yaml` and disable any sources you do not want
3. Enable `mock-demo` and run `poll-once --dry-run`
4. Verify your filters and notifications
5. Test individual real sources with `test-adapter`
6. Run `poll-once --dry-run` against real sources
7. Switch to real polling with `poll-once`
8. Start the scheduler with `run`

## Configuration

Start from `config.example.yaml`. The config is validated with Pydantic when the CLI starts.

### Important path behavior

- `database_path` is resolved relative to the config file location if it is not absolute.
- `debug_artifacts_dir` is also resolved relative to the config file location.
- `.env` autoload checks the config file directory first, then the current working directory.

### Top-level config keys

```yaml
database_path: ./data/housing.db
poll_interval_seconds: 300
timezone: Europe/Amsterdam
logging:
  level: INFO
notifications:
  ...
filters:
  ...
scoring:
  ...
sources:
  ...
```

Top-level fields:

- `database_path`: SQLite database file location
- `poll_interval_seconds`: scheduler interval used by `housing-monitor run`
- `timezone`: available in config for environment consistency; it is not used directly by the current scheduler logic
- `logging.level`: standard log level such as `DEBUG`, `INFO`, or `WARNING`
- `notifications`: desktop and Telegram notification settings
- `filters`: your hard match criteria
- `scoring`: thresholds used after a listing passes filters
- `sources`: one or more configured site adapters

### Filters

Example:

```yaml
filters:
  cities:
    - Amsterdam
  max_rent_eur: 2300
  min_sqm: 50
  furnishing: any
  include_keywords:
    - balcony
    - renovated
  exclude_keywords:
    - sharing
    - student
  rental_types:
    - apartment
    - house
  bedrooms_min: 1
  bedrooms_max: 3
```

Filter behavior:

- `cities`: allowed cities; values are normalized to lowercase internally
- `max_rent_eur`: reject listings above this value
- `min_sqm`: reject listings below this size
- `furnishing`: one of `any`, `furnished`, `unfurnished`, `either`
- `include_keywords`: if set, at least one of these must appear in title, description, or address
- `exclude_keywords`: reject listings containing any of these
- `rental_types`: allowed values are `apartment`, `house`, `studio`, `room`, `other`
- `bedrooms_min`: reject listings below this bedroom count
- `bedrooms_max`: reject listings above this bedroom count when the listing includes a bedroom count

Important detail: this tool uses hard filters first. If a listing fails one of those checks, it is not treated as a match regardless of score.

Current furnishing nuance: `furnished` and `unfurnished` apply a hard furnishing filter. `any` and `either` currently behave as "do not reject based on furnishing".

### Scoring

Example:

```yaml
scoring:
  high_priority_threshold: 85.0
  keyword_bonus: 8.0
```

Scoring behavior:

- Matching listings start from a base score and gain points for city, budget, area, furnishing, rental type, bedrooms, and keyword hits.
- Scores are capped at `100.0`.
- `high_priority_threshold` marks especially strong matches.
- `keyword_bonus` controls how much extra score each matched include-keyword adds, up to a cap.

High priority currently affects stored metadata and can help you prioritize notifications or exported results.

### Notifications

Example:

```yaml
notifications:
  desktop:
    enabled: false
  telegram:
    enabled: true
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
  telegram_targets:
    - enabled: true
      bot_token_env: TELEGRAM_BOT_TOKEN_2
      chat_id_env: TELEGRAM_CHAT_ID_2
```

Behavior:

- `desktop.enabled`: show a local desktop notification
- `telegram`: primary Telegram target
- `telegram_targets`: optional extra Telegram targets

All enabled Telegram targets receive the same notification.

Notifications are sent only when:

- the listing is new to the database
- the listing passes filters
- the run is not a dry run

If a listing is seen again later, it is updated in the database but not notified again as a new match.

### Telegram environment variables

Set them in your shell:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

Or use a local `.env` file:

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_BOT_TOKEN_2=...
TELEGRAM_CHAT_ID_2=...
```

### Sources

Each source entry defines one adapter instance.

Common fields:

- `id`: unique source identifier used by CLI commands
- `adapter`: adapter name such as `pararius` or `funda`
- `enabled`: whether the scheduler should poll this source
- `search_url`: page to fetch
- `max_listings`: maximum number of listings to keep from that source in one run
- `timeout_seconds`: fetch timeout
- `headless`: whether Playwright runs headless
- `wait_until`: Playwright load state, usually `domcontentloaded` or `networkidle`
- `extra_wait_ms`: extra wait after navigation before parsing
- `debug_artifacts_dir`: where screenshots and raw HTML should be written when `--debug` is enabled

Example:

```yaml
sources:
  - id: pararius-amsterdam
    adapter: pararius
    enabled: true
    search_url: https://www.pararius.com/apartments/amsterdam
    max_listings: 25

  - id: funda-amsterdam
    adapter: funda
    enabled: true
    search_url: https://www.funda.nl/zoeken/huur?selected_area=[%22amsterdam%22]
    max_listings: 25
    headless: false
    wait_until: networkidle
    extra_wait_ms: 5000
    debug_artifacts_dir: ./artifacts/funda
```

Adapter-specific fields currently used in this repository:

- `vbt`: `city`
- `mock`: `seed`, `fixture_name`

Advanced browser fields supported through permissive source config:

- `stealth`: enable extra browser fingerprint masking and a warm-up navigation path
- `persistent_profile`: reuse Chromium profile data across runs
- `profile_dir`: base directory for persistent browser profiles
- `proxy`: Playwright proxy object, for example:

```yaml
sources:
  - id: funda-amsterdam
    adapter: funda
    enabled: true
    search_url: https://www.funda.nl/zoeken/huur?selected_area=[%22amsterdam%22]
    stealth: true
    persistent_profile: true
    profile_dir: ~/.local_housing_searcher/browser_profiles
    proxy:
      server: http://proxy-host:3128
      username: your-user
      password: your-password
```

Use those advanced options carefully. They are useful for debugging and for reducing repeated verification loops on some sites, but they are not guaranteed to work indefinitely.

## Example local config

This is a practical starting point for a laptop setup:

```yaml
database_path: ./data/housing.db
poll_interval_seconds: 1800
timezone: Europe/Amsterdam

logging:
  level: INFO

notifications:
  desktop:
    enabled: true
  telegram:
    enabled: false
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
  telegram_targets: []

filters:
  cities:
    - Amsterdam
  max_rent_eur: 2300
  min_sqm: 50
  furnishing: any
  include_keywords:
    - balcony
  exclude_keywords:
    - student
    - sharing
  rental_types:
    - apartment
    - house
  bedrooms_min: 1

scoring:
  high_priority_threshold: 85.0
  keyword_bonus: 8.0

sources:
  - id: pararius-amsterdam
    adapter: pararius
    enabled: true
    search_url: https://www.pararius.com/apartments/amsterdam
    max_listings: 50

  - id: funda-amsterdam
    adapter: funda
    enabled: false
    search_url: https://www.funda.nl/zoeken/huur?selected_area=[%22amsterdam%22]
    max_listings: 50
    headless: false
    debug_artifacts_dir: ./artifacts/funda

  - id: mock-demo
    adapter: mock
    enabled: false
    seed: 3
    fixture_name: demo
```

## CLI reference

The CLI entrypoint is:

```bash
housing-monitor --help
```

Available commands:

- `init`
- `poll-once`
- `run`
- `test-adapter`
- `recent-matches`
- `export`
- `list-sources`

### `init`

Create a starter config and initialize the database:

```bash
housing-monitor init --config ./config.yaml
```

Use this when you are setting up a new environment.

### `poll-once`

Run one poll cycle and exit:

```bash
housing-monitor poll-once --config ./config.yaml
```

Useful variants:

```bash
housing-monitor poll-once --config ./config.yaml --dry-run
housing-monitor poll-once --config ./config.yaml --debug
housing-monitor poll-once --config ./config.yaml --source pararius-amsterdam
housing-monitor poll-once --config ./config.yaml --source pararius-amsterdam --source funda-amsterdam --dry-run
```

Use `--dry-run` when you want to:

- validate parsing
- validate filters
- avoid database writes
- avoid notifications

Use `--debug` when you want adapters with `debug_artifacts_dir` configured to write screenshots and HTML captures.

### `run`

Run the scheduler continuously:

```bash
housing-monitor run --config ./config.yaml
```

Behavior:

- runs one poll cycle
- waits `poll_interval_seconds`
- repeats until interrupted
- stops cleanly on `SIGINT` or `SIGTERM`

You can combine it with:

```bash
housing-monitor run --config ./config.yaml --dry-run
housing-monitor run --config ./config.yaml --debug
```

### `test-adapter`

Test one configured source directly:

```bash
housing-monitor test-adapter pararius-amsterdam --config ./config.yaml
```

This is the best command when:

- only one source is failing
- you want to inspect a real parser run
- you want to see the first few parsed listings quickly

With debug artifacts:

```bash
housing-monitor test-adapter funda-amsterdam --config ./config.yaml --debug
```

### `recent-matches`

Show recent matching listings already stored in SQLite:

```bash
housing-monitor recent-matches --config ./config.yaml --limit 20
```

This reads from the database. It does not trigger a new scrape.

### `export`

Export listings from SQLite:

```bash
housing-monitor export ./exports/listings.json --format json --config ./config.yaml
housing-monitor export ./exports/listings.csv --format csv --config ./config.yaml
housing-monitor export ./exports/matches.json --format json --matches-only --config ./config.yaml
```

Exported fields include:

- listing identifiers
- title and city
- price, area, and bedrooms
- furnishing and rental type
- URL and canonical URL
- match score and priority flags
- first seen / last seen timestamps
- notification timestamp

### `list-sources`

Show configured sources and latest recorded health status:

```bash
housing-monitor list-sources --config ./config.yaml
```

This is useful for checking:

- which sources are enabled
- whether they have ever run
- how many listings were found in the latest run
- the latest health message

## Understanding the database

The default database is SQLite.

Tables include:

- `listings`
- `listing_identities`
- `source_runs`

Listings are considered the same when any of these identities match:

- `source + external_id`
- canonical URL
- normalized fingerprint derived from listing content

That means repeated scheduler runs update existing listings instead of inserting duplicates.

## Debugging and blocked sources

Some sites occasionally return verification or challenge pages. This project does not promise full bypass behavior. The intended workflow is to make those failures visible and debuggable.

Recommended debugging setup:

```yaml
sources:
  - id: funda-amsterdam
    adapter: funda
    enabled: true
    search_url: https://www.funda.nl/zoeken/huur?selected_area=[%22amsterdam%22]
    headless: false
    debug_artifacts_dir: ./artifacts/funda
```

Then run:

```bash
housing-monitor test-adapter funda-amsterdam --config ./config.yaml --debug
```

When debug artifacts are enabled and the adapter is run with `--debug`, the fetcher can write:

- a full-page screenshot
- the raw HTML that was returned

Those files are the first thing to inspect when:

- a source suddenly returns zero listings
- a parser starts failing
- a site is serving a CAPTCHA or interstitial page

## Desktop notifications

Desktop notification behavior depends on the platform:

- macOS: uses `osascript`
- Linux: uses `notify-send` if available

Inside Docker, desktop notifications are usually not useful. Telegram is the better notification channel there.

## Docker

Build the image:

```bash
docker build -t local-housing-searcher .
```

Run one dry-run poll:

```bash
docker run --rm -it \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -v "$(pwd)/data:/app/data" \
  local-housing-searcher poll-once --config /app/config.yaml --dry-run
```

Run the scheduler:

```bash
docker run --rm -it \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/exports:/app/exports" \
  -v "$(pwd)/artifacts:/app/artifacts" \
  --env TELEGRAM_BOT_TOKEN \
  --env TELEGRAM_CHAT_ID \
  local-housing-searcher run --config /app/config.yaml
```

Container behavior worth knowing:

- the image installs Chromium with Playwright
- `xvfb` is included so headed browser runs can still work on headless hosts
- the entrypoint auto-adds `--config` from `HOUSING_MONITOR_CONFIG` when missing
- `/app/data`, `/app/exports`, and `/app/artifacts` are created automatically

## Docker Compose and VPS workflow

This repository includes `compose.yaml` and `scripts/container.sh` for a small VPS deployment.

Typical setup:

```bash
cp config.vps.example.yaml config.yaml
$EDITOR config.yaml
cp .env.example .env
$EDITOR .env
./scripts/container.sh deploy
```

Useful wrapper commands:

```bash
./scripts/container.sh deploy
./scripts/container.sh start
./scripts/container.sh stop
./scripts/container.sh restart
./scripts/container.sh status
./scripts/container.sh logs
./scripts/container.sh poll-once
./scripts/container.sh shell
./scripts/container.sh down
```

The compose service mounts:

- `./config.yaml` to `/app/config.yaml`
- `./data` to `/app/data`
- `./exports` to `/app/exports`
- `./artifacts` to `/app/artifacts`

This keeps your database, exports, and debug captures persistent across container rebuilds.

## Optional dashboard API

Install the dashboard extra:

```bash
pip install -e ".[dashboard]"
```

Run the API:

```bash
uvicorn "local_housing_searcher.dashboard:create_app('./config.yaml')" --factory --reload
```

Endpoints:

- `GET /health`
- `GET /listings`
- `GET /sources`

This is intentionally lightweight. It is a small API over the SQLite data, not a full interactive frontend.

## Typical usage patterns

### Pattern 1: Safe local development

```bash
housing-monitor init --config ./config.yaml
housing-monitor poll-once --config ./config.yaml --source mock-demo --dry-run
housing-monitor poll-once --config ./config.yaml --source mock-demo
housing-monitor recent-matches --config ./config.yaml
```

### Pattern 2: Testing one broken site

```bash
housing-monitor test-adapter funda-amsterdam --config ./config.yaml --debug
housing-monitor list-sources --config ./config.yaml
```

### Pattern 3: Daily laptop use

```bash
housing-monitor poll-once --config ./config.yaml
housing-monitor recent-matches --config ./config.yaml --limit 10
housing-monitor export ./exports/matches.csv --format csv --matches-only --config ./config.yaml
```

### Pattern 4: Long-running VPS

```bash
./scripts/container.sh deploy
./scripts/container.sh logs
./scripts/container.sh status
```

## Troubleshooting

### `poll-once` returns zero listings

Check:

- whether the source is enabled
- whether the `search_url` still works in a browser
- whether the site changed its HTML
- whether you hit a CAPTCHA or verification page
- whether your filters are too strict

Run:

```bash
housing-monitor test-adapter SOURCE_ID --config ./config.yaml --debug
```

### Notifications are not arriving

Check:

- whether you used `--dry-run`
- whether the listing is actually new
- whether the listing passed filters
- whether Telegram environment variables are set
- whether desktop notifications are supported on your platform

### Docker container says config file is missing

Make sure one of these is true:

- `./config.yaml` is mounted to `/app/config.yaml`
- `HOUSING_MONITOR_CONFIG` points to the mounted config path

### Funda or another source hits verification pages

Try:

- `headless: false`
- `--debug`
- `debug_artifacts_dir`
- carefully enabling `stealth` and `persistent_profile`

If the site keeps challenging the session, inspect the saved screenshot and HTML before changing parser code.

## Development

Install dev dependencies and run tests:

```bash
pip install -e ".[dev]"
pytest
```

The test suite covers config loading, CLI behavior, notifications, scheduling, dedupe/filtering logic, and several adapter parsers.

Short architecture notes live in `docs/architecture.md`.

## Summary

If you only want the shortest path to a working setup:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
housing-monitor init --config ./config.yaml
$EDITOR config.yaml
housing-monitor poll-once --config ./config.yaml --dry-run
housing-monitor run --config ./config.yaml
```

That gives you a local, inspectable housing monitor with SQLite persistence and optional notifications.
