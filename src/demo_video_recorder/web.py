"""Web UI recorder helpers built on Playwright."""

from __future__ import annotations

from difflib import SequenceMatcher
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
import time
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

    def highlight(
        self,
        *,
        duration_ms: int = 700,
        scroll_duration_ms: int | None = None,
        scope: Literal["element", "field"] = "element",
    ) -> "WebElement":
        resolved_scroll_duration_ms = (
            self.recorder.scroll_duration_ms
            if scroll_duration_ms is None
            else scroll_duration_ms
        )
        self.locator.evaluate(
            """
            async (element, args) => {
                const target = args.scope === 'field'
                    ? element.closest('label, .field, fieldset, [role="group"]') || element
                    : element;
                const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
                const ease = progress => 1 - Math.pow(1 - progress, 3);
                const scrollWindowToTarget = async () => {
                    const rect = target.getBoundingClientRect();
                    const startX = window.scrollX;
                    const startY = window.scrollY;
                    const maxX = Math.max(
                        0,
                        document.documentElement.scrollWidth - window.innerWidth,
                    );
                    const maxY = Math.max(
                        0,
                        document.documentElement.scrollHeight - window.innerHeight,
                    );
                    const endX = Math.min(
                        Math.max(startX + rect.left - ((window.innerWidth - rect.width) / 2), 0),
                        maxX,
                    );
                    const endY = Math.min(
                        Math.max(startY + rect.top - ((window.innerHeight - rect.height) / 2), 0),
                        maxY,
                    );
                    const duration = Math.max(0, Number(args.scrollDuration) || 0);

                    if (duration <= 0 || (Math.abs(endX - startX) < 1 && Math.abs(endY - startY) < 1)) {
                        window.scrollTo(endX, endY);
                        return;
                    }

                    const startedAt = performance.now();
                    await new Promise(resolve => {
                        const step = now => {
                            const progress = Math.min((now - startedAt) / duration, 1);
                            const eased = ease(progress);
                            window.scrollTo(
                                startX + ((endX - startX) * eased),
                                startY + ((endY - startY) * eased),
                            );
                            if (progress < 1) {
                                requestAnimationFrame(step);
                            } else {
                                resolve();
                            }
                        };
                        requestAnimationFrame(step);
                    });
                };

                try {
                    await scrollWindowToTarget();
                } catch {
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'center',
                        inline: 'center',
                    });
                    await wait(Math.max(300, Number(args.scrollDuration) || 0));
                }

                const previousOutline = target.style.outline;
                const previousOffset = target.style.outlineOffset;
                const previousTransition = target.style.transition;
                const previousRadius = target.style.borderRadius;
                target.style.transition = 'outline 120ms ease';
                target.style.outline = '4px solid #ffbf00';
                target.style.outlineOffset = '3px';
                if (!target.style.borderRadius) {
                    target.style.borderRadius = '6px';
                }
                await new Promise(resolve => setTimeout(resolve, args.duration));
                target.style.outline = previousOutline;
                target.style.outlineOffset = previousOffset;
                target.style.transition = previousTransition;
                target.style.borderRadius = previousRadius;
            }
            """,
            {
                "duration": duration_ms,
                "scrollDuration": resolved_scroll_duration_ms,
                "scope": scope,
            },
        )
        return self

    def smooth_scroll(
        self,
        *,
        duration_ms: int | None = None,
        block: Literal["start", "center", "end", "nearest"] = "center",
        inline: Literal["start", "center", "end", "nearest"] = "center",
    ) -> "WebElement":
        """Smooth-scroll this element into view without highlighting it."""

        resolved_duration_ms = (
            self.recorder.scroll_duration_ms if duration_ms is None else duration_ms
        )
        self.locator.evaluate(
            """
            async (element, args) => {
                const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
                const target = element;
                const rect = target.getBoundingClientRect();
                const startX = window.scrollX;
                const startY = window.scrollY;
                const maxX = Math.max(
                    0,
                    document.documentElement.scrollWidth - window.innerWidth,
                );
                const maxY = Math.max(
                    0,
                    document.documentElement.scrollHeight - window.innerHeight,
                );

                const targetX = () => {
                    if (args.inline === 'start') {
                        return startX + rect.left;
                    }
                    if (args.inline === 'end') {
                        return startX + rect.right - window.innerWidth;
                    }
                    if (args.inline === 'nearest') {
                        if (rect.left >= 0 && rect.right <= window.innerWidth) {
                            return startX;
                        }
                        return startX + rect.left;
                    }
                    return startX + rect.left - ((window.innerWidth - rect.width) / 2);
                };

                const targetY = () => {
                    if (args.block === 'start') {
                        return startY + rect.top;
                    }
                    if (args.block === 'end') {
                        return startY + rect.bottom - window.innerHeight;
                    }
                    if (args.block === 'nearest') {
                        if (rect.top >= 0 && rect.bottom <= window.innerHeight) {
                            return startY;
                        }
                        return startY + rect.top;
                    }
                    return startY + rect.top - ((window.innerHeight - rect.height) / 2);
                };

                const endX = Math.min(Math.max(targetX(), 0), maxX);
                const endY = Math.min(Math.max(targetY(), 0), maxY);
                const duration = Math.max(0, Number(args.duration) || 0);
                if (duration <= 0 || (Math.abs(endX - startX) < 1 && Math.abs(endY - startY) < 1)) {
                    window.scrollTo(endX, endY);
                    return;
                }

                const startedAt = performance.now();
                const ease = progress => 1 - Math.pow(1 - progress, 3);
                await new Promise(resolve => {
                    const step = now => {
                        const progress = Math.min((now - startedAt) / duration, 1);
                        const eased = ease(progress);
                        window.scrollTo(
                            startX + ((endX - startX) * eased),
                            startY + ((endY - startY) * eased),
                        );
                        if (progress < 1) {
                            requestAnimationFrame(step);
                        } else {
                            resolve();
                        }
                    };
                    requestAnimationFrame(step);
                });
                await wait(20);
            }
            """,
            {
                "duration": resolved_duration_ms,
                "block": block,
                "inline": inline,
            },
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
        self._pause_after_action()
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
        self._pause_after_action()
        return self

    def hover(self, *, timeout_seconds: float = 10.0) -> "WebElement":
        self.smooth_scroll()
        self.locator.hover(timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def text(self, *, timeout_seconds: float = 10.0) -> str:
        return self.locator.inner_text(timeout=timeout_seconds * 1000)

    def attribute(self, name: str, *, timeout_seconds: float = 10.0) -> str | None:
        return self.locator.get_attribute(name, timeout=timeout_seconds * 1000)

    def copy_text(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> str:
        """Copy this element's text to the clipboard without selecting the page."""

        if highlight:
            self.highlight()
        text = self.text(timeout_seconds=timeout_seconds)
        self.recorder.write_clipboard_text(text)
        self._pause_after_action()
        return text

    def _pause_after_action(self, seconds: float | None = None) -> None:
        self.recorder.pause(seconds)

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
            **kwargs,  # type: ignore
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
            self._pause_after_action()
            return self
        self.locator.fill(value, timeout=timeout_seconds * 1000)
        self._pause_after_action()
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
        self._pause_after_action()
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
        self._pause_after_action()
        return self

    def edit_text(
        self,
        value: str,
        *,
        remove_chars: int | None = None,
        backspace_delay_ms: float | None = None,
        type_delay_ms: float | None = None,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        """Edit text by applying the smallest visible keyboard changes."""

        if highlight:
            self.highlight()
        self.locator.click(timeout=timeout_seconds * 1000)

        if remove_chars is not None:
            return self._replace_from_end(
                value,
                remove_chars=remove_chars,
                backspace_delay_ms=backspace_delay_ms,
                type_delay_ms=type_delay_ms,
                timeout_seconds=timeout_seconds,
            )

        current_value = str(
            self.locator.evaluate("element => String(element.value ?? '')") or ""
        )
        edits = self._diff_text_edits(current_value, value)
        if not edits:
            return self

        resolved_backspace_delay = (
            self.recorder.typed_character_delay * 1000
            if backspace_delay_ms is None
            else backspace_delay_ms
        )
        resolved_type_delay = (
            self.recorder.typed_character_delay * 1000
            if type_delay_ms is None
            else type_delay_ms
        )

        running_length = len(current_value)
        for start, end, replacement in reversed(edits):
            restore_type = self._move_caret(
                end,
                current_length=running_length,
                timeout_seconds=timeout_seconds,
            )
            try:
                for _ in range(end - start):
                    self._press_edit_key("Backspace", timeout_seconds=timeout_seconds)
                    if resolved_backspace_delay > 0:
                        time.sleep(resolved_backspace_delay / 1000)
                if replacement:
                    self._type_edit_text(
                        replacement,
                        delay=resolved_type_delay,
                        timeout_seconds=timeout_seconds,
                    )
            finally:
                self._restore_input_type(restore_type)
            running_length += len(replacement) - (end - start)
        self._pause_after_action()
        return self

    def _replace_from_end(
        self,
        value: str,
        *,
        remove_chars: int,
        backspace_delay_ms: float | None,
        type_delay_ms: float | None,
        timeout_seconds: float,
    ) -> "WebInputElement":
        current_length = int(self.locator.evaluate("""
                element => {
                    const value = String(element.value ?? '');
                    element.focus();
                    return value.length;
                }
                """) or 0)
        restore_type = self._move_caret(
            current_length,
            current_length=current_length,
            timeout_seconds=timeout_seconds,
        )
        try:
            delete_count = min(max(remove_chars, 0), current_length)
            resolved_backspace_delay = (
                self.recorder.typed_character_delay * 1000
                if backspace_delay_ms is None
                else backspace_delay_ms
            )
            for _ in range(delete_count):
                self._press_edit_key("Backspace", timeout_seconds=timeout_seconds)
                if resolved_backspace_delay > 0:
                    time.sleep(resolved_backspace_delay / 1000)

            resolved_type_delay = (
                self.recorder.typed_character_delay * 1000
                if type_delay_ms is None
                else type_delay_ms
            )
            self._type_edit_text(
                value,
                delay=resolved_type_delay,
                timeout_seconds=timeout_seconds,
            )
        finally:
            self._restore_input_type(restore_type)
        self._pause_after_action()
        return self

    def select_text(
        self,
        text: str | None = None,
        *,
        start: int | None = None,
        end: int | None = None,
        occurrence: int = 1,
        drag: bool = True,
        steps: int = 12,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        """Select text in an input or textarea, optionally by mouse drag."""

        if highlight:
            self.highlight()
        value = str(self.locator.evaluate("element => String(element.value ?? '')"))
        resolved_start, resolved_end = self._resolve_text_selection(
            value,
            text=text,
            start=start,
            end=end,
            occurrence=occurrence,
        )

        if drag and resolved_start != resolved_end:
            self.smooth_scroll()
            points = self.locator.evaluate(
                """
                (element, args) => {
                    const value = String(element.value ?? '');
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    element.scrollIntoView({
                        behavior: 'smooth',
                        block: 'center',
                        inline: 'center',
                    });
                    element.focus();

                    const clamp = (number, min, max) => Math.min(Math.max(number, min), max);
                    const number = value => Number.parseFloat(value) || 0;
                    const font = style.font || [
                        style.fontStyle,
                        style.fontVariant,
                        style.fontWeight,
                        style.fontSize,
                        style.fontFamily,
                    ].filter(Boolean).join(' ');

                    const inputPoint = offset => {
                        const canvas = document.createElement('canvas');
                        const context = canvas.getContext('2d');
                        if (context) {
                            context.font = font;
                        }
                        const measured = context
                            ? context.measureText(value.slice(0, offset)).width
                            : 0;
                        const left = rect.left + number(style.borderLeftWidth) + number(style.paddingLeft);
                        const right = rect.right - number(style.borderRightWidth) - number(style.paddingRight);
                        const x = clamp(left + measured - element.scrollLeft, left, right);
                        return { x, y: rect.top + (rect.height / 2) };
                    };

                    const textareaPoint = offset => {
                        const mirror = document.createElement('div');
                        const span = document.createElement('span');
                        Object.assign(mirror.style, {
                            position: 'fixed',
                            left: `${rect.left}px`,
                            top: `${rect.top}px`,
                            width: `${rect.width}px`,
                            visibility: 'hidden',
                            whiteSpace: 'pre-wrap',
                            overflowWrap: 'break-word',
                            boxSizing: style.boxSizing,
                            font,
                            lineHeight: style.lineHeight,
                            letterSpacing: style.letterSpacing,
                            padding: style.padding,
                            border: style.border,
                        });
                        mirror.textContent = value.slice(0, offset);
                        span.textContent = '\\u200b';
                        mirror.appendChild(span);
                        document.body.appendChild(mirror);
                        const spanRect = span.getBoundingClientRect();
                        const point = {
                            x: clamp(spanRect.left, rect.left + 4, rect.right - 4),
                            y: clamp(spanRect.top + (spanRect.height / 2), rect.top + 4, rect.bottom - 4),
                        };
                        mirror.remove();
                        return point;
                    };

                    const pointFor = element instanceof HTMLTextAreaElement
                        ? textareaPoint
                        : inputPoint;
                    return {
                        from: pointFor(args.start),
                        to: pointFor(args.end),
                    };
                }
                """,
                {"start": resolved_start, "end": resolved_end},
            )
            mouse = self.recorder.current_page.mouse
            mouse.move(points["from"]["x"], points["from"]["y"])
            mouse.down()
            mouse.move(points["to"]["x"], points["to"]["y"], steps=max(1, steps))
            mouse.up()

        self.locator.evaluate(
            """
            (element, args) => {
                element.focus();
                if (typeof element.setSelectionRange === 'function') {
                    try {
                        element.setSelectionRange(args.start, args.end);
                    } catch {
                    }
                }
            }
            """,
            {"start": resolved_start, "end": resolved_end},
        )
        self._pause_after_action()
        return self

    def select_all(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight()
        self.locator.click(timeout=timeout_seconds * 1000)
        self.locator.press("ControlOrMeta+A", timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def clear_selection(
        self,
        *,
        key: Literal["Backspace", "Delete"] = "Backspace",
        timeout_seconds: float = 10.0,
    ) -> "WebInputElement":
        self.locator.evaluate("element => element.focus()")
        self.locator.press(key, timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def copy(self, *, timeout_seconds: float = 10.0) -> "WebInputElement":
        self.locator.evaluate("element => element.focus()")
        self.locator.press("ControlOrMeta+C", timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def cut(self, *, timeout_seconds: float = 10.0) -> "WebInputElement":
        self.locator.evaluate("element => element.focus()")
        self.locator.press("ControlOrMeta+X", timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def paste(
        self,
        text: str | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> "WebInputElement":
        self.locator.evaluate("element => element.focus()")
        if text is not None:
            self._write_clipboard_text(text)
        self.locator.press("ControlOrMeta+V", timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def select_clear(
        self,
        wait_seconds: float = 0.5,
        *,
        key: Literal["Backspace", "Delete"] = "Backspace",
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        self.select_all(timeout_seconds=timeout_seconds, highlight=highlight)
        self._wait_between_steps(wait_seconds)
        self.clear_selection(key=key, timeout_seconds=timeout_seconds)
        return self

    def select_paste(
        self,
        wait_seconds: float = 0.5,
        text: str | None = None,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        self.select_all(timeout_seconds=timeout_seconds, highlight=highlight)
        self._wait_between_steps(wait_seconds)
        self.paste(text, timeout_seconds=timeout_seconds)
        return self

    def select_clear_paste(
        self,
        wait_seconds: float = 0.5,
        text: str | None = None,
        *,
        key: Literal["Backspace", "Delete"] = "Backspace",
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        self.select_all(timeout_seconds=timeout_seconds, highlight=highlight)
        self._wait_between_steps(wait_seconds)
        self.clear_selection(key=key, timeout_seconds=timeout_seconds)
        self._wait_between_steps(wait_seconds)
        self.paste(text, timeout_seconds=timeout_seconds)
        return self

    def set_value(
        self,
        value: str | int | float,
        *,
        highlight: bool = True,
        duration_ms: int = 800,
    ) -> "WebInputElement":
        """Set a control value and emit input/change events.

        This is useful for controls such as ``input[type=range]`` that do not
        behave like text fields but still expose a value. Range inputs are
        animated so the recorded video shows the thumb moving.
        """

        if highlight:
            self.highlight()
        self.locator.evaluate(
            """
            async (element, args) => {
                const dispatch = name => {
                    element.dispatchEvent(new Event(name, { bubbles: true }));
                };
                const finalValue = String(args.value);

                if (
                    element instanceof HTMLInputElement
                    && element.type === 'range'
                    && args.duration > 0
                ) {
                    const start = Number(element.value || element.min || 0);
                    const end = Number(finalValue);
                    const duration = Number(args.duration);
                    const startedAt = performance.now();

                    await new Promise(resolve => {
                        const step = now => {
                            const progress = Math.min((now - startedAt) / duration, 1);
                            const eased = 1 - Math.pow(1 - progress, 3);
                            const next = start + ((end - start) * eased);
                            element.value = String(next);
                            dispatch('input');
                            if (progress < 1) {
                                requestAnimationFrame(step);
                            } else {
                                element.value = finalValue;
                                dispatch('input');
                                resolve();
                            }
                        };
                        requestAnimationFrame(step);
                    });
                    dispatch('change');
                    return;
                }

                element.value = finalValue;
                dispatch('input');
                dispatch('change');
            }
            """,
            {"value": value, "duration": duration_ms},
        )
        self._pause_after_action()
        return self

    @staticmethod
    def _diff_text_edits(current: str, target: str) -> list[tuple[int, int, str]]:
        return [
            (i1, i2, target[j1:j2])
            for tag, i1, i2, j1, j2 in SequenceMatcher(
                a=current,
                b=target,
                autojunk=False,
            ).get_opcodes()
            if tag != "equal"
        ]

    def _move_caret(
        self,
        position: int,
        *,
        current_length: int,
        timeout_seconds: float,
    ) -> str | None:
        result = self.locator.evaluate(
            """
            (element, args) => {
                element.focus();
                const setPosition = () => {
                    if (typeof element.setSelectionRange !== 'function') {
                        return false;
                    }
                    try {
                        element.setSelectionRange(args.position, args.position);
                        return true;
                    } catch {
                        return false;
                    }
                };

                if (setPosition()) {
                    return { moved: true, restoreType: null };
                }

                if (element instanceof HTMLInputElement) {
                    const originalType = element.type;
                    try {
                        element.type = 'text';
                        if (setPosition()) {
                            return { moved: true, restoreType: originalType };
                        }
                    } catch {
                    }
                    try {
                        element.type = originalType;
                    } catch {
                    }
                }

                return { moved: false, restoreType: null };
            }
            """,
            {"position": position},
        )
        if isinstance(result, dict) and result.get("moved"):
            restore_type = result.get("restoreType")
            return str(restore_type) if restore_type else None

        self.locator.press("ControlOrMeta+ArrowRight", timeout=timeout_seconds * 1000)
        self.locator.press("End", timeout=timeout_seconds * 1000)
        for _ in range(max(current_length - position, 0)):
            self.locator.press("ArrowLeft", timeout=timeout_seconds * 1000)
        return None

    def _press_edit_key(self, key: str, *, timeout_seconds: float) -> None:
        if self.recorder.page is not None:
            del timeout_seconds
            self.recorder.current_page.keyboard.press(key)
            return
        self.locator.press(key, timeout=timeout_seconds * 1000)

    def _type_edit_text(
        self,
        text: str,
        *,
        delay: float,
        timeout_seconds: float,
    ) -> None:
        if self.recorder.page is not None:
            del timeout_seconds
            self.recorder.current_page.keyboard.type(text, delay=delay)
            return
        self.locator.type(text, delay=delay, timeout=timeout_seconds * 1000)

    def _restore_input_type(self, input_type: str | None) -> None:
        if input_type is None:
            return
        self.recorder.current_page.evaluate(
            """
            inputType => {
                const element = document.activeElement;
                if (element instanceof HTMLInputElement) {
                    element.type = inputType;
                }
            }
            """,
            input_type,
        )

    def _wait_between_steps(self, seconds: float) -> None:
        if seconds > 0:
            self.recorder.wait(seconds)

    @staticmethod
    def _resolve_text_selection(
        value: str,
        *,
        text: str | None,
        start: int | None,
        end: int | None,
        occurrence: int,
    ) -> tuple[int, int]:
        if text is not None:
            if occurrence < 1:
                raise ValueError("occurrence must be 1 or greater.")
            offset = -1
            search_from = 0
            for _ in range(occurrence):
                offset = value.find(text, search_from)
                if offset == -1:
                    raise RecordingError(
                        f"Could not find text {text!r} in the input value."
                    )
                search_from = offset + len(text)
            return offset, offset + len(text)

        value_length = len(value)
        resolved_start = 0 if start is None else start
        resolved_end = value_length if end is None else end
        resolved_start = min(max(resolved_start, 0), value_length)
        resolved_end = min(max(resolved_end, 0), value_length)
        if resolved_start > resolved_end:
            resolved_start, resolved_end = resolved_end, resolved_start
        return resolved_start, resolved_end

    def _write_clipboard_text(self, text: str) -> None:
        self.recorder.write_clipboard_text(text)

    def set_range(
        self,
        value: str | int | float,
        *,
        duration_ms: int = 800,
        highlight: bool = True,
    ) -> "WebInputElement":
        """Set an ``input[type=range]`` value with visible thumb movement."""

        return self.set_value(value, highlight=highlight, duration_ms=duration_ms)

    def set_date(
        self,
        value: str,
        *,
        preview_ms: int = 1800,
        highlight: bool = True,
    ) -> "WebInputElement":
        """Set a date input while briefly showing a recorder-friendly calendar."""

        if highlight:
            self.highlight()
        self.locator.evaluate(
            """
            async (element, args) => {
                const targetDate = new Date(`${args.value}T12:00:00`);
                if (Number.isNaN(targetDate.getTime())) {
                    return;
                }

                const currentDate = element.value
                    ? new Date(`${element.value}T12:00:00`)
                    : targetDate;
                const startDate = Number.isNaN(currentDate.getTime())
                    ? targetDate
                    : currentDate;
                const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
                const stepDelay = Math.max(260, Math.round(args.preview / 4));
                const clickDelay = Math.max(180, Math.round(stepDelay * 0.55));
                const monthNames = Array.from({ length: 12 }, (_, index) => (
                    new Date(2024, index, 1).toLocaleString(undefined, { month: 'short' })
                ));
                const weekdays = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

                const overlay = document.createElement('div');
                overlay.setAttribute('data-demo-recorder-picker', 'date');
                const rect = element.getBoundingClientRect();
                Object.assign(overlay.style, {
                    position: 'fixed',
                    left: `${Math.min(rect.left, window.innerWidth - 308)}px`,
                    top: `${Math.min(rect.bottom + 8, window.innerHeight - 328)}px`,
                    zIndex: '2147483647',
                    width: '300px',
                    padding: '14px',
                    border: '1px solid #9fb2c4',
                    borderRadius: '8px',
                    background: '#ffffff',
                    color: '#17212c',
                    boxShadow: '0 18px 48px rgba(30, 47, 64, 0.24)',
                    font: '13px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
                });
                document.body.appendChild(overlay);

                const cellStyle = (active, target) => `
                    display:grid;place-items:center;height:32px;border-radius:6px;
                    border:${target ? '3px solid #ffbf00' : '1px solid transparent'};
                    ${active ? 'background:#1f6f8b;color:white;font-weight:760;' : ''}
                    ${target ? 'box-shadow:0 0 0 3px rgba(255,191,0,.25);font-weight:760;' : ''}
                `;
                const cursor = '<span style="position:absolute;right:6px;bottom:5px;width:12px;height:12px;border-radius:999px;background:#17212c;box-shadow:0 0 0 4px rgba(23,33,44,.14);"></span>';
                const wrapTarget = (content, active, target) => `
                    <span style="position:relative;${cellStyle(active, target)}">
                        ${content}${target ? cursor : ''}
                    </span>
                `;

                const renderYears = targetActive => {
                    const currentYear = startDate.getFullYear();
                    const targetYear = targetDate.getFullYear();
                    const firstYear = Math.min(currentYear, targetYear) - 3;
                    const years = Array.from({ length: 12 }, (_, index) => firstYear + index);
                    overlay.innerHTML = `
                        <div style="font-weight:760;margin-bottom:10px;">Year</div>
                        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:7px;text-align:center;">
                            ${years.map(year => wrapTarget(
                                year,
                                year === currentYear && !targetActive,
                                targetActive && year === targetYear,
                            )).join('')}
                        </div>
                    `;
                };

                const renderMonths = targetActive => {
                    const currentMonth = startDate.getMonth();
                    const targetMonth = targetDate.getMonth();
                    overlay.innerHTML = `
                        <div style="font-weight:760;margin-bottom:10px;">${targetDate.getFullYear()}</div>
                        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:7px;text-align:center;">
                            ${monthNames.map((month, index) => wrapTarget(
                                month,
                                index === currentMonth && !targetActive,
                                targetActive && index === targetMonth,
                            )).join('')}
                        </div>
                    `;
                };

                const renderDays = targetActive => {
                    const viewDate = targetActive ? targetDate : startDate;
                    const first = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
                    const days = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 0).getDate();
                    const cells = [];
                    for (let i = 0; i < first.getDay(); i += 1) {
                        cells.push('<span></span>');
                    }
                    for (let day = 1; day <= days; day += 1) {
                        const isCurrent = (
                            viewDate.getFullYear() === startDate.getFullYear()
                            && viewDate.getMonth() === startDate.getMonth()
                            && day === startDate.getDate()
                        );
                        const isTarget = day === targetDate.getDate();
                        cells.push(wrapTarget(day, isCurrent && !targetActive, targetActive && isTarget));
                    }
                    overlay.innerHTML = `
                        <div style="font-weight:760;margin-bottom:10px;">
                            ${viewDate.toLocaleString(undefined, { month: 'long', year: 'numeric' })}
                        </div>
                        <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;color:#536270;margin-bottom:5px;text-align:center;font-weight:700;">
                            ${weekdays.map(day => `<span>${day}</span>`).join('')}
                        </div>
                        <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center;">
                            ${cells.join('')}
                        </div>
                    `;
                };

                if (startDate.getFullYear() !== targetDate.getFullYear()) {
                    renderYears(false);
                    await wait(stepDelay);
                    renderYears(true);
                    await wait(clickDelay);
                }
                if (
                    startDate.getFullYear() !== targetDate.getFullYear()
                    || startDate.getMonth() !== targetDate.getMonth()
                ) {
                    renderMonths(false);
                    await wait(stepDelay);
                    renderMonths(true);
                    await wait(clickDelay);
                }

                renderDays(false);
                await wait(stepDelay);
                renderDays(true);
                await wait(clickDelay);
                overlay.remove();
            }
            """,
            {"value": value, "preview": preview_ms},
        )
        self.set_value(value, highlight=False, duration_ms=0)
        return self

    def set_color(
        self,
        value: str,
        *,
        preview_ms: int = 1100,
        highlight: bool = True,
    ) -> "WebInputElement":
        """Set a color input while briefly showing a color chooser preview."""

        if highlight:
            self.highlight()
        self.locator.evaluate(
            """
            async (element, args) => {
                const targetColor = String(args.value).toLowerCase();
                const currentColor = String(element.value || '').toLowerCase();
                const rect = element.getBoundingClientRect();
                const swatches = Array.from(new Set([
                    '#1f6f8b', '#146348', '#f7c767', '#c94f4f',
                    '#725ac1', '#17212c', '#ffffff', currentColor, targetColor,
                ].filter(Boolean)));
                const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
                const overlay = document.createElement('div');
                overlay.setAttribute('data-demo-recorder-picker', 'color');
                Object.assign(overlay.style, {
                    position: 'fixed',
                    left: `${Math.min(rect.left, window.innerWidth - 238)}px`,
                    top: `${Math.min(rect.bottom + 8, window.innerHeight - 176)}px`,
                    zIndex: '2147483647',
                    width: '230px',
                    padding: '14px',
                    border: '1px solid #9fb2c4',
                    borderRadius: '8px',
                    background: '#ffffff',
                    color: '#17212c',
                    boxShadow: '0 18px 48px rgba(30, 47, 64, 0.24)',
                    font: '13px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
                });
                const render = targetActive => {
                    overlay.innerHTML = `
                        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
                            <span style="display:block;width:34px;height:34px;border-radius:7px;border:1px solid #9fb2c4;background:${targetActive ? targetColor : currentColor};"></span>
                            <strong>${targetActive ? targetColor : currentColor}</strong>
                        </div>
                        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
                            ${swatches.map(color => {
                                const isCurrent = color.toLowerCase() === currentColor;
                                const isTarget = color.toLowerCase() === targetColor;
                                return `
                                    <span style="
                                        position:relative;display:block;height:32px;border-radius:7px;background:${color};
                                        border:${targetActive && isTarget ? '3px solid #ffbf00' : isCurrent && !targetActive ? '3px solid #1f6f8b' : '1px solid #9fb2c4'};
                                        box-shadow:${targetActive && isTarget ? '0 0 0 3px rgba(255,191,0,.25)' : 'none'};
                                    ">${targetActive && isTarget ? '<span style="position:absolute;right:4px;bottom:4px;width:10px;height:10px;border-radius:999px;background:#17212c;box-shadow:0 0 0 4px rgba(23,33,44,.14);"></span>' : ''}</span>
                                `;
                            }).join('')}
                        </div>
                    `;
                };
                document.body.appendChild(overlay);
                render(false);
                await wait(Math.max(250, Math.round(args.preview * 0.45)));
                render(true);
                await wait(Math.max(250, Math.round(args.preview * 0.55)));
                overlay.remove();
            }
            """,
            {"value": value, "preview": preview_ms},
        )
        self.set_value(value, highlight=False, duration_ms=0)
        return self

    def set_files(
        self,
        files: str | Path | Sequence[str | Path],
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        """Attach one or more files to an ``input[type=file]`` control."""

        if highlight:
            self.highlight()
        resolved: str | list[str]
        if isinstance(files, (str, Path)):
            resolved = str(files)
        else:
            resolved = [str(path) for path in files]
        self.locator.set_input_files(resolved, timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def press(self, key: str, *, timeout_seconds: float = 10.0) -> "WebInputElement":
        self.locator.press(key, timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def check(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight(scope="field")
        self.locator.check(timeout=timeout_seconds * 1000)
        self._pause_after_action()
        return self

    def uncheck(
        self,
        *,
        timeout_seconds: float = 10.0,
        highlight: bool = True,
    ) -> "WebInputElement":
        if highlight:
            self.highlight(scope="field")
        self.locator.uncheck(timeout=timeout_seconds * 1000)
        self._pause_after_action()
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
        self._pause_after_action()
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
        self._show_options(value=value, label=label, index=index)
        self.locator.select_option(
            value=value,
            label=label,
            index=index,
            timeout=timeout_seconds * 1000,
        )
        self._pause_after_action()
        return self

    def _show_options(
        self,
        *,
        value: str | Sequence[str] | None,
        label: str | Sequence[str] | None,
        index: int | Sequence[int] | None,
        preview_ms: int = 900,
    ) -> None:
        self.locator.evaluate(
            """
            async (element, args) => {
                const first = candidate => Array.isArray(candidate) ? candidate[0] : candidate;
                const target = {
                    value: first(args.value),
                    label: first(args.label),
                    index: first(args.index),
                };
                const options = Array.from(element.options);
                const targetIndex = options.findIndex((option, optionIndex) => {
                    if (target.index !== null && target.index !== undefined) {
                        return optionIndex === Number(target.index);
                    }
                    if (target.label !== null && target.label !== undefined) {
                        return option.label === String(target.label) || option.text === String(target.label);
                    }
                    if (target.value !== null && target.value !== undefined) {
                        return option.value === String(target.value);
                    }
                    return option.selected;
                });
                const currentIndex = Math.max(options.findIndex(option => option.selected), 0);
                const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
                const rect = element.getBoundingClientRect();
                const overlay = document.createElement('div');
                overlay.setAttribute('data-demo-recorder-picker', 'select');
                Object.assign(overlay.style, {
                    position: 'fixed',
                    left: `${rect.left}px`,
                    top: `${Math.min(rect.bottom + 6, window.innerHeight - 220)}px`,
                    zIndex: '2147483647',
                    minWidth: `${Math.max(rect.width, 220)}px`,
                    maxWidth: '360px',
                    maxHeight: '212px',
                    overflow: 'hidden',
                    border: '1px solid #9fb2c4',
                    borderRadius: '8px',
                    background: '#ffffff',
                    color: '#17212c',
                    boxShadow: '0 18px 48px rgba(30, 47, 64, 0.24)',
                    font: '14px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
                });
                const render = targetActive => {
                    overlay.innerHTML = options.map((option, optionIndex) => {
                        const isCurrent = optionIndex === currentIndex;
                        const isTarget = optionIndex === targetIndex;
                        return `
                            <div style="
                                position:relative;
                                padding:9px 12px;
                                border-bottom:${optionIndex === options.length - 1 ? '0' : '1px solid #dbe4ec'};
                                outline:${targetActive && isTarget ? '3px solid #ffbf00' : '0'};
                                outline-offset:-3px;
                                ${!targetActive && isCurrent ? 'background:#1f6f8b;color:white;font-weight:760;' : ''}
                                ${targetActive && isTarget ? 'background:#eaf5fb;color:#17212c;font-weight:760;' : ''}
                            ">
                                ${option.text}
                                ${targetActive && isTarget ? '<span style="position:absolute;right:10px;top:50%;width:11px;height:11px;transform:translateY(-50%);border-radius:999px;background:#17212c;box-shadow:0 0 0 4px rgba(23,33,44,.14);"></span>' : ''}
                            </div>
                        `;
                    }).join('');
                };
                document.body.appendChild(overlay);
                render(false);
                await wait(Math.max(250, Math.round(args.preview * 0.45)));
                render(true);
                await wait(Math.max(250, Math.round(args.preview * 0.55)));
                overlay.remove();
            }
            """,
            {
                "value": value,
                "label": label,
                "index": index,
                "preview": preview_ms,
            },
        )


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
        self._pause_after_action()
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
        scroll_duration_ms: int = 450,
        action_pause_seconds: float = 0.0,
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
        self.scroll_duration_ms = scroll_duration_ms
        self.action_pause_seconds = action_pause_seconds
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

    def pause(self, seconds: float | None = None) -> "WebUIRecorder":
        """Pause between visible browser actions."""

        resolved_seconds = self.action_pause_seconds if seconds is None else seconds
        if resolved_seconds > 0:
            self.wait(resolved_seconds)
        return self

    def element(self, locator: Locator) -> WebElement:
        """Wrap a Playwright locator so custom selectors still use recorder actions."""

        return self._wrap_element(locator.first)

    def write_clipboard_text(self, text: str) -> "WebUIRecorder":
        """Write browser clipboard text without selecting any page content."""

        page = self.current_page
        parsed = urlparse(page.url)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            try:
                page.context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin=origin,
                )
            except Exception:
                pass
        try:
            page.evaluate("text => navigator.clipboard.writeText(text)", text)
        except Exception as exc:
            raise RecordingError(
                "Could not write text to the browser clipboard."
            ) from exc
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
