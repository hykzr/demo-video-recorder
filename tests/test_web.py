from __future__ import annotations

from pathlib import Path
import re
from urllib.request import urlopen

import pytest

from demo_video_recorder.backends import PlaywrightVideoCaptureBackend
from demo_video_recorder.errors import RecordingError
from demo_video_recorder.web import (
    WebElement,
    WebInputElement,
    WebSelectElement,
    WebUIRecorder,
    _combine_css_selectors,
    _css_selector_from_find_args,
)


class FakeLocator:
    def __init__(
        self,
        selector: str = "*",
        *,
        tag: str = "input",
        items: list["FakeLocator"] | None = None,
        value: str = "",
    ) -> None:
        self.selector = selector
        self.tag = tag
        self.items = items
        self.value = value
        self.caret_position = len(value)
        self.selection_start: int | None = None
        self.selection_end: int | None = None
        self.text_filter: str | re.Pattern[str] | None = None
        self.wait_state: str | None = None
        self.wait_timeout: float | None = None
        self.evaluate_calls: list[tuple[str, object | None]] = []
        self.clicks = 0
        self.pressed_keys: list[str] = []
        self.typed_text: list[str] = []
        self.checked = False
        self.unchecked = False
        self.selected_options: dict[str, object] | None = None
        self.input_files: str | list[str] | None = None

    @property
    def first(self) -> "FakeLocator":
        if self.items:
            return self.items[0]
        return self

    def wait_for(self, *, state: str, timeout: float) -> None:
        self.wait_state = state
        self.wait_timeout = timeout

    def inner_text(self, *, timeout: float) -> str:
        del timeout
        return self.value

    def get_attribute(self, name: str, *, timeout: float) -> str | None:
        del name, timeout
        return None

    def evaluate(self, script: str, *args: object) -> str | None:
        self.evaluate_calls.append((script, args[0] if args else None))
        if args and isinstance(args[0], dict):
            arg = args[0]
            if "position" in arg:
                self.caret_position = int(arg["position"])
                self.selection_start = self.caret_position
                self.selection_end = self.caret_position
                return {"moved": True, "restoreType": None}  # type: ignore[return-value]
            if "start" in arg and "end" in arg:
                self.selection_start = int(arg["start"])
                self.selection_end = int(arg["end"])
                self.caret_position = self.selection_end
                return None
        if "String(element.value" in script and "return value.length" in script:
            return str(len(self.value))
        if "String(element.value" in script:
            return self.value
        if "tagName" in script:
            return self.tag
        return None

    def filter(self, *, has_text: str | re.Pattern[str]) -> "FakeLocator":
        self.text_filter = has_text
        return self

    def and_(self, other: "FakeLocator") -> "FakeLocator":
        self.selector = f"{self.selector} AND {other.selector}"
        return self

    def count(self) -> int:
        if self.items is None:
            return 1
        return len(self.items)

    def nth(self, index: int) -> "FakeLocator":
        if self.items is None:
            return self
        return self.items[index]

    def clear(self, *, timeout: float) -> None:
        del timeout
        self.value = ""
        self.caret_position = 0

    def type(self, text: str, *, delay: float | None, timeout: float) -> None:
        del delay, timeout
        self.typed_text.append(text)
        self._replace_selection(text)

    def fill(self, value: str, *, timeout: float) -> None:
        del timeout
        self.value = value
        self.caret_position = len(value)
        self.selection_start = None
        self.selection_end = None

    def click(self, *, timeout: float, **kwargs: object) -> None:
        del timeout, kwargs
        self.clicks += 1
        self.selection_start = None
        self.selection_end = None

    def press(self, key: str, *, timeout: float) -> None:
        del timeout
        self.pressed_keys.append(key)
        if key == "ControlOrMeta+A":
            self.selection_start = 0
            self.selection_end = len(self.value)
            self.caret_position = self.selection_end
        elif key == "Backspace":
            if self._has_selection():
                self._replace_selection("")
            elif self.caret_position > 0:
                self.value = (
                    self.value[: self.caret_position - 1]
                    + self.value[self.caret_position :]
                )
                self.caret_position -= 1
        elif key == "Delete":
            if self._has_selection():
                self._replace_selection("")
            elif self.caret_position < len(self.value):
                self.value = (
                    self.value[: self.caret_position]
                    + self.value[self.caret_position + 1 :]
                )
        elif key == "End":
            self.caret_position = len(self.value)
            self.selection_start = None
            self.selection_end = None
        elif key == "ArrowLeft":
            self.caret_position = max(self.caret_position - 1, 0)
            self.selection_start = None
            self.selection_end = None

    def _has_selection(self) -> bool:
        return (
            self.selection_start is not None
            and self.selection_end is not None
            and self.selection_start != self.selection_end
        )

    def _replace_selection(self, text: str) -> None:
        if self._has_selection():
            start = min(self.selection_start or 0, self.selection_end or 0)
            end = max(self.selection_start or 0, self.selection_end or 0)
        else:
            start = self.caret_position
            end = self.caret_position
        self.value = self.value[:start] + text + self.value[end:]
        self.caret_position = start + len(text)
        self.selection_start = None
        self.selection_end = None

    def check(self, *, timeout: float) -> None:
        del timeout
        self.checked = True

    def uncheck(self, *, timeout: float) -> None:
        del timeout
        self.unchecked = True

    def select_option(
        self,
        *,
        value: object = None,
        label: object = None,
        index: object = None,
        timeout: float,
    ) -> None:
        self.selected_options = {
            "value": value,
            "label": label,
            "index": index,
            "timeout": timeout,
        }

    def set_input_files(self, files: str | list[str], *, timeout: float) -> None:
        del timeout
        self.input_files = files


