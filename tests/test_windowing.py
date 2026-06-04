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
