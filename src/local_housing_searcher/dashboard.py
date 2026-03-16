from __future__ import annotations

from fastapi import FastAPI

from local_housing_searcher.config import load_config
from local_housing_searcher.db import Database


def create_app(config_path: str) -> FastAPI:
    config = load_config(config_path)
    database = Database(config.database_path)
    database.initialize()

    app = FastAPI(title="Local Housing Searcher")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/listings")
    def listings(limit: int = 50):
        return database.recent_dashboard_rows(limit=limit)

    @app.get("/sources")
    def sources():
        return database.latest_source_statuses()

    return app
