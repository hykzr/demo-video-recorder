from __future__ import annotations

import demo_video_recorder.macos as macos
import demo_video_recorder.windowing as windowing


class _FakeCoreGraphics:
    def __init__(self, *, granted: bool, request_result: bool = False) -> None:
        self.granted = granted
        self.request_result = request_result
        self.request_calls = 0

    def CGPreflightScreenCaptureAccess(self) -> bool:
        return self.granted

    def CGRequestScreenCaptureAccess(self) -> bool:
        self.request_calls += 1
        self.granted = self.request_result
        return self.request_result


def test_check_screen_recording_access_returns_granted_without_prompt(
    monkeypatch,
) -> None:
    fake = _FakeCoreGraphics(granted=True)
    monkeypatch.setattr(macos, "IS_MACOS", True)
    monkeypatch.setattr(macos, "_core_graphics", lambda: fake)

    result = macos.check_screen_recording_access(prompt=True)

    assert result.granted is True
    assert result.prompted is False
    assert result.status == "granted"
    assert fake.request_calls == 0


def test_check_screen_recording_access_reports_rejected(monkeypatch) -> None:
    fake = _FakeCoreGraphics(granted=False, request_result=False)
    monkeypatch.setattr(macos, "IS_MACOS", True)
    monkeypatch.setattr(macos, "_core_graphics", lambda: fake)

    result = macos.check_screen_recording_access(
        prompt=True,
        timeout_seconds=0,
    )

    assert result.granted is False
    assert result.prompted is True
    assert result.status == "rejected"
    assert fake.request_calls == 1


def test_configure_current_console_reads_macos_terminal_bounds(monkeypatch) -> None:
    monkeypatch.setattr(windowing, "IS_MACOS", True)
    monkeypatch.setattr(windowing, "IS_WINDOWS", False)
    monkeypatch.setattr(windowing, "_macos_terminal_app_name", lambda: "Terminal")
    monkeypatch.setattr(windowing, "_activate_macos_console", lambda: None)
    monkeypatch.setattr(windowing, "_current_tty_path", lambda: "/dev/ttys123")
    monkeypatch.setattr(windowing, "get_display_scale_factor_for_rect", lambda *_: 2.0)

    def fake_osascript(lines: list[str]) -> str:
        script = "\n".join(lines)
        assert 'set targetTty to "/dev/ttys123"' in script
        return "Demo|10|20|410|320"

    monkeypatch.setattr(windowing, "_run_osascript", fake_osascript)

    window = windowing.configure_current_console(title="Demo")

    assert window is not None
    assert window.title == "Demo"
    assert window.region.left == 20
    assert window.region.top == 40
    assert window.region.width == 800
    assert window.region.height == 600


def test_configure_current_console_falls_back_to_title_match(monkeypatch) -> None:
    monkeypatch.setattr(windowing, "IS_MACOS", True)
    monkeypatch.setattr(windowing, "IS_WINDOWS", False)
    monkeypatch.setattr(windowing, "_macos_terminal_app_name", lambda: "Terminal")
    monkeypatch.setattr(windowing, "_activate_macos_console", lambda: None)
    monkeypatch.setattr(windowing, "_current_tty_path", lambda: None)
    monkeypatch.setattr(windowing, "get_display_scale_factor_for_rect", lambda *_: 2.0)

    def fake_osascript(lines: list[str]) -> str:
        script = "\n".join(lines)
        if 'set targetTitle to "Demo"' in script:
            return "Demo|10|20|410|320"
        return ""

    monkeypatch.setattr(windowing, "_run_osascript", fake_osascript)

    window = windowing.configure_current_console(title="Demo")

    assert window is not None
    assert window.title == "Demo"
    assert window.region.left == 20
    assert window.region.top == 40


