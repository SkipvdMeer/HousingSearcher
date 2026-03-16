# Architecture

## Modules

- `config.py`: YAML loading and typed runtime config
- `models.py`: domain and persistence-facing Pydantic models
- `db.py`: SQLite schema and CRUD operations
- `adapters/`: fetchers for each source
- `filtering.py`: hard filters and match scoring
- `dedupe.py`: canonical fingerprint generation
- `notifications.py`: desktop and Telegram notifiers
- `service.py`: single poll orchestration
- `scheduler.py`: polling loop
- `cli.py`: Typer command surface
- `dashboard.py`: optional local API

## Poll flow

1. Load config and initialize SQLite.
2. Build an adapter for each enabled source.
3. Fetch listings from the source.
4. Normalize listing records and compute a fingerprint.
5. Apply filtering and match scoring.
6. Deduplicate against stored identities.
7. Persist new or updated listings.
8. Notify only for newly created matching listings.
9. Record adapter health for later inspection.

## Adapter design

Each adapter returns:

- normalized listings
- a health object
- fetch duration

Adapters stay responsible for source-specific DOM parsing only. Persistence, dedupe, filtering, and notifications live outside adapter code.

## Dry-run semantics

Dry-run mode fetches and evaluates listings but does not write new listings or send notifications. It logs what would have triggered.
