"""macOS-specific helpers for permissions and display metrics."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import ctypes
import platform
import time

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
    library.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
    library.CGDisplayPixelsWide.restype = ctypes.c_size_t
    library.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    library.CGDisplayBounds.restype = CGRect
    return library


def get_main_display_scale_factor() -> float:
    library = _core_graphics()
    if library is None:
        return 1.0

    display_id = library.CGMainDisplayID()
    bounds = library.CGDisplayBounds(display_id)
    if bounds.size.width <= 0:
        return 1.0

    pixels_wide = float(library.CGDisplayPixelsWide(display_id))
    return max(pixels_wide / float(bounds.size.width), 1.0)


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