class FakeScope:
    def __init__(self) -> None:
        self.selectors: list[str] = []
        self.role_calls: list[tuple[str, object]] = []
        self.label_calls: list[str] = []

    def locator(self, selector: str) -> FakeLocator:
        self.selectors.append(selector)
        if "select" in selector and "input, textarea" not in selector:
            return FakeLocator(selector, tag="select")
        if "input, textarea" in selector:
            return FakeLocator(
                selector,
                items=[
                    FakeLocator(f"{selector} >> nth=0", tag="input"),
                    FakeLocator(f"{selector} >> nth=1", tag="textarea"),
                ],
            )
        return FakeLocator(selector, tag="button")

    def get_by_role(self, role: str, *, name: object = None) -> FakeLocator:
        self.role_calls.append((role, name))
        return FakeLocator(f"role={role!r}, name={name!r}", tag="button")

    def get_by_label(self, label: str) -> FakeLocator:
        self.label_calls.append(label)
        return FakeLocator(f"label={label!r}", tag="input")

    def get_by_placeholder(self, placeholder: str) -> FakeLocator:
        return FakeLocator(f"placeholder={placeholder!r}", tag="input")

    def get_by_test_id(self, test_id: str) -> FakeLocator:
        return FakeLocator(f"test_id={test_id!r}", tag="input")

    def get_by_title(self, title: str) -> FakeLocator:
        return FakeLocator(f"title={title!r}", tag="input")


def test_css_selector_from_find_args_supports_bs4_style_attrs() -> None:
    selector = _css_selector_from_find_args(
        "button",
        {
            "data_testid": "save.primary",
            "aria_label": 'Save "now"',
            "disabled": True,
            "hidden": False,
            "class_": "primary",
            "_class": "action",
        },
    )

    assert selector == (
        'button[data-testid="save.primary"]'
        '[aria-label="Save \\"now\\""]'
        "[disabled]"
        '[class~="primary"]'
        '[class~="action"]'
    )


def test_combine_css_selectors_intersects_typed_and_user_selectors() -> None:
    assert _combine_css_selectors(None, "button.primary") == "button.primary"
    assert _combine_css_selectors("input, textarea", "*") == "input, textarea"
    assert (
        _combine_css_selectors("input, textarea", '*[class~="field"]')
        == ':is(input, textarea):is(*[class~="field"])'
    )


