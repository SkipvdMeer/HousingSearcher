from __future__ import annotations

import logging


def configure_logging(level: str, debug: bool = False) -> None:
    effective_level = "DEBUG" if debug else level.upper()
    logging.basicConfig(
        level=effective_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
