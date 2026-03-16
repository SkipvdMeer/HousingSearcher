from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse
from typing import TYPE_CHECKING

from playwright.sync_api import sync_playwright

from local_housing_searcher.config import FilterConfig, SourceConfig
from local_housing_searcher.models import AdapterHealth, AdapterResult

if TYPE_CHECKING:
    from local_housing_searcher.db import Database


@dataclass(slots=True)
class AdapterContext:
    source: SourceConfig
    filters: FilterConfig | None = None
    database: Database | None = None
    debug: bool = False


@dataclass(slots=True)
class PageFetchResult:
    requested_url: str
    final_url: str
    title: str
    status_code: int | None
    html: str
    screenshot_path: str | None = None
    html_path: str | None = None

    @property
    def content_length(self) -> int:
        return len(self.html)


# ---------------------------------------------------------------------------
# Stealth helpers
# ---------------------------------------------------------------------------

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Patches injected before any page script runs.
# Covers: webdriver flag, plugins, languages, window.chrome,
# permission fingerprinting, canvas noise, WebGL renderer spoof.
_STEALTH_INIT_SCRIPT = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer',  filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client',      filename: 'internal-nacl-plugin' },
        ],
    });

    Object.defineProperty(navigator, 'languages', { get: () => ['nl-NL', 'nl', 'en-US', 'en'] });

    if (!window.chrome) { window.chrome = { runtime: {} }; }

    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);

    // Canvas fingerprint noise — adds tiny per-session pixel shifts
    const toBlob     = HTMLCanvasElement.prototype.toBlob;
    const toDataURL  = HTMLCanvasElement.prototype.toDataURL;
    const getImgData = CanvasRenderingContext2D.prototype.getImageData;
    const _noisify = (canvas, ctx) => {
        const s = { r: (Math.random()*10|0)-5, g: (Math.random()*10|0)-5,
                    b: (Math.random()*10|0)-5, a: (Math.random()*10|0)-5 };
        if (canvas.width && canvas.height) {
            const d = getImgData.call(ctx, 0, 0, canvas.width, canvas.height);
            for (let i = 0; i < d.data.length; i += 4) {
                d.data[i]+=s.r; d.data[i+1]+=s.g; d.data[i+2]+=s.b; d.data[i+3]+=s.a;
            }
            ctx.putImageData(d, 0, 0);
        }
    };
    HTMLCanvasElement.prototype.toBlob    = function() { _noisify(this,this.getContext('2d')); return toBlob.apply(this,arguments); };
    HTMLCanvasElement.prototype.toDataURL = function() { _noisify(this,this.getContext('2d')); return toDataURL.apply(this,arguments); };
    CanvasRenderingContext2D.prototype.getImageData = function() { _noisify(this.canvas,this); return getImgData.apply(this,arguments); };

    // WebGL renderer strings — match common Mac Intel GPU
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return getParam.apply(this, arguments);
    };
}
"""

_DEFAULT_PROFILE_BASE = Path.home() / ".local_housing_searcher" / "browser_profiles"


def _apply_stealth(page) -> None:
    """Inject stealth patches into every frame before any script runs."""
    page.add_init_script(_STEALTH_INIT_SCRIPT)


def _human_delay(lo: float = 0.8, hi: float = 2.5) -> None:
    """Sleep for a random duration to mimic human think-time."""
    time.sleep(random.uniform(lo, hi))


def _move_mouse_randomly(page) -> None:
    """Two random mouse moves to trigger behavioural heuristics."""
    try:
        page.mouse.move(random.randint(200, 1200), random.randint(150, 700))
        page.mouse.move(random.randint(200, 1200), random.randint(150, 700))
    except Exception:
        pass


def _wait_for_challenge_resolution(page, timeout_ms: int = 20_000) -> bool:
    """
    Poll document.title until Funda's JS challenge self-resolves and redirects.
    Returns True if the title changed away from the challenge phrase, False on timeout.
    """
    try:
        page.wait_for_function(
            "() => !document.title.includes('Je bent bijna op de pagina')",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def _is_challenge_page(page) -> bool:
    return "je bent bijna op de pagina" in page.title().lower()


# ---------------------------------------------------------------------------
# Base adapter
# ---------------------------------------------------------------------------

class BaseAdapter(ABC):
    def __init__(self, context: AdapterContext) -> None:
        self.context = context
        self.logger = logging.getLogger(self.__class__.__module__)

    @abstractmethod
    def fetch(self) -> AdapterResult:
        raise NotImplementedError

    def wrap_result(
        self,
        *,
        listings,
        ok: bool,
        message: str,
        details: dict | None = None,
        started_at: float,
    ) -> AdapterResult:
        duration_ms = int((perf_counter() - started_at) * 1000)
        return AdapterResult(
            source_id=self.context.source.id,
            listings=listings,
            duration_ms=duration_ms,
            health=AdapterHealth(
                source_id=self.context.source.id,
                ok=ok,
                message=message,
                details=details or {},
            ),
        )

    def get_page_html(self, url: str, timeout_seconds: int) -> str:
        return self.fetch_page(
            url,
            timeout_seconds,
            headless=self.context.source.headless,
            wait_until=self.context.source.wait_until,
            extra_wait_ms=self.context.source.extra_wait_ms,
        ).html

    def fetch_page(
        self,
        url: str,
        timeout_seconds: int,
        *,
        headless: bool,
        wait_until: str,
        extra_wait_ms: int,
    ) -> PageFetchResult:
        source = self.context.source
        stealth_mode: bool = getattr(source, "stealth", False)
        proxy_config: dict | None = getattr(source, "proxy", None)
        # persistent_profile defaults to True when stealth is enabled so that
        # Funda's challenge cookies survive across poll cycles.
        use_persistent_profile: bool = getattr(source, "persistent_profile", stealth_mode)
        profile_base: Path = Path(getattr(source, "profile_dir", str(_DEFAULT_PROFILE_BASE)))

        self.logger.debug(
            "%s fetch start | url=%s | headless=%s | stealth=%s | persistent_profile=%s"
            " | wait_until=%s | extra_wait_ms=%s | timeout_seconds=%s",
            source.id, url, headless, stealth_mode, use_persistent_profile,
            wait_until, extra_wait_ms, timeout_seconds,
        )

        with sync_playwright() as playwright:
            launch_args = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--enable-unsafe-swiftshader",  # canvas spoofing in headless
            ]
            if not headless:
                # Keep headed debug runs out of the visible desktop when possible.
                launch_args.append("--window-position=-2000,0")

            launch_kwargs: dict = {
                "headless": headless,
                "args": launch_args,
            }

            parsed = urlparse(url)
            homepage = f"{parsed.scheme}://{parsed.netloc}/"

            if use_persistent_profile:
                # ------------------------------------------------------------------
                # Persistent profile: reuse cookies, localStorage, and fingerprint
                # across runs. After the first successful challenge Funda recognises
                # the profile and skips the challenge on subsequent visits.
                # ------------------------------------------------------------------
                profile_dir = profile_base / source.id
                profile_dir.mkdir(parents=True, exist_ok=True)
                self.logger.debug("%s using persistent profile | dir=%s", source.id, profile_dir)

                context_kwargs: dict = {"user_data_dir": str(profile_dir)}
                if stealth_mode:
                    context_kwargs.update({
                        "user_agent": _DEFAULT_USER_AGENT,
                        "viewport": {"width": 1920, "height": 1080},
                        "locale": "nl-NL",
                        "timezone_id": "Europe/Amsterdam",
                        "geolocation": {"latitude": 52.3676, "longitude": 4.9041},
                        "permissions": ["geolocation"],
                        "color_scheme": "light",
                        "device_scale_factor": 1,
                    })
                if proxy_config:
                    context_kwargs["proxy"] = proxy_config

                browser_context = playwright.chromium.launch_persistent_context(
                    **context_kwargs,
                    **launch_kwargs,
                )
                page = browser_context.new_page()

            else:
                # ------------------------------------------------------------------
                # Ephemeral context: original behaviour for non-stealth sources.
                # ------------------------------------------------------------------
                browser = playwright.chromium.launch(**launch_kwargs)
                context_kwargs = {}
                if proxy_config:
                    context_kwargs["proxy"] = proxy_config
                browser_context = browser.new_context(**context_kwargs)
                page = browser_context.new_page()

            if stealth_mode:
                _apply_stealth(page)

            # ------------------------------------------------------------------
            # Warm-up: visit homepage first for a natural entry path, then wait
            # out any JS challenge before navigating to the target URL.
            # ------------------------------------------------------------------
            if stealth_mode and url != homepage:
                self.logger.debug("%s stealth warm-up | loading homepage %s", source.id, homepage)
                try:
                    page.goto(homepage, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)

                    if _is_challenge_page(page):
                        self.logger.debug("%s challenge on homepage, waiting for resolution...", source.id)
                        resolved = _wait_for_challenge_resolution(page, timeout_ms=25_000)
                        self.logger.debug("%s homepage challenge resolved=%s", source.id, resolved)
                        if resolved:
                            try:
                                page.wait_for_load_state("networkidle", timeout=10_000)
                            except Exception:
                                pass
                        else:
                            self.logger.warning(
                                "%s homepage challenge timed out — continuing with existing profile state",
                                source.id,
                            )

                    _human_delay(1.5, 3.0)
                    _move_mouse_randomly(page)
                    _human_delay(0.5, 1.5)
                    self._try_accept_cookies(page)
                    _human_delay(0.8, 2.0)
                except Exception as exc:
                    self.logger.debug("%s stealth warm-up failed (non-fatal): %s", source.id, exc)

            # ------------------------------------------------------------------
            # Main navigation to the actual target URL
            # ------------------------------------------------------------------
            response = page.goto(url, wait_until=wait_until, timeout=timeout_seconds * 1000)

            if stealth_mode:
                if _is_challenge_page(page):
                    self.logger.debug("%s challenge on target page, waiting for resolution...", source.id)
                    resolved = _wait_for_challenge_resolution(page, timeout_ms=30_000)
                    self.logger.debug("%s target challenge resolved=%s", source.id, resolved)
                    if resolved:
                        try:
                            page.wait_for_load_state("networkidle", timeout=10_000)
                        except Exception:
                            pass
                _human_delay(1.0, 2.5)
                _move_mouse_randomly(page)

            if extra_wait_ms > 0:
                page.wait_for_timeout(extra_wait_ms)

            html = page.content()
            screenshot_path, html_path = self.maybe_save_debug_artifacts(page, html, url)

            result = PageFetchResult(
                requested_url=url,
                final_url=page.url,
                title=page.title(),
                status_code=response.status if response else None,
                html=html,
                screenshot_path=screenshot_path,
                html_path=html_path,
            )

            self.logger.debug(
                "%s fetch complete | status=%s | final_url=%s | title=%r | content_length=%s",
                source.id, result.status_code, result.final_url, result.title, result.content_length,
            )
            self.logger.debug("%s fetch preview | %s", source.id, self.html_preview(result.html))

            browser_context.close()
            return result

    # ------------------------------------------------------------------
    # Cookie / consent helpers
    # ------------------------------------------------------------------

    def _try_accept_cookies(self, page) -> None:
        """Best-effort click on common Dutch cookie consent buttons."""
        selectors = [
            "button[data-testid='accept-button']",
            "#didomi-notice-agree-button",
            "button:has-text('Accepteren')",
            "button:has-text('Alles accepteren')",
            "button:has-text('Akkoord')",
            "button:has-text('Accept')",
            "button:has-text('Accept all')",
            "[aria-label='Accept cookies']",
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    self.logger.debug("Cookie consent accepted via selector: %s", selector)
                    _human_delay(0.4, 0.9)
                    return
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Access block detection — unchanged from original
    # ------------------------------------------------------------------

    def detect_access_block(self, html: str) -> str | None:
        normalized = html.lower()
        strong_markers = {
            "just a moment": "bot challenge encountered",
            "cf-challenge": "cloudflare challenge encountered",
            "verify you are human": "human verification encountered",
            "je bent bijna op de pagina": "site returned verification page",
        }
        for needle, message in strong_markers.items():
            if needle in normalized:
                return message
        captcha_markers = [
            "g-recaptcha", "hcaptcha", "cf-turnstile",
            "data-sitekey", "captcha-container", "captcha__", "/captcha/",
        ]
        for needle in captcha_markers:
            if needle in normalized:
                return "captcha encountered"
        return None

    def html_preview(self, html: str, length: int = 240) -> str:
        collapsed = re.sub(r"\s+", " ", html).strip()
        return collapsed[:length]

    def block_details(self, fetch_result: PageFetchResult, reason: str) -> dict[str, str | int | None]:
        return {
            "reason": reason,
            "requested_url": fetch_result.requested_url,
            "final_url": fetch_result.final_url,
            "status_code": fetch_result.status_code,
            "title": fetch_result.title,
            "html_preview": self.html_preview(fetch_result.html, length=320),
            "screenshot_path": fetch_result.screenshot_path,
            "html_path": fetch_result.html_path,
        }

    def log_access_block(self, fetch_result: PageFetchResult, reason: str) -> None:
        self.logger.warning(
            "%s access blocked | reason=%s | status=%s | final_url=%s | title=%r | preview=%s",
            self.context.source.id, reason, fetch_result.status_code,
            fetch_result.final_url, fetch_result.title,
            self.html_preview(fetch_result.html, length=220),
        )

    def log_parse_summary(
        self,
        *,
        candidate_count: int,
        parsed_count: int,
        skip_counts: dict[str, int],
    ) -> None:
        self.logger.debug(
            "%s parse summary | candidates=%s | parsed=%s | skip_counts=%s",
            self.context.source.id, candidate_count, parsed_count, skip_counts,
        )

    def maybe_save_debug_artifacts(self, page, html: str, url: str) -> tuple[str | None, str | None]:
        artifacts_dir = self.context.source.debug_artifacts_dir
        if artifacts_dir is None or not self.context.debug:
            return None, None
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        stem = self.artifact_stem(url)
        screenshot_path = (artifacts_dir / f"{stem}.png").resolve()
        html_path = (artifacts_dir / f"{stem}.html").resolve()
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as exc:
            self.logger.warning("%s failed to save screenshot artifact: %s", self.context.source.id, exc)
            screenshot_path_str: str | None = None
        else:
            screenshot_path_str = str(screenshot_path)
        try:
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            self.logger.warning("%s failed to save html artifact: %s", self.context.source.id, exc)
            html_path_str: str | None = None
        else:
            html_path_str = str(html_path)
        return screenshot_path_str, html_path_str

    def artifact_stem(self, url: str) -> str:
        hostname = urlparse(url).netloc.replace(".", "-") or "page"
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"{self.context.source.id}-{hostname}-{timestamp}"


def build_adapter(context: AdapterContext) -> BaseAdapter:
    from local_housing_searcher.adapters.directwonen import DirectWonenAdapter
    from local_housing_searcher.adapters.funda import FundaAdapter
    from local_housing_searcher.adapters.huurwoningen import HuurwoningenAdapter
    from local_housing_searcher.adapters.mock import MockAdapter
    from local_housing_searcher.adapters.pararius import ParariusAdapter
    from local_housing_searcher.adapters.vbt import VbtAdapter
    from local_housing_searcher.adapters.vanderlinden import VanDerLindenAdapter

    registry = {
        "directwonen": DirectWonenAdapter,
        "funda": FundaAdapter,
        "huurwoningen": HuurwoningenAdapter,
        "mock": MockAdapter,
        "pararius": ParariusAdapter,
        "vbt": VbtAdapter,
        "vanderlinden": VanDerLindenAdapter,
    }
    try:
        adapter_cls = registry[context.source.adapter]
    except KeyError as exc:
        raise KeyError(f"unsupported adapter '{context.source.adapter}'") from exc
    return adapter_cls(context)
