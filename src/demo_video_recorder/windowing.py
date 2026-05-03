"""Small Windows window-management helpers.

The public recorder does not depend on this module being available. On
non-Windows platforms these functions either return ``None`` or raise a clear
window lookup error, which keeps the backend replaceable later.
"""

from __future__ import annotations

from pathlib import Path
import ctypes
from ctypes import wintypes
import platform
import time

from demo_video_recorder.errors import WindowNotFoundError
from demo_video_recorder.types import CaptureRegion, WindowInfo


IS_WINDOWS = platform.system() == "Windows"


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    kernel32.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
    kernel32.SetConsoleTitleW.restype = wintypes.BOOL
else:
    RECT = object


def set_process_dpi_aware() -> None:
    """Use physical pixels for window bounds on Windows."""

    if not IS_WINDOWS:
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            return


def get_window_region(hwnd: int) -> CaptureRegion | None:
    if not IS_WINDOWS or not hwnd:
        return None

    rect = RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None

    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None
    return clamp_region_to_virtual_screen(CaptureRegion(int(rect.left), int(rect.top), width, height))


def get_virtual_screen_region() -> CaptureRegion | None:
    if not IS_WINDOWS:
        return None

    sm_xvirtualscreen = 76
    sm_yvirtualscreen = 77
    sm_cxvirtualscreen = 78
    sm_cyvirtualscreen = 79
    return CaptureRegion(
        user32.GetSystemMetrics(sm_xvirtualscreen),
        user32.GetSystemMetrics(sm_yvirtualscreen),
        user32.GetSystemMetrics(sm_cxvirtualscreen),
        user32.GetSystemMetrics(sm_cyvirtualscreen),
    )


def clamp_region_to_virtual_screen(region: CaptureRegion) -> CaptureRegion:
    screen = get_virtual_screen_region()
    if screen is None:
        return region

    left = max(region.left, screen.left)
    top = max(region.top, screen.top)
    right = min(region.left + region.width, screen.left + screen.width)
    bottom = min(region.top + region.height, screen.top + screen.height)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return region
    return CaptureRegion(left, top, width, height)


def get_window_title(hwnd: int) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""

    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value


def enumerate_windows() -> list[WindowInfo]:
    if not IS_WINDOWS:
        return []

    set_process_dpi_aware()
    windows: list[WindowInfo] = []

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True

        title = get_window_title(hwnd)
        if not title:
            return True

        region = get_window_region(hwnd)
        if region is None:
            return True

        windows.append(WindowInfo(int(hwnd), title, region))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def find_window(title: str, *, exact: bool = False, timeout_seconds: float = 10.0) -> WindowInfo:
    deadline = time.monotonic() + timeout_seconds
    normalized = title.casefold()

    while True:
        for window in enumerate_windows():
            candidate = window.title.casefold()
            if (exact and candidate == normalized) or (not exact and normalized in candidate):
                return window

        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)

    available = ", ".join(window.title for window in enumerate_windows()[:8])
    suffix = f" Visible windows: {available}" if available else ""
    raise WindowNotFoundError(f"Could not find a window titled {title!r}.{suffix}")


def get_current_console_window() -> WindowInfo | None:
    if not IS_WINDOWS:
        return None

    set_process_dpi_aware()
    raw_hwnd = kernel32.GetConsoleWindow()
    hwnd = int(raw_hwnd or 0)
    if hwnd == 0:
        return None

    region = get_window_region(hwnd)
    if region is None:
        return None

    return WindowInfo(hwnd, get_window_title(hwnd), region)


def activate_window(hwnd: int, *, maximize: bool = False, top: bool = False) -> None:
    if not IS_WINDOWS or not hwnd:
        return

    show_default = 3 if maximize else 5
    user32.ShowWindow(wintypes.HWND(hwnd), show_default)
    user32.SetForegroundWindow(wintypes.HWND(hwnd))

    if top:
        hwnd_topmost = wintypes.HWND(-1)
        no_move = 0x0002
        no_size = 0x0001
        show_window = 0x0040
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            hwnd_topmost,
            0,
            0,
            0,
            0,
            no_move | no_size | show_window,
        )


def configure_current_console(
    *,
    title: str | None = None,
    maximize: bool = True,
    top: bool = False,
) -> WindowInfo | None:
    if not IS_WINDOWS:
        return None

    set_process_dpi_aware()
    if title:
        kernel32.SetConsoleTitleW(title)
        time.sleep(0.1)
        try:
            titled_window = find_window(title, timeout_seconds=2.0)
        except WindowNotFoundError:
            titled_window = None
        if titled_window is not None:
            activate_window(titled_window.hwnd, maximize=maximize, top=top)
            time.sleep(0.25)
            refreshed_region = get_window_region(titled_window.hwnd)
            if refreshed_region is not None:
                return WindowInfo(titled_window.hwnd, titled_window.title, refreshed_region)
            return titled_window

    window = get_current_console_window()
    if window is None:
        return None

    activate_window(window.hwnd, maximize=maximize, top=top)
    time.sleep(0.25)
    return get_current_console_window() or window


def describe_path(path: str | Path) -> str:
    return str(Path(path).resolve())
