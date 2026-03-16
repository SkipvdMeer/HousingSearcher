# Local Housing Searcher

Local-first rental monitoring for a small set of Dutch rental websites. It is designed for personal use on a laptop or self-hosted Docker container, with correctness and maintainability prioritized over scraping breadth.

## Features

- Python 3.12+ CLI-first workflow
- `Playwright` adapters with a small adapter abstraction
- `SQLite` persistence for listings, dedupe identities, and adapter run health
- Typed YAML config via `Pydantic`
- Deduplication by canonical URL, `source+external_id`, and fuzzy fingerprint
- Filtering plus match scoring
- Desktop notifications and Telegram notifications
- Dry-run mode and debug mode
- Export to CSV or JSON
- Optional lightweight `FastAPI` dashboard

## Current adapters

- `mock`: deterministic local development adapter
- `directwonen`: real adapter for `directwonen.nl` Amsterdam listing pages
- `pararius`: real adapter for `pararius.com` search result pages
- `funda`: real adapter with explicit challenge detection for `funda.nl`
- `huurwoningen`: real adapter with explicit challenge detection for `huurwoningen.nl`
- `vbt`: real adapter for `vbtverhuurmakelaars.nl` public listings, filtered to Amsterdam via config
- `vanderlinden`: real adapter for `vanderlinden.nl`

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
housing-monitor init --config ./config.yaml
housing-monitor poll-once --config ./config.yaml --dry-run
housing-monitor run --config ./config.yaml
```

Then edit `./config.yaml` for your own filters and sources.

## Docker

```bash
docker build -t local-housing-searcher .
docker run --rm -it \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -v "$(pwd)/data:/app/data" \
  local-housing-searcher poll-once --config /app/config.yaml --dry-run
```

For long-running use:

```bash
docker run --rm -it \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -v "$(pwd)/data:/app/data" \
  --env TELEGRAM_BOT_TOKEN \
  --env TELEGRAM_CHAT_ID \
  local-housing-searcher run --config /app/config.yaml
```

Desktop notifications are generally not useful from inside Docker, so Telegram is the better notification channel there.

The container includes `xvfb`, so adapters configured with `headless: false` can still run on a VPS without a physical display.

If you use Telegram notifications, export the environment variables first:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

Or put them in a local `.env` file next to `config.yaml` or in the project root:

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

`housing-monitor` now loads that `.env` file automatically.

## VPS deployment

For a long-running VPS setup, keep the scheduler inside the container and set `poll_interval_seconds: 3600` in [config.yaml](/Users/skipvandermeer/Local Housing Searcher/config.yaml). A VPS-oriented starter config is available at [config.vps.example.yaml](/Users/skipvandermeer/Local Housing Searcher/config.vps.example.yaml).

The repo now includes [compose.yaml](/Users/skipvandermeer/Local Housing Searcher/compose.yaml) and [scripts/container.sh](/Users/skipvandermeer/Local Housing Searcher/scripts/container.sh), so deployment is just:

```bash
cp config.vps.example.yaml config.yaml
$EDITOR config.yaml
cp .env.example .env
$EDITOR .env
./scripts/container.sh deploy
./scripts/container.sh logs
./scripts/container.sh status
```

The wrapper script uses `docker compose` under the hood and supports:

```bash
./scripts/container.sh deploy
./scripts/container.sh start
./scripts/container.sh stop
./scripts/container.sh restart
./scripts/container.sh status
./scripts/container.sh logs
./scripts/container.sh poll-once
./scripts/container.sh down
```

The compose service mounts these paths from the VPS filesystem:

- `./config.yaml -> /app/config.yaml`
- `./data -> /app/data`
- `./exports -> /app/exports`
- `./artifacts -> /app/artifacts`

That keeps the SQLite database, exports, and debug artifacts persistent across container rebuilds and restarts.

For multiple Telegram destinations, keep `notifications.telegram` for one target and add `notifications.telegram_targets` for any extras:

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

Each target can use a different bot, a different chat, or both.

## CLI commands

```bash
housing-monitor init --config ./config.yaml
housing-monitor list-sources --config ./config.yaml
housing-monitor test-adapter pararius-amsterdam --config ./config.yaml
housing-monitor poll-once --config ./config.yaml
housing-monitor poll-once --config ./config.yaml --source pararius-amsterdam --dry-run --debug
housing-monitor run --config ./config.yaml
housing-monitor recent-matches --config ./config.yaml --limit 20
housing-monitor export ./exports/matches.json --format json --matches-only --config ./config.yaml
housing-monitor export ./exports/listings.csv --format csv --config ./config.yaml
```

## Config

Start from [config.example.yaml](/Users/skipvandermeer/Local Housing Searcher/config.example.yaml). The most important sections are:

- `sources`: site adapters to poll
- `filters`: cities, rent, area, furnishing, keywords, rental type, bedrooms
- `notifications`: desktop and Telegram settings
- `scoring`: high-priority threshold
- `poll_interval_seconds`: scheduler interval

The default example config is Amsterdam-only and includes `Pararius`, `Funda`, `Huurwoningen`, and `Van der Linden`.

For sites that return verification pages, prefer manual inspection over anti-bot evasion. A source can be run in headed mode and store debug artifacts for review:

```yaml
sources:
  - id: funda-amsterdam
    adapter: funda
    search_url: https://www.funda.nl/huur/amsterdam/
    headless: false
    debug_artifacts_dir: ./artifacts/funda
```

Then run:

```bash
housing-monitor test-adapter funda-amsterdam --config ./config.yaml --debug
```

When debug mode is enabled, the Playwright fetch path writes a screenshot and raw HTML to `debug_artifacts_dir`, and blocked runs include those paths in adapter health details.

## Data model

`SQLite` stores:

- canonical listings
- dedupe identities
- source run health and timestamps

A listing is considered the same when any of these identities match:

- canonical URL
- `source_id + external_id`
- fuzzy fingerprint derived from normalized title, address, city, price bucket, and area bucket

## Optional dashboard

Install the dashboard extra and run a local API:

```bash
pip install -e ".[dashboard]"
uvicorn "local_housing_searcher.dashboard:create_app('./config.yaml')" --factory --reload
```

Endpoints:

- `GET /health`
- `GET /listings`
- `GET /sources`

## Development

```bash
pytest
```

More implementation notes are in [docs/architecture.md](/Users/skipvandermeer/Local Housing Searcher/docs/architecture.md).
