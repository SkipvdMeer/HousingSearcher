import threading

import pytest

from local_housing_searcher.scheduler import run_scheduler


class _Summary:
    total_new_matches = 0


class _Service:
    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self.calls = 0

    def poll_once(self) -> _Summary:
        self.calls += 1
        self.stop_event.set()
        return _Summary()


def test_run_scheduler_stops_when_stop_event_is_set() -> None:
    stop_event = threading.Event()
    service = _Service(stop_event)

    run_scheduler(service, 3600, stop_event=stop_event)

    assert service.calls == 1


def test_run_scheduler_rejects_non_positive_intervals() -> None:
    stop_event = threading.Event()
    service = _Service(stop_event)

    with pytest.raises(ValueError, match="greater than 0"):
        run_scheduler(service, 0, stop_event=stop_event)
