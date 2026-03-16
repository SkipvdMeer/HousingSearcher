from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    compact = re.sub(r"\s+", " ", value).strip().lower()
    return compact


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.startswith("utm_")
    ]
    normalized_path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            normalized_path,
            "",
            urlencode(filtered_query),
            "",
        )
    )


def extract_digits(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None
