from __future__ import annotations

from urllib.request import urlopen

from demo_video_recorder.backends import PlaywrightVideoCaptureBackend
from demo_video_recorder.web import WebUIRecorder, _css_selector_from_find_args


def test_css_selector_from_find_args_supports_bs4_style_attrs() -> None:
    selector = _css_selector_from_find_args(
        "button",
        {
            "data_testid": "save.primary",
            "aria_label": 'Save "now"',
            "disabled": True,
            "hidden": False,
            "class_": "primary",
        },
    )

    assert selector == (
        'button[data-testid="save.primary"]'
        '[aria-label="Save \\"now\\""]'
        "[disabled]"
        '[class="primary"]'
    )


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
