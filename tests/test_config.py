from pathlib import Path

from local_housing_searcher.config import load_config


def test_load_config_resolves_relative_database_path(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
database_path: ./data/test.db
filters:
  cities: [Amsterdam]
sources:
  - id: mock
    adapter: mock
        """
    )

    config = load_config(config_file)

    assert config.database_path == (tmp_path / "data" / "test.db").resolve()
    assert config.filters.cities == ["amsterdam"]


def test_load_config_supports_multiple_telegram_targets(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
database_path: ./data/test.db
notifications:
  telegram:
    enabled: true
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
  telegram_targets:
    - enabled: true
      bot_token_env: TELEGRAM_BOT_TOKEN_2
      chat_id_env: TELEGRAM_CHAT_ID_2
sources:
  - id: mock
    adapter: mock
        """
    )

    config = load_config(config_file)

    assert len(config.notifications.enabled_telegram_targets()) == 2


def test_load_config_resolves_relative_debug_artifacts_dir(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
database_path: ./data/test.db
sources:
  - id: funda
    adapter: funda
    debug_artifacts_dir: ./artifacts/funda
        """
    )

    config = load_config(config_file)

    assert config.sources[0].debug_artifacts_dir == (tmp_path / "artifacts" / "funda").resolve()
