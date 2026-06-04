from __future__ import annotations

import demo_video_recorder.windowing as windowing
from demo_video_recorder import CaptureRegion


def test_fit_region_in_screen_repositions_offscreen_window() -> None:
    screen = CaptureRegion(0, 0, 1920, 1080)
    region = CaptureRegion(2500, -200, 900, 700)

    fitted = windowing.fit_region_in_screen(region, screen)

    assert fitted == CaptureRegion(1020, 0, 900, 700)


def test_fit_region_in_screen_applies_custom_window_size() -> None:
    screen = CaptureRegion(0, 0, 1920, 1080)
    region = CaptureRegion(1700, 900, 500, 400)

    fitted = windowing.fit_region_in_screen(region, screen, preferred_size=(800, 600))

    assert fitted == CaptureRegion(1120, 480, 800, 600)


def test_ensure_window_bounds_moves_window_back_onscreen(monkeypatch) -> None:
    calls: list[tuple[int, int, int, int]] = []

    monkeypatch.setattr(windowing, "IS_WINDOWS", True)
    monkeypatch.setattr(windowing, "get_virtual_screen_region", lambda: CaptureRegion(0, 0, 1920, 1080))
    monkeypatch.setattr(windowing, "get_window_region", lambda hwnd: CaptureRegion(2500, -200, 900, 700))

    class _FakeUser32:
        def SetWindowPos(self, hwnd, insert_after, left, top, width, height, flags):
            del hwnd, insert_after, flags
            calls.append((left, top, width, height))
            return True

    monkeypatch.setattr(windowing, "user32", _FakeUser32())

    windowing.ensure_window_bounds(123, window_size=(800, 600))

    assert calls == [(1120, 0, 800, 600)]
