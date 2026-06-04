from datetime import UTC, datetime

from local_housing_searcher.config import NotificationConfig, TelegramNotificationConfig
from local_housing_searcher.models import (
    FurnishingPreference,
    Listing,
    MatchResult,
    RentalType,
    StoredListing,
)
from local_housing_searcher.notifications import NotificationManager, NotificationPayload, build_payload


def make_match() -> tuple[StoredListing, MatchResult]:
    listing = Listing(
        source="pararius-amsterdam",
        external_id="abc123",
        url="https://www.pararius.com/apartment-for-rent/amsterdam/abc123/example",
        canonical_url="https://www.pararius.com/apartment-for-rent/amsterdam/abc123/example",
        title="Flat Examplestraat 1",
        address="Examplestraat 1",
        city="Amsterdam",
        price_eur=2000,
        area_sqm=60,
        bedrooms=1,
        furnishing=FurnishingPreference.UNFURNISHED,
        rental_type=RentalType.APARTMENT,
        fingerprint="fp",
        discovered_at=datetime.now(UTC),
    )
    match = MatchResult(
        listing=listing,
        is_match=True,
        score=91.0,
        is_high_priority=True,
        reasons=["city matched"],
    )
    stored = StoredListing(
        id=1,
        listing=listing,
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        match_score=91.0,
        match_reasons=["city matched"],
    )
    return stored, match


def test_notification_manager_sends_to_multiple_telegram_targets(monkeypatch) -> None:
    config = NotificationConfig(
        desktop={"enabled": False},
        telegram=TelegramNotificationConfig(
            enabled=True,
            bot_token_env="TELEGRAM_BOT_TOKEN",
            chat_id_env="TELEGRAM_CHAT_ID",
        ),
        telegram_targets=[
            TelegramNotificationConfig(
                enabled=True,
                bot_token_env="TELEGRAM_BOT_TOKEN_2",
                chat_id_env="TELEGRAM_CHAT_ID_2",
            )
        ],
    )
    manager = NotificationManager(config)
    stored, match = make_match()
    sent = []

    def fake_send(config_obj, payload):
        sent.append((config_obj.bot_token_env, config_obj.chat_id_env, payload.body))

    monkeypatch.setattr("local_housing_searcher.notifications.send_telegram_notification", fake_send)

    manager.notify(stored, match, dry_run=False)

    assert sent == [
        ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", sent[0][2]),
        ("TELEGRAM_BOT_TOKEN_2", "TELEGRAM_CHAT_ID_2", sent[1][2]),
    ]


def test_notification_manager_does_not_raise_when_telegram_fails(monkeypatch) -> None:
    config = NotificationConfig(
        desktop={"enabled": False},
        telegram=TelegramNotificationConfig(
            enabled=True,
            bot_token_env="TELEGRAM_BOT_TOKEN",
            chat_id_env="TELEGRAM_CHAT_ID",
        ),
    )
    manager = NotificationManager(config)
    stored, match = make_match()

    def fake_send(_config_obj: TelegramNotificationConfig, _payload: NotificationPayload) -> None:
        raise RuntimeError("telegram rejected message")

    monkeypatch.setattr("local_housing_searcher.notifications.send_telegram_notification", fake_send)

    manager.notify(stored, match, dry_run=False)


def test_build_payload_uses_requested_telegram_format() -> None:
    _stored, match = make_match()

    payload = build_payload(match)

    assert payload.title == "Huis gevonden!"
    assert payload.body == (
        "Straat: Examplestraat 1\n"
        "Prijs: 2000\n"
        "Grootte: 60 m2\n"
        "Url: https://www.pararius.com/apartment-for-rent/amsterdam/abc123/example"
    )
