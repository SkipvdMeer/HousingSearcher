from __future__ import annotations

from pathlib import Path

import typer

from local_housing_searcher.adapters import AdapterContext, build_adapter
from local_housing_searcher.config import load_config, write_example_config
from local_housing_searcher.db import Database
from local_housing_searcher.env_utils import autoload_dotenv
from local_housing_searcher.logging_utils import configure_logging
from local_housing_searcher.notifications import NotificationManager
from local_housing_searcher.scheduler import run_scheduler
from local_housing_searcher.service import PollService

app = typer.Typer(help="Local-first rental monitoring CLI")


def _load_runtime(config_path: Path, debug: bool):
    autoload_dotenv(config_path)
    config = load_config(config_path)
    configure_logging(config.logging.level, debug=debug)
    database = Database(config.database_path)
    database.initialize()
    notifications = NotificationManager(config.notifications)
    return config, database, notifications


@app.command()
def init(
    config_path: Path = typer.Option(Path("./config.yaml"), "--config", help="Path to create config file"),
) -> None:
    created = write_example_config(config_path)
    config = load_config(created)
    database = Database(config.database_path)
    database.initialize()
    typer.echo(f"Config ready at {created}")
    typer.echo(f"Database ready at {config.database_path}")


@app.command("poll-once")
def poll_once(
    config_path: Path = typer.Option(Path("./config.yaml"), "--config"),
    source_ids: list[str] = typer.Option(None, "--source", help="Specific source id to run"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    config, database, notifications = _load_runtime(config_path, debug)
    service = PollService(config, database, notifications, debug=debug, dry_run=dry_run)
    summary = service.poll_once(source_ids=source_ids or None)
    for item in summary.source_summaries:
        typer.echo(
            f"{item.source_id} | ok={item.ok} | fetched={item.fetched} | new_matches={item.new_matches} | {item.message}"
        )


@app.command()
def run(
    config_path: Path = typer.Option(Path("./config.yaml"), "--config"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    config, database, notifications = _load_runtime(config_path, debug)
    service = PollService(config, database, notifications, debug=debug, dry_run=dry_run)
    run_scheduler(service, config.poll_interval_seconds)


@app.command("test-adapter")
def test_adapter(
    source_id: str = typer.Argument(..., help="Configured source id"),
    config_path: Path = typer.Option(Path("./config.yaml"), "--config"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    config, database, _notifications = _load_runtime(config_path, debug)
    source = config.get_source(source_id)
    adapter = build_adapter(AdapterContext(source=source, filters=config.filters, database=database, debug=debug))
    result = adapter.fetch()
    database.save_source_run(
        source_id=result.source_id,
        ok=result.health.ok,
        message=result.health.message,
        duration_ms=result.duration_ms,
        listings_found=len(result.listings),
    )
    typer.echo(f"{result.source_id} | ok={result.health.ok} | fetched={len(result.listings)} | {result.health.message}")
    if debug and result.health.details:
        typer.echo(f"details: {result.health.details}")
    for listing in result.listings[:5]:
        typer.echo(f"- {listing.title} | {listing.city} | {listing.price_eur} EUR | {listing.url}")


@app.command("recent-matches")
def recent_matches(
    config_path: Path = typer.Option(Path("./config.yaml"), "--config"),
    limit: int = typer.Option(20, "--limit"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    _config, database, _notifications = _load_runtime(config_path, debug)
    records = database.recent_matches(limit=limit)
    for record in records:
        listing = record.listing
        typer.echo(
            f"{record.id} | {listing.source} | {listing.city} | {listing.price_eur} EUR | "
            f"{listing.area_sqm or 'n/a'} sqm | score={record.match_score or 0:.1f} | {listing.url}"
        )


@app.command()
def export(
    destination: Path = typer.Argument(..., help="Output file path"),
    format: str = typer.Option("json", "--format", case_sensitive=False),
    matches_only: bool = typer.Option(False, "--matches-only"),
    config_path: Path = typer.Option(Path("./config.yaml"), "--config"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    _config, database, _notifications = _load_runtime(config_path, debug)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if format.lower() == "json":
        path = database.export_json(destination, matches_only=matches_only)
    elif format.lower() == "csv":
        path = database.export_csv(destination, matches_only=matches_only)
    else:
        raise typer.BadParameter("format must be 'json' or 'csv'")
    typer.echo(f"Exported to {path}")


@app.command("list-sources")
def list_sources(
    config_path: Path = typer.Option(Path("./config.yaml"), "--config"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    config, database, _notifications = _load_runtime(config_path, debug)
    latest_status = {item["source_id"]: item for item in database.latest_source_statuses()}
    for source in config.sources:
        status = latest_status.get(source.id)
        if status:
            typer.echo(
                f"{source.id} | adapter={source.adapter} | enabled={source.enabled} | "
                f"ok={bool(status['ok'])} | found={status['listings_found']} | {status['message']}"
            )
        else:
            typer.echo(f"{source.id} | adapter={source.adapter} | enabled={source.enabled} | never-run")


if __name__ == "__main__":
    app()
