from pathlib import Path

from local_housing_searcher.adapters.base import AdapterContext, BaseAdapter, PageFetchResult
from local_housing_searcher.config import SourceConfig


class DummyAdapter(BaseAdapter):
    def fetch(self):  # pragma: no cover
        raise NotImplementedError


class FakePage:
    def __init__(self) -> None:
        self.screenshot_calls = 0

    def screenshot(self, *, path: str, full_page: bool) -> None:
        self.screenshot_calls += 1
        Path(path).write_bytes(b"png")


def test_block_details_include_debug_artifacts(tmp_path: Path) -> None:
    adapter = DummyAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda",
                adapter="funda",
                debug_artifacts_dir=tmp_path,
            ),
            debug=True,
        )
    )
    page = FakePage()

    screenshot_path, html_path = adapter.maybe_save_debug_artifacts(page, "<html>blocked</html>", "https://www.funda.nl/")
    result = PageFetchResult(
        requested_url="https://www.funda.nl/",
        final_url="https://www.funda.nl/",
        title="Blocked",
        status_code=403,
        html="<html>blocked</html>",
        screenshot_path=screenshot_path,
        html_path=html_path,
    )

    details = adapter.block_details(result, "verification page")

    assert page.screenshot_calls == 1
    assert screenshot_path is not None and Path(screenshot_path).exists()
    assert html_path is not None and Path(html_path).read_text(encoding="utf-8") == "<html>blocked</html>"
    assert details["screenshot_path"] == screenshot_path
    assert details["html_path"] == html_path
