"""Web UI recorder helpers built on Playwright."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from typing import Literal, Mapping, Sequence
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from demo_video_recorder.backends import (
    PlaywrightVideoCaptureBackend,
)
from demo_video_recorder.core import DemoVideoRecorder
from demo_video_recorder.defaults import DEFAULTS
from demo_video_recorder.errors import RecordingError, WebElementNotFoundError

BrowserName = Literal["chromium", "firefox", "webkit"]
WebVideoBackend = Literal["playwright", "ffmpeg"]
INPUT_SELECTOR = "input, textarea"
SELECT_SELECTOR = "select"


class WebElement:
    """A selected web UI element with recorder-friendly actions."""

    def __init__(self, recorder: "WebUIRecorder", locator: Locator) -> None:
        self.recorder = recorder
        self.locator = locator.first

    def highlight(self, *, duration_ms: int = 700) -> "WebElement":
        self.locator.scroll_into_view_if_needed()
        self.locator.evaluate(
            """
            async (element, duration) => {
                const previousOutline = element.style.outline;
                const previousOffset = element.style.outlineOffset;
                const previousTransition = element.style.transition;
                element.style.transition = 'outline 120ms ease';
                element.style.outline = '4px solid #ffbf00';
                element.style.outlineOffset = '3px';
                await new Promise(resolve => setTimeout(resolve, duration));
                element.style.outline = previousOutline;
                element.style.outlineOffset = previousOffset;
                element.style.transition = previousTransition;
            }
            """,
            duration_ms,
        )
        return self

    def wait(
        self,
        *,
        state: Literal["attached", "detached", "visible", "hidden"] = "visible",
        timeout_seconds: float = 10.0,
    ) -> "WebElement":
        self.locator.wait_for(state=state, timeout=timeout_seconds * 1000)
        return self

    def click(
        self,
        *,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebElement":
        if highlight:
            self.highlight()
        self.locator.click(
            button=button,
            click_count=click_count,
            timeout=timeout_seconds * 1000,
        )
        return self

    def double_click(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebElement":
        if highlight:
            self.highlight()
        self.locator.dblclick(timeout=timeout_seconds * 1000)
        return self

    def hover(self, *, timeout_seconds: float = 10.0) -> "WebElement":
        self.locator.hover(timeout=timeout_seconds * 1000)
        return self

    def text(self, *, timeout_seconds: float = 10.0) -> str:
        return self.locator.inner_text(timeout=timeout_seconds * 1000)

    def attribute(self, name: str, *, timeout_seconds: float = 10.0) -> str | None:
        return self.locator.get_attribute(name, timeout=timeout_seconds * 1000)

    def find(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> "WebElement":
        return self.recorder._find_in_scope(
            self.locator,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_optional(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 2.0,
        **kwargs: object,
    ) -> "WebElement | None":
        return self.recorder._find_optional_in_scope(
            self.locator,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_all(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list["WebElement"]:
        return self.recorder._find_all_in_scope(
            self.locator,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            **kwargs,
        )

    def find_input(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> "WebInputElement":
        return self.recorder._find_input_in_scope(
            self.locator,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_all_input(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list["WebInputElement"]:
        return self.recorder._find_all_input_in_scope(
            self.locator,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            **kwargs,
        )

    def find_select(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> "WebSelectElement":
        return self.recorder._find_select_in_scope(
            self.locator,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_all_select(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list["WebSelectElement"]:
        return self.recorder._find_all_select_in_scope(
            self.locator,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            **kwargs,
        )


class WebInputElement(WebElement):
    """A form control with input-specific actions."""

    def fill(
        self,
        value: str,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight()
        if self.recorder.typed_character_delay > 0:
            self.locator.clear(timeout=timeout_seconds * 1000)
            self.locator.type(
                value,
                delay=self.recorder.typed_character_delay * 1000,
                timeout=timeout_seconds * 1000,
            )
            return self
        self.locator.fill(value, timeout=timeout_seconds * 1000)
        return self

    def type(
        self,
        text: str,
        *,
        delay_ms: float | None = None,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight()
        self.locator.type(text, delay=delay_ms, timeout=timeout_seconds * 1000)
        return self

    def clear(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight()
        self.locator.clear(timeout=timeout_seconds * 1000)
        return self

    def set_value(
        self,
        value: str | int | float,
        *,
        highlight: bool = True,
    ) -> "WebInputElement":
        """Set a control value and emit input/change events.

        This is useful for controls such as ``input[type=range]`` that do not
        behave like text fields but still expose a value.
        """

        if highlight:
            self.highlight()
        self.locator.evaluate(
            """
            (element, value) => {
                element.value = String(value);
                element.dispatchEvent(new Event('input', { bubbles: true }));
                element.dispatchEvent(new Event('change', { bubbles: true }));
            }
            """,
            value,
        )
        return self

    def press(self, key: str, *, timeout_seconds: float = 10.0) -> "WebInputElement":
        self.locator.press(key, timeout=timeout_seconds * 1000)
        return self

    def check(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight()
        self.locator.check(timeout=timeout_seconds * 1000)
        return self

    def uncheck(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight()
        self.locator.uncheck(timeout=timeout_seconds * 1000)
        return self

    def select_option(
        self,
        value: str | Sequence[str] | None = None,
        *,
        label: str | Sequence[str] | None = None,
        index: int | Sequence[int] | None = None,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight()
        self.locator.select_option(
            value=value,
            label=label,
            index=index,
            timeout=timeout_seconds * 1000,
        )
        return self


class WebSelectElement(WebInputElement):
    """A select control with select-specific actions."""

    def select_option(
        self,
        value: str | Sequence[str] | None = None,
        *,
        label: str | Sequence[str] | None = None,
        index: int | Sequence[int] | None = None,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebSelectElement":
        if highlight:
            self.highlight()
        self.locator.select_option(
            value=value,
            label=label,
            index=index,
            timeout=timeout_seconds * 1000,
        )
        return self


class WebFormElement(WebElement):
    """A form element with form-specific actions."""

    def submit(self, *, highlight: bool = True) -> "WebFormElement":
        if highlight:
            self.highlight()
        self.locator.evaluate("""
            form => {
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            }
            """)
        return self


class WebUIRecorder(DemoVideoRecorder):
    """Recorder specialized for browser and Web UI demos."""

    def __init__(
        self,
        output_path: str | Path,
        *,
        browser: BrowserName = "chromium",
        headless: bool = True,
        viewport: tuple[int, int] = (1280, 720),
        video_backend: WebVideoBackend = "playwright",
        slow_mo_ms: float | None = None,
        **kwargs: object,
    ) -> None:
        self.typed_character_delay = float(
            kwargs.pop("typed_character_delay", DEFAULTS.typed_character_delay)
        )
        self.command_lead_seconds = float(
            kwargs.pop("command_lead_seconds", DEFAULTS.command_lead_seconds)
        )
        super().__init__(output_path, **kwargs)  # type: ignore[arg-type]
        self.browser_name = browser
        self.headless = headless
        self.viewport = viewport
        self.video_backend = video_backend
        self.slow_mo_ms = slow_mo_ms
        if video_backend == "playwright":
            self.capture = PlaywrightVideoCaptureBackend(
                self.raw_video_path,
                framerate=kwargs.get(
                    "capture_framerate",
                    DEFAULTS.capture_framerate,
                ),  # type: ignore[arg-type]
                scale_width=kwargs.get(
                    "video_scale_width",
                    DEFAULTS.video_scale_width,
                ),  # type: ignore[arg-type]
                ffmpeg=kwargs.get("ffmpeg", "ffmpeg"),  # type: ignore[arg-type]
                ffprobe=kwargs.get("ffprobe", "ffprobe"),  # type: ignore[arg-type]
            )

        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.server: ThreadingHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.served_url: str | None = None

    def serve(
        self,
        path: str | Path,
        port: int = 8000,
        *,
        host: str = "127.0.0.1",
    ) -> str:
        """Serve a static folder over localhost and return the base URL."""

        if self.server is not None:
            raise RecordingError("A local web server is already running.")

        root = Path(path).resolve()
        if not root.exists() or not root.is_dir():
            raise RecordingError(f"Static web root does not exist: {root}")

        handler = partial(SimpleHTTPRequestHandler, directory=str(root))
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()
        resolved_port = self.server.server_address[1]
        self.served_url = f"http://{host}:{resolved_port}"
        return self.served_url

    def open_web(
        self,
        url: str | None = None,
        *,
        start_recording: bool = True,
        wait_until: Literal[
            "commit", "domcontentloaded", "load", "networkidle"
        ] = "load",
        timeout_seconds: float = 30.0,
        headless: bool | None = None,
        viewport: tuple[int, int] | None = None,
    ) -> "WebUIRecorder":
        """Open a URL in Playwright and optionally start recording immediately."""

        resolved_viewport = viewport or self.viewport
        self._ensure_page(headless=headless, viewport=resolved_viewport)
        if start_recording:
            self.start_recording()

        if url is None:
            if self.served_url is None:
                raise RecordingError("No URL was provided and no folder is served.")
            url = self.served_url
        self.current_page.goto(
            self._normalize_url(url),
            wait_until=wait_until,
            timeout=timeout_seconds * 1000,
        )
        return self

    @property
    def current_page(self) -> Page:
        if self.page is None:
            raise RecordingError("No web page is open. Call open_web() first.")
        return self.page

    def find(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> WebElement:
        return self._find_in_scope(
            self.current_page,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_optional(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 2.0,
        **kwargs: object,
    ) -> WebElement | None:
        return self._find_optional_in_scope(
            self.current_page,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_all(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list[WebElement]:
        return self._find_all_in_scope(
            self.current_page,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            **kwargs,
        )

    def find_input(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> WebInputElement:
        return self._find_input_in_scope(
            self.current_page,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_all_input(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list[WebInputElement]:
        return self._find_all_input_in_scope(
            self.current_page,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            **kwargs,
        )

    def find_select(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> WebSelectElement:
        return self._find_select_in_scope(
            self.current_page,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    def find_all_select(
        self,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list[WebSelectElement]:
        return self._find_all_select_in_scope(
            self.current_page,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            **kwargs,
        )

    def wait_for_url(
        self,
        url: str | re.Pattern[str],
        *,
        timeout_seconds: float = 10.0,
    ) -> "WebUIRecorder":
        self.current_page.wait_for_url(url, timeout=timeout_seconds * 1000)
        return self

    def stop_recording(self, *, burn: bool | None = None) -> Path:
        final_path = super().stop_recording(burn=burn)
        self._cleanup_web_runtime(close_context=False)
        return final_path

    def close(self) -> None:
        super().close()
        if self.capture.is_recording:
            return
        self._cleanup_web_runtime(close_context=True)

    def _cleanup_web_runtime(self, *, close_context: bool) -> None:
        if close_context and self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
        self.context = None
        self.page = None
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.server_thread is not None:
            self.server_thread.join(timeout=2)
            self.server_thread = None

    def _ensure_page(
        self,
        *,
        headless: bool | None,
        viewport: tuple[int, int],
    ) -> None:
        if self.page is not None:
            return
        if self.playwright is None:
            self.playwright = sync_playwright().start()
        if self.browser is None:
            browser_type = getattr(self.playwright, self.browser_name)
            launch_options: dict[str, object] = {
                "headless": self.headless if headless is None else headless,
            }
            if self.slow_mo_ms is not None:
                launch_options["slow_mo"] = self.slow_mo_ms
            self.browser = browser_type.launch(**launch_options)

        assert self.browser is not None

        context_options: dict[str, object] = {
            "viewport": {"width": viewport[0], "height": viewport[1]},
        }
        if isinstance(self.capture, PlaywrightVideoCaptureBackend):
            context_options.update(
                self.capture.context_video_options(
                    width=viewport[0],
                    height=viewport[1],
                )
            )
        self.context = self.browser.new_context(**context_options)  # type: ignore
        self.page = self.context.new_page()
        if isinstance(self.capture, PlaywrightVideoCaptureBackend):
            self.capture.attach_page(self.page)

    def _find_in_scope(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        base_selector: str | None = None,
        **kwargs: object,
    ) -> WebElement:
        locator = self._locator_for(
            scope,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            base_selector=base_selector,
            **kwargs,
        ).first
        try:
            locator.wait_for(state="visible", timeout=timeout_seconds * 1000)
        except PlaywrightTimeoutError as exc:
            raise WebElementNotFoundError(
                f"No visible web element matched {self._describe_query(name, attrs, selector, role, kwargs)}."
            ) from exc
        return self._wrap_element(locator)

    def _find_input_in_scope(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> WebInputElement:
        element = self._find_in_scope(
            scope,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            base_selector=INPUT_SELECTOR,
            **kwargs,
        )
        if not isinstance(element, WebInputElement) or isinstance(
            element, WebSelectElement
        ):
            raise WebElementNotFoundError(
                f"No visible input element matched {self._describe_query(name, attrs, selector, role, kwargs)}."
            )
        return element

    def _find_select_in_scope(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 10.0,
        **kwargs: object,
    ) -> WebSelectElement:
        element = self._find_in_scope(
            scope,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            timeout_seconds=timeout_seconds,
            base_selector=SELECT_SELECTOR,
            **kwargs,
        )
        if not isinstance(element, WebSelectElement):
            raise WebElementNotFoundError(
                f"No visible select element matched {self._describe_query(name, attrs, selector, role, kwargs)}."
            )
        return element

    def _find_optional_in_scope(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        timeout_seconds: float = 2.0,
        **kwargs: object,
    ) -> WebElement | None:
        try:
            return self._find_in_scope(
                scope,
                name,
                attrs,
                text=text,
                string=string,
                selector=selector,
                role=role,
                timeout_seconds=timeout_seconds,
                **kwargs,
            )
        except WebElementNotFoundError:
            return None

    def _find_all_in_scope(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        base_selector: str | None = None,
        **kwargs: object,
    ) -> list[WebElement]:
        locator = self._locator_for(
            scope,
            name,
            attrs,
            text=text,
            string=string,
            selector=selector,
            role=role,
            base_selector=base_selector,
            **kwargs,
        )
        return [
            self._wrap_element(locator.nth(index)) for index in range(locator.count())
        ]

    def _find_all_input_in_scope(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list[WebInputElement]:
        return [
            element
            for element in self._find_all_in_scope(
                scope,
                name,
                attrs,
                text=text,
                string=string,
                selector=selector,
                role=role,
                base_selector=INPUT_SELECTOR,
                **kwargs,
            )
            if isinstance(element, WebInputElement)
            and not isinstance(element, WebSelectElement)
        ]

    def _find_all_select_in_scope(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        **kwargs: object,
    ) -> list[WebSelectElement]:
        return [
            element
            for element in self._find_all_in_scope(
                scope,
                name,
                attrs,
                text=text,
                string=string,
                selector=selector,
                role=role,
                base_selector=SELECT_SELECTOR,
                **kwargs,
            )
            if isinstance(element, WebSelectElement)
        ]

    def _locator_for(
        self,
        scope: Page | Locator,
        name: str | None = None,
        attrs: Mapping[str, object] | None = None,
        *,
        text: str | re.Pattern[str] | None = None,
        string: str | re.Pattern[str] | None = None,
        selector: str | None = None,
        role: str | None = None,
        base_selector: str | None = None,
        **kwargs: object,
    ) -> Locator:
        query_attrs = dict(attrs or {})
        query_attrs.update(kwargs)
        text_filter = string if string is not None else text

        if role is not None:
            role_name = query_attrs.pop("name", None)
            css_name = name
            if role_name is None and name is not None:
                role_name = name
                css_name = None
            locator = scope.get_by_role(role, name=role_name)  # type: ignore[arg-type]
        elif "label" in query_attrs:
            css_name = name
            locator = scope.get_by_label(str(query_attrs.pop("label")))
        elif "placeholder" in query_attrs:
            css_name = name
            locator = scope.get_by_placeholder(str(query_attrs.pop("placeholder")))
        elif "test_id" in query_attrs:
            css_name = name
            locator = scope.get_by_test_id(str(query_attrs.pop("test_id")))
        elif "title" in query_attrs:
            css_name = name
            locator = scope.get_by_title(str(query_attrs.pop("title")))
        else:
            css_selector = selector or _css_selector_from_find_args(name, query_attrs)
            return self._apply_text_filter(
                scope.locator(_combine_css_selectors(base_selector, css_selector)),
                text_filter,
            )

        remaining_selector = selector or _css_selector_from_find_args(
            css_name, query_attrs
        )
        if base_selector is not None or remaining_selector != "*":
            locator = locator.and_(
                scope.locator(_combine_css_selectors(base_selector, remaining_selector))
            )

        return self._apply_text_filter(locator, text_filter)

    def _apply_text_filter(
        self,
        locator: Locator,
        text_filter: str | re.Pattern[str] | None,
    ) -> Locator:
        if text_filter is not None:
            locator = locator.filter(has_text=text_filter)
        return locator

    def _wrap_element(self, locator: Locator) -> WebElement:
        try:
            tag = str(locator.evaluate("element => element.tagName.toLowerCase()"))
        except Exception:
            return WebElement(self, locator)
        if tag in {"input", "textarea"}:
            return WebInputElement(self, locator)
        if tag == "select":
            return WebSelectElement(self, locator)
        if tag == "form":
            return WebFormElement(self, locator)
        return WebElement(self, locator)

    def _normalize_url(self, url: str) -> str:
        if url.startswith("/"):
            if self.served_url is None:
                raise RecordingError(
                    "Relative URLs need a served folder. Call serve() first."
                )
            return f"{self.served_url}{url}"

        if url.startswith("localhost") or url.startswith("127.0.0.1"):
            return f"http://{url}"
        parsed = urlparse(url)
        if parsed.scheme:
            return url
        return f"https://{url}"

    def _describe_query(
        self,
        name: str | None,
        attrs: Mapping[str, object] | None,
        selector: str | None,
        role: str | None,
        kwargs: Mapping[str, object],
    ) -> str:
        parts: list[str] = []
        if selector:
            parts.append(f"selector={selector!r}")
        if role:
            parts.append(f"role={role!r}")
        if name:
            parts.append(f"name={name!r}")
        merged_attrs = dict(attrs or {})
        merged_attrs.update(kwargs)
        if merged_attrs:
            parts.append(f"attrs={merged_attrs!r}")
        return ", ".join(parts) if parts else "the empty query"


def _css_selector_from_find_args(
    name: str | None,
    attrs: Mapping[str, object],
) -> str:
    selector = name or "*"
    for raw_key, raw_value in attrs.items():
        key = "class" if raw_key in {"class_", "_class"} else raw_key.replace("_", "-")
        if raw_value is False or raw_value is None:
            continue
        if raw_value is True:
            selector += f"[{key}]"
            continue
        operator = "~=" if key == "class" else "="
        selector += f"[{key}{operator}{_css_string(str(raw_value))}]"
    return selector


def _combine_css_selectors(
    base_selector: str | None,
    selector: str,
) -> str:
    if base_selector is None:
        return selector
    if selector == "*":
        return base_selector
    return f":is({base_selector}):is({selector})"


def _css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
