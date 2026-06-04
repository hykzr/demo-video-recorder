"""macOS-specific helpers for permissions and display metrics."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import ctypes
import platform
import time

from demo_video_recorder.types import CaptureRegion

IS_MACOS = platform.system() == "Darwin"


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


@dataclass(frozen=True)
class ScreenRecordingAccessResult:
    granted: bool
    prompted: bool
    status: str


@lru_cache(maxsize=1)
def _core_graphics() -> ctypes.CDLL | None:
    if not IS_MACOS:
        return None

    library = ctypes.CDLL(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )
    library.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    library.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
    library.CGMainDisplayID.restype = ctypes.c_uint32
    library.CGGetActiveDisplayList.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    library.CGGetActiveDisplayList.restype = ctypes.c_int32
    library.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
    library.CGDisplayPixelsWide.restype = ctypes.c_size_t
    library.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    library.CGDisplayBounds.restype = CGRect
    library.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
    library.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
    library.CGDisplayModeGetPixelWidth.argtypes = [ctypes.c_void_p]
    library.CGDisplayModeGetPixelWidth.restype = ctypes.c_size_t
    library.CGDisplayModeGetWidth.argtypes = [ctypes.c_void_p]
    library.CGDisplayModeGetWidth.restype = ctypes.c_size_t
    return library


@lru_cache(maxsize=1)
def _core_foundation() -> ctypes.CDLL | None:
    if not IS_MACOS:
        return None

    library = ctypes.CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    library.CFRelease.argtypes = [ctypes.c_void_p]
    library.CFRelease.restype = None
    return library


def _display_mode_scale_factor(
    library: ctypes.CDLL,
    display_id: int,
) -> float:
    mode = library.CGDisplayCopyDisplayMode(display_id)
    if mode:
        try:
            points_wide = float(library.CGDisplayModeGetWidth(mode))
            pixels_wide = float(library.CGDisplayModeGetPixelWidth(mode))
            if points_wide > 0 and pixels_wide > 0:
                return max(pixels_wide / points_wide, 1.0)
        finally:
            foundation = _core_foundation()
            if foundation is not None:
                foundation.CFRelease(mode)

    bounds = library.CGDisplayBounds(display_id)
    if bounds.size.width <= 0:
        return 1.0

    pixels_wide = float(library.CGDisplayPixelsWide(display_id))
    return max(pixels_wide / float(bounds.size.width), 1.0)


def get_main_display_scale_factor() -> float:
    library = _core_graphics()
    if library is None:
        return 1.0

    return _display_mode_scale_factor(library, library.CGMainDisplayID())


def get_display_scale_factor_for_rect(
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> float:
    library = _core_graphics()
    if library is None:
        return 1.0

    best_display = _display_id_for_rect(library, left, top, right, bottom)
    return _display_mode_scale_factor(library, best_display)


def get_display_bounds_for_rect(
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> CaptureRegion | None:
    library = _core_graphics()
    if library is None:
        return None

    bounds = library.CGDisplayBounds(
        _display_id_for_rect(library, left, top, right, bottom)
    )
    return CaptureRegion(
        int(round(bounds.origin.x)),
        int(round(bounds.origin.y)),
        max(int(round(bounds.size.width)), 1),
        max(int(round(bounds.size.height)), 1),
    )


def _display_id_for_rect(
    library: ctypes.CDLL,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> int:
    max_displays = 32
    display_ids = (ctypes.c_uint32 * max_displays)()
    display_count = ctypes.c_uint32()
    error = library.CGGetActiveDisplayList(
        max_displays,
        display_ids,
        ctypes.byref(display_count),
    )
    if error != 0 or display_count.value <= 0:
        return int(library.CGMainDisplayID())

    best_display = int(library.CGMainDisplayID())
    best_overlap = -1.0
    for index in range(display_count.value):
        display_id = int(display_ids[index])
        bounds = library.CGDisplayBounds(display_id)
        overlap = _overlap_area(
            left,
            top,
            right,
            bottom,
            bounds.origin.x,
            bounds.origin.y,
            bounds.origin.x + bounds.size.width,
            bounds.origin.y + bounds.size.height,
        )
        if overlap > best_overlap:
            best_display = display_id
            best_overlap = overlap

    return best_display


def _overlap_area(
    left_a: float,
    top_a: float,
    right_a: float,
    bottom_a: float,
    left_b: float,
    top_b: float,
    right_b: float,
    bottom_b: float,
) -> float:
    width = min(right_a, right_b) - max(left_a, left_b)
    height = min(bottom_a, bottom_b) - max(top_a, top_b)
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


def screen_recording_access_granted() -> bool:
    library = _core_graphics()
    if library is None:
        return True
    return bool(library.CGPreflightScreenCaptureAccess())


def check_screen_recording_access(
    *,
    prompt: bool = True,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.25,
) -> ScreenRecordingAccessResult:
    if not IS_MACOS:
        return ScreenRecordingAccessResult(
            granted=True,
            prompted=False,
            status="not_macos",
        )

    library = _core_graphics()
    if library is None:
        return ScreenRecordingAccessResult(
            granted=False,
            prompted=False,
            status="unavailable",
        )

    if screen_recording_access_granted():
        return ScreenRecordingAccessResult(
            granted=True,
            prompted=False,
            status="granted",
        )

    prompted = False
    if prompt:
        prompted = True
        if bool(library.CGRequestScreenCaptureAccess()):
            return ScreenRecordingAccessResult(
                granted=True,
                prompted=True,
                status="granted",
            )

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if screen_recording_access_granted():
                return ScreenRecordingAccessResult(
                    granted=True,
                    prompted=True,
                    status="granted",
                )
            time.sleep(poll_interval_seconds)

    return ScreenRecordingAccessResult(
        granted=False,
        prompted=prompted,
        status="rejected",
    )
