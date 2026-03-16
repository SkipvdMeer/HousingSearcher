from __future__ import annotations

import logging
import signal
import threading

from local_housing_searcher.service import PollService

LOGGER = logging.getLogger(__name__)


def _install_signal_handlers(stop_event: threading.Event) -> dict[signal.Signals, signal.Handlers]:
    previous_handlers: dict[signal.Signals, signal.Handlers] = {}

    def handle_signal(signum: int, _frame) -> None:
        LOGGER.info("received %s, stopping scheduler", signal.Signals(signum).name)
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, handle_signal)
    return previous_handlers


def _restore_signal_handlers(previous_handlers: dict[signal.Signals, signal.Handlers]) -> None:
    for signum, previous_handler in previous_handlers.items():
        signal.signal(signum, previous_handler)


def run_scheduler(
    service: PollService,
    poll_interval_seconds: int,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0")

    managed_stop_event = stop_event is None
    scheduler_stop_event = stop_event or threading.Event()
    previous_handlers: dict[signal.Signals, signal.Handlers] = {}
    if managed_stop_event:
        previous_handlers = _install_signal_handlers(scheduler_stop_event)

    LOGGER.info("starting scheduler with %s second interval", poll_interval_seconds)
    try:
        while not scheduler_stop_event.is_set():
            summary = service.poll_once()
            LOGGER.info("poll cycle complete | new matches=%s", summary.total_new_matches)
            if scheduler_stop_event.wait(poll_interval_seconds):
                break
    finally:
        if managed_stop_event:
            _restore_signal_handlers(previous_handlers)
        LOGGER.info("scheduler stopped")
