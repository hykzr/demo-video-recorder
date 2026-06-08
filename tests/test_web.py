from __future__ import annotations

import re
from urllib.request import urlopen

from demo_video_recorder.backends import PlaywrightVideoCaptureBackend
from demo_video_recorder.web import (
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
    ) -> None:
        self.selector = selector
        self.tag = tag
        self.items = items
        self.text_filter: str | re.Pattern[str] | None = None
        self.wait_state: str | None = None
        self.wait_timeout: float | None = None

    @property
    def first(self) -> "FakeLocator":
        if self.items:
            return self.items[0]
        return self

    def wait_for(self, *, state: str, timeout: float) -> None:
        self.wait_state = state
        self.wait_timeout = timeout

    def evaluate(self, script: str, *args: object) -> str | None:
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


def test_webui_recorder_uses_playwright_video_backend_by_default(tmp_path) -> None:
    recorder = WebUIRecorder(
        tmp_path / "demo.mp4",
        typed_character_delay=0.025,
        command_lead_seconds=1.0,
    )

    assert isinstance(recorder.capture, PlaywrightVideoCaptureBackend)
    assert recorder.typed_character_delay == 0.025
    assert recorder.command_lead_seconds == 1.0


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