def test_locator_for_supports_multiple_attrs_and_text_filter(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    scope = FakeScope()
    text = re.compile("Save")

    locator = recorder._locator_for(
        scope,
        "button",
        {"data_testid": "save"},
        text=text,
        _class="primary",
    )

    assert scope.selectors == [
        'button[data-testid="save"][class~="primary"]',
    ]
    assert locator.text_filter is text


def test_locator_for_intersects_role_label_attrs_and_text(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    role_scope = FakeScope()
    role_locator = recorder._locator_for(
        role_scope,
        role="button",
        name="Save",
        _class="primary",
        text="Save changes",
    )

    assert role_scope.role_calls == [("button", "Save")]
    assert role_scope.selectors == ['*[class~="primary"]']
    assert role_locator.selector == (
        "role='button', name='Save' AND " '*[class~="primary"]'
    )
    assert role_locator.text_filter == "Save changes"

    label_scope = FakeScope()
    label_locator = recorder._locator_for(
        label_scope,
        label="Email address",
        type="email",
    )

    assert label_scope.label_calls == ["Email address"]
    assert label_scope.selectors == ['*[type="email"]']
    assert label_locator.selector == "label='Email address' AND " '*[type="email"]'


def test_find_input_and_find_select_return_typed_elements(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    scope = FakeScope()

    text_input = recorder._find_input_in_scope(scope, _class="field", text="Email")
    select = recorder._find_select_in_scope(scope, attrs={"name": "salary_tier"})

    assert isinstance(text_input, WebInputElement)
    assert not isinstance(text_input, WebSelectElement)
    assert isinstance(select, WebSelectElement)
    assert scope.selectors == [
        ':is(input, textarea):is(*[class~="field"])',
        ':is(select):is(*[name="salary_tier"])',
    ]


def test_find_all_input_and_find_all_select_return_typed_lists(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    scope = FakeScope()

    inputs = recorder._find_all_input_in_scope(scope)
    selects = recorder._find_all_select_in_scope(scope)

    assert len(inputs) == 2
    assert all(isinstance(item, WebInputElement) for item in inputs)
    assert all(not isinstance(item, WebSelectElement) for item in inputs)
    assert len(selects) == 1
    assert isinstance(selects[0], WebSelectElement)


def test_check_and_uncheck_highlight_the_containing_field(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    locator = FakeLocator("input[type=checkbox]", tag="input")
    element = WebInputElement(recorder, locator)

    element.check()
    element.uncheck()

    highlight_args = [
        args for script, args in locator.evaluate_calls if "scrollIntoView" in script
    ]
    assert highlight_args == [
        {"duration": 700, "scrollDuration": 450, "scope": "field"},
        {"duration": 700, "scrollDuration": 450, "scope": "field"},
    ]
    assert locator.checked is True
    assert locator.unchecked is True


def test_set_value_animates_range_inputs(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    locator = FakeLocator("input[type=range]", tag="input")
    element = WebInputElement(recorder, locator)

    element.set_range(8, duration_ms=425)

    assert locator.evaluate_calls[-1][1] == {"value": 8, "duration": 425}


def test_date_color_and_file_input_actions_have_visible_steps(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    locator = FakeLocator("input[type=date]", tag="input")
    element = WebInputElement(recorder, locator)

    element.set_date("1991-08-14", preview_ms=321)
    element.set_color("#146348", preview_ms=654)
    element.set_files([Path("resume.pdf"), "photo.png"])

    args = [call_args for _script, call_args in locator.evaluate_calls]
    assert {"value": "1991-08-14", "preview": 321} in args
    assert {"value": "#146348", "preview": 654} in args
    assert {"value": "1991-08-14", "duration": 0} in args
    assert {"value": "#146348", "duration": 0} in args
    assert locator.input_files == ["resume.pdf", "photo.png"]


def test_edit_text_backspaces_existing_value_then_types_replacement(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4", typed_character_delay=0)
    locator = FakeLocator(
        "input[type=email]",
        tag="input",
        value="maya.chen@example.com",
    )
    element = WebInputElement(recorder, locator)

    assert (
        element.edit_text(
            "maya.chen+intake@example.com",
            backspace_delay_ms=0,
            type_delay_ms=0,
        )
        is element
    )

    assert locator.clicks == 1
    assert locator.pressed_keys == []
    assert locator.typed_text == ["+intake"]
    assert locator.value == "maya.chen+intake@example.com"


def test_edit_text_applies_separate_small_edits_from_right_to_left(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4", typed_character_delay=0)
    locator = FakeLocator("input", tag="input", value="hellow wald")
    element = WebInputElement(recorder, locator)

    element.edit_text("hello world", backspace_delay_ms=0, type_delay_ms=0)

    assert locator.pressed_keys == ["Backspace", "Backspace"]
    assert locator.typed_text == ["or"]
    assert locator.value == "hello world"


def test_select_text_resolves_text_and_ranges_without_dragging(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    locator = FakeLocator(
        "textarea", tag="textarea", value="morning call, morning plan"
    )
    element = WebInputElement(recorder, locator)

    element.select_text("morning", occurrence=2, drag=False, highlight=False)
    element.select_text(start=15, end=7, drag=False, highlight=False)

    selection_args = [
        args
        for script, args in locator.evaluate_calls
        if "setSelectionRange(args.start, args.end)" in script
    ]
    assert selection_args == [
        {"start": 14, "end": 21},
        {"start": 7, "end": 15},
    ]


def test_select_text_raises_when_text_is_missing(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    locator = FakeLocator("input", tag="input", value="maya.chen@example.com")
    element = WebInputElement(recorder, locator)

    with pytest.raises(RecordingError):
        element.select_text("missing", drag=False, highlight=False)


def test_selection_and_clipboard_shortcuts_are_chainable(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    locator = FakeLocator("textarea", tag="textarea", value="notes")
    element = WebInputElement(recorder, locator)

    assert element.select_all(highlight=False) is element
    assert element.copy() is element
    assert element.cut() is element
    assert element.clear_selection(key="Delete") is element
    assert element.paste() is element

    assert locator.clicks == 1
    assert locator.pressed_keys == [
        "ControlOrMeta+A",
        "ControlOrMeta+C",
        "ControlOrMeta+X",
        "Delete",
        "ControlOrMeta+V",
    ]


def test_select_clear_paste_wraps_visible_steps_with_waits(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    waits: list[float] = []
    recorder.wait = lambda seconds: waits.append(seconds) or recorder  # type: ignore[method-assign]
    locator = FakeLocator("textarea", tag="textarea", value="notes")
    element = WebInputElement(recorder, locator)

    assert element.select_clear_paste(0.5, highlight=False) is element

    assert waits == [0.5, 0.5]
    assert locator.pressed_keys == [
        "ControlOrMeta+A",
        "ControlOrMeta+C",
        "Backspace",
        "ControlOrMeta+V",
    ]


def test_select_option_shows_options_before_selecting(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    locator = FakeLocator("select", tag="select")
    element = WebSelectElement(recorder, locator)

    element.select_option(label="$100,000 to $150,000")

    assert locator.evaluate_calls[-1][1] == {
        "value": None,
        "label": "$100,000 to $150,000",
        "index": None,
        "preview": 900,
    }
    assert locator.selected_options == {
        "value": None,
        "label": "$100,000 to $150,000",
        "index": None,
        "timeout": 10000.0,
    }


def test_webui_recorder_uses_playwright_video_backend_by_default(tmp_path) -> None:
    recorder = WebUIRecorder(
        tmp_path / "demo.mp4",
        typed_character_delay=0.025,
        command_lead_seconds=1.0,
        scroll_duration_ms=620,
        action_pause_seconds=0.125,
    )

    assert isinstance(recorder.capture, PlaywrightVideoCaptureBackend)
    assert recorder.typed_character_delay == 0.025
    assert recorder.command_lead_seconds == 1.0
    assert recorder.scroll_duration_ms == 620
    assert recorder.action_pause_seconds == 0.125


def test_web_actions_use_recorder_pause_when_configured(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4", action_pause_seconds=0.25)
    waits: list[float] = []
    recorder.wait = lambda seconds: waits.append(seconds) or recorder  # type: ignore[method-assign]

    WebInputElement(recorder, FakeLocator("input")).fill("hello", highlight=False)
    WebElement(recorder, FakeLocator("button", tag="button")).click(highlight=False)

    assert waits == [0.25, 0.25]


def test_web_element_copy_text_writes_clipboard_without_page_selection(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    copied: list[str] = []
    recorder.write_clipboard_text = lambda text: copied.append(text) or recorder  # type: ignore[method-assign]
    locator = FakeLocator("code", tag="code", value="1 1\n1 2\n1 3")
    element = WebElement(recorder, locator)

    assert element.copy_text(highlight=False) == "1 1\n1 2\n1 3"

    assert copied == ["1 1\n1 2\n1 3"]
    assert locator.pressed_keys == []


def test_webui_recorder_serves_static_folder(tmp_path) -> None:
    web_root = tmp_path / "site"
    web_root.mkdir()
    (web_root / "index.html").write_text("<h1>Hello web demo</h1>", encoding="utf-8")
    recorder = WebUIRecorder(tmp_path / "demo.mp4")

    try:
        url = recorder.serve(web_root, 0)
        body = urlopen(f"{url}/index.html", timeout=5).read().decode("utf-8")
    finally:
        recorder.close()

    assert body == "<h1>Hello web demo</h1>"


def test_webui_recorder_normalizes_urls(tmp_path) -> None:
    recorder = WebUIRecorder(tmp_path / "demo.mp4")
    recorder.served_url = "http://127.0.0.1:8000"

    assert recorder._normalize_url("example.com") == "https://example.com"
    assert recorder._normalize_url("localhost:3000") == "http://localhost:3000"
    assert recorder._normalize_url("/demo") == "http://127.0.0.1:8000/demo"
