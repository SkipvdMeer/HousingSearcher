import os
from pathlib import Path

from local_housing_searcher.env_utils import autoload_dotenv, load_dotenv


def test_load_dotenv_reads_simple_key_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
# comment
TELEGRAM_BOT_TOKEN=abc123
export TELEGRAM_CHAT_ID="987654"
INVALID_LINE
        """
    )

    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)

    loaded = load_dotenv(env_file)

    assert loaded == env_file.resolve()
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "abc123"
    assert os.environ["TELEGRAM_CHAT_ID"] == "987654"


def test_autoload_dotenv_uses_config_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "workspace"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"
    config_file.write_text("sources:\n  - id: mock\n    adapter: mock\n")
    env_file = config_dir / ".env"
    env_file.write_text("TELEGRAM_CHAT_ID=111222333\n")

    os.environ.pop("TELEGRAM_CHAT_ID", None)

    loaded = autoload_dotenv(config_file)

    assert loaded == env_file.resolve()
    assert os.environ["TELEGRAM_CHAT_ID"] == "111222333"
