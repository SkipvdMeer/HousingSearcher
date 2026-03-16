from __future__ import annotations

import os
from pathlib import Path


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if value and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


def load_dotenv(env_path: str | Path, *, override: bool = False) -> Path | None:
    path = Path(env_path).expanduser().resolve()
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
    return path


def autoload_dotenv(config_path: str | Path) -> Path | None:
    config_parent = Path(config_path).expanduser().resolve().parent
    candidates = [
        config_parent / ".env",
        Path.cwd() / ".env",
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        loaded = load_dotenv(resolved)
        if loaded is not None:
            return loaded
    return None