def test_configure_current_console_applies_window_size_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(windowing, "IS_MACOS", True)
    monkeypatch.setattr(windowing, "IS_WINDOWS", False)
    monkeypatch.setattr(windowing, "_macos_terminal_app_name", lambda: "Terminal")
    monkeypatch.setattr(windowing, "_activate_macos_console", lambda: None)
    monkeypatch.setattr(windowing, "_current_tty_path", lambda: "/dev/ttys123")
    monkeypatch.setattr(windowing, "get_display_scale_factor_for_rect", lambda *_: 2.0)
    monkeypatch.setattr(
        windowing,
        "get_display_bounds_for_rect",
        lambda *_: windowing.CaptureRegion(0, 0, 960, 540),
    )

    scripts: list[str] = []
    current_output = "Demo|10|20|410|320"

    def fake_osascript(lines: list[str]) -> str:
        nonlocal current_output
        script = "\n".join(lines)
        scripts.append(script)
        if 'set bounds of aWindow to targetBounds' in script:
            assert "set targetBounds to {10, 20, 610, 420}" in script
            current_output = "Demo|10|20|610|420"
            return "ok"
        return current_output

    monkeypatch.setattr(windowing, "_run_osascript", fake_osascript)

    window = windowing.configure_current_console(
        title="Demo",
        window_size=(1200, 800),
    )

    assert window is not None
    assert window.region.width == 1200
    assert window.region.height == 800
    assert any("set targetBounds to {10, 20, 610, 420}" in script for script in scripts)


def test_configure_current_console_maximize_uses_display_bounds_on_macos(
    monkeypatch,
) -> None:
    monkeypatch.setattr(windowing, "IS_MACOS", True)
    monkeypatch.setattr(windowing, "IS_WINDOWS", False)
    monkeypatch.setattr(windowing, "_macos_terminal_app_name", lambda: "Terminal")
    monkeypatch.setattr(windowing, "_activate_macos_console", lambda: None)
    monkeypatch.setattr(windowing, "_current_tty_path", lambda: "/dev/ttys123")
    monkeypatch.setattr(windowing, "get_display_scale_factor_for_rect", lambda *_: 2.0)
    monkeypatch.setattr(
        windowing,
        "get_display_bounds_for_rect",
        lambda *_: windowing.CaptureRegion(0, 0, 960, 540),
    )

    captured: list[str] = []
    current_output = "Demo|10|20|410|320"

    def fake_osascript(lines: list[str]) -> str:
        nonlocal current_output
        script = "\n".join(lines)
        captured.append(script)
        if 'set bounds of aWindow to targetBounds' in script:
            assert "set targetBounds to {0, 0, 960, 540}" in script
            current_output = "Demo|0|0|960|540"
            return "ok"
        return current_output

    monkeypatch.setattr(windowing, "_run_osascript", fake_osascript)

    window = windowing.configure_current_console(title="Demo", maximize=True)

    assert window is not None
    assert window.region.width == 1920
    assert window.region.height == 1080
    assert any("set targetBounds to {0, 0, 960, 540}" in script for script in captured)


def test_get_main_display_scale_factor_uses_display_mode_pixels(monkeypatch) -> None:
    class _FakeGraphics:
        def CGMainDisplayID(self) -> int:
            return 7

        def CGDisplayCopyDisplayMode(self, display_id: int) -> int:
            assert display_id == 7
            return 123

        def CGDisplayModeGetPixelWidth(self, mode: int) -> int:
            assert mode == 123
            return 2560

        def CGDisplayModeGetWidth(self, mode: int) -> int:
            assert mode == 123
            return 1280

    class _FakeFoundation:
        def __init__(self) -> None:
            self.released: list[int] = []

        def CFRelease(self, value: int) -> None:
            self.released.append(value)

    graphics = _FakeGraphics()
    foundation = _FakeFoundation()
    monkeypatch.setattr(macos, "_core_graphics", lambda: graphics)
    monkeypatch.setattr(macos, "_core_foundation", lambda: foundation)

    assert macos.get_main_display_scale_factor() == 2.0
    assert foundation.released == [123]


def test_get_display_bounds_for_rect_uses_matching_display(monkeypatch) -> None:
    class _FakeGraphics:
        def CGMainDisplayID(self) -> int:
            return 1

        def CGGetActiveDisplayList(self, _max_displays, display_ids, display_count) -> int:
            display_ids[0] = 1
            display_ids[1] = 2
            display_count._obj.value = 2
            return 0

        def CGDisplayBounds(self, display_id: int):
            bounds = macos.CGRect()
            if display_id == 1:
                bounds.origin.x = 0
                bounds.origin.y = 0
                bounds.size.width = 1440
                bounds.size.height = 900
            else:
                bounds.origin.x = 1440
                bounds.origin.y = 0
                bounds.size.width = 1728
                bounds.size.height = 1117
            return bounds

    monkeypatch.setattr(macos, "_core_graphics", lambda: _FakeGraphics())

    bounds = macos.get_display_bounds_for_rect(1500, 50, 2000, 700)

    assert bounds == windowing.CaptureRegion(1440, 0, 1728, 1117)
