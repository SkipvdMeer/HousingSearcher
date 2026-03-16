from pathlib import Path

from typer.testing import CliRunner

from local_housing_searcher.cli import app

runner = CliRunner()


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
database_path: {tmp_path / "data" / "housing.db"}
poll_interval_seconds: 5
notifications:
  desktop:
    enabled: false
  telegram:
    enabled: false
filters:
  cities: [Amsterdam]
  max_rent_eur: 2500
  min_sqm: 40
  furnishing: either
  include_keywords: [balcony]
  rental_types: [apartment]
sources:
  - id: mock-demo
    adapter: mock
    enabled: true
    seed: 2
    fixture_name: demo
        """
    )
    return config_path


def test_cli_poll_once_recent_matches_and_export(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    poll_result = runner.invoke(app, ["poll-once", "--config", str(config_path)])
    assert poll_result.exit_code == 0
    assert "mock-demo" in poll_result.stdout
    assert "new_matches=1" in poll_result.stdout

    recent_result = runner.invoke(app, ["recent-matches", "--config", str(config_path), "--limit", "10"])
    assert recent_result.exit_code == 0
    assert "Amsterdam" in recent_result.stdout

    export_path = tmp_path / "exports" / "matches.json"
    export_result = runner.invoke(
        app,
        ["export", str(export_path), "--format", "json", "--matches-only", "--config", str(config_path)],
    )
    assert export_result.exit_code == 0
    assert export_path.exists()


def test_cli_list_sources(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = runner.invoke(app, ["list-sources", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "mock-demo" in result.stdout
