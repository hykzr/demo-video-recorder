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
    monkeypatch.setattr(windowing, "get_main_display_scale_factor", lambda: 2.0)

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
    monkeypatch.setattr(windowing, "get_main_display_scale_factor", lambda: 2.0)

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
