from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass

import httpx

from local_housing_searcher.config import NotificationConfig, TelegramNotificationConfig
from local_housing_searcher.models import MatchResult, StoredListing

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class NotificationPayload:
    title: str
    body: str


def build_payload(match: MatchResult) -> NotificationPayload:
    listing = match.listing
    title = "Huis gevonden!"
    street = listing.address or listing.title
    size = f"{listing.area_sqm:.0f} m2" if listing.area_sqm else "onbekend"
    body = (
        f"Straat: {street}\n"
        f"Prijs: {listing.price_eur}\n"
        f"Grootte: {size}\n"
        f"Url: {listing.url}"
    )
    return NotificationPayload(title=title, body=body)


class NotificationManager:
    def __init__(self, config: NotificationConfig) -> None:
        self.config = config

    def notify(self, stored: StoredListing, match: MatchResult, dry_run: bool) -> None:
        payload = build_payload(match)
        if dry_run:
            LOGGER.info("dry-run notification | %s | %s", payload.title, payload.body)
            return
        if self.config.desktop.enabled:
            send_desktop_notification(payload)
        for target in self.config.enabled_telegram_targets():
            send_telegram_notification(target, payload)


def send_desktop_notification(payload: NotificationPayload) -> None:
    system = platform.system().lower()
    if system == "darwin":
        script = (
            'display notification "{body}" with title "{title}"'
            .format(body=payload.body.replace('"', '\\"'), title=payload.title.replace('"', '\\"'))
        )
        subprocess.run(["osascript", "-e", script], check=False)
        return
    if system == "linux" and shutil.which("notify-send"):
        subprocess.run(["notify-send", payload.title, payload.body], check=False)
        return
    LOGGER.info("desktop notifications unavailable on this platform")


def send_telegram_notification(
    config: TelegramNotificationConfig,
    payload: NotificationPayload,
) -> None:
    token, chat_id = config.resolve()
    if not token or not chat_id:
        LOGGER.warning("telegram notification skipped because env vars are missing")
        return
    text = f"{payload.title}\n{payload.body}"
    with httpx.Client(timeout=10.0) as client:
        response = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        )
        response.raise_for_status()
