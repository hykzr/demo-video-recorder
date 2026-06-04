"""Small Windows window-management helpers.

The public recorder does not depend on this module being available. On
non-Windows platforms these functions either return ``None`` or raise a clear
window lookup error, which keeps the backend replaceable later.
"""

from __future__ import annotations

from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import platform
import subprocess
import sys
import time

from demo_video_recorder.errors import WindowNotFoundError
from demo_video_recorder.macos import (
    get_display_bounds_for_rect,
    get_display_scale_factor_for_rect,
)
from demo_video_recorder.types import CaptureRegion, WindowInfo

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # type: ignore

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
    RECT = object  # type: ignore


def set_process_dpi_aware() -> None:
    """Use physical pixels for window bounds on Windows."""

    if not IS_WINDOWS:
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore
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
    return clamp_region_to_virtual_screen(
        CaptureRegion(int(rect.left), int(rect.top), width, height)
    )


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


def fit_region_in_screen(
    region: CaptureRegion,
    screen: CaptureRegion,
    *,
    preferred_size: tuple[int, int] | None = None,
) -> CaptureRegion:
    """Resize and reposition a region so it stays fully inside ``screen``."""

    width = region.width
    height = region.height
    if preferred_size is not None:
        width, height = preferred_size

    width = max(1, min(width, screen.width))
    height = max(1, min(height, screen.height))

    max_left = screen.left + screen.width - width
    max_top = screen.top + screen.height - height
    left = min(max(region.left, screen.left), max_left)
    top = min(max(region.top, screen.top), max_top)
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
    if IS_MACOS:
        window = get_current_console_window()
        return [window] if window is not None else []

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


def find_window(
    title: str, *, exact: bool = False, timeout_seconds: float = 10.0
) -> WindowInfo:
    deadline = time.monotonic() + timeout_seconds
    normalized = title.casefold()

    while True:
        for window in enumerate_windows():
            candidate = window.title.casefold()
            if (exact and candidate == normalized) or (
                not exact and normalized in candidate
            ):
                return window

        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)

    available = ", ".join(window.title for window in enumerate_windows()[:8])
    suffix = f" Visible windows: {available}" if available else ""
    raise WindowNotFoundError(f"Could not find a window titled {title!r}.{suffix}")


def get_current_console_window() -> WindowInfo | None:
    if IS_MACOS:
        return _get_macos_console_window()

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
    if IS_MACOS:
        del hwnd, maximize, top
        _activate_macos_console()
        return

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


def ensure_window_bounds(
    hwnd: int,
    *,
    window_size: tuple[int, int] | None = None,
) -> None:
    if not IS_WINDOWS or not hwnd:
        return

    screen = get_virtual_screen_region()
    region = get_window_region(hwnd)
    if screen is None or region is None:
        return

    fitted = fit_region_in_screen(region, screen, preferred_size=window_size)
    should_resize = (
        fitted.left != region.left
        or fitted.top != region.top
        or fitted.width != region.width
        or fitted.height != region.height
    )
    if not should_resize:
        return

    no_zorder = 0x0004
    show_window = 0x0040
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(0),
        fitted.left,
        fitted.top,
        fitted.width,
        fitted.height,
        no_zorder | show_window,
    )


def configure_current_console(
    *,
    title: str | None = None,
    maximize: bool = True,
    top: bool = False,
    window_size: tuple[int, int] | None = None,
) -> WindowInfo | None:
    if IS_MACOS:
        if title:
            time.sleep(0.15)
        _activate_macos_console()
        time.sleep(0.15)
        window = _wait_for_macos_console_window(title=title)
        if window is None:
            return None
        _configure_macos_console_window(
            window,
            title=title,
            maximize=maximize,
            top=top,
            window_size=window_size,
        )
        time.sleep(0.15)
        return _wait_for_macos_console_window(title=title) or window

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
            ensure_window_bounds(titled_window.hwnd, window_size=window_size)
            time.sleep(0.25)
            refreshed_region = get_window_region(titled_window.hwnd)
            if refreshed_region is not None:
                return WindowInfo(
                    titled_window.hwnd, titled_window.title, refreshed_region
                )
            return titled_window

    window = get_current_console_window()
    if window is None:
        return None

    activate_window(window.hwnd, maximize=maximize, top=top)
    ensure_window_bounds(window.hwnd, window_size=window_size)
    time.sleep(0.25)
    return get_current_console_window() or window


def describe_path(path: str | Path) -> str:
    return str(Path(path).resolve())


def _activate_macos_console() -> None:
    app_name = _macos_terminal_app_name()
    if app_name is None:
        return
    _run_osascript([f'tell application "{app_name}" to activate'])


def make_macos_console_background_opaque(*, title: str | None = None) -> bool:
    if not IS_MACOS:
        return False

    app_name = _macos_terminal_app_name()
    if app_name is None:
        return False

    tty_path = _current_tty_path()
    queries: list[list[str]] = []
    if tty_path:
        queries.append(
            _macos_set_window_background_opaque_lines(app_name, tty_path=tty_path)
        )
    if title:
        queries.append(
            _macos_set_window_background_opaque_lines(app_name, title=title)
        )
    queries.append(_macos_set_window_background_opaque_lines(app_name))

    for query in queries:
        if _run_osascript(query) == "ok":
            return True
    return False


def _configure_macos_console_window(
    window: WindowInfo,
    *,
    title: str | None,
    maximize: bool,
    top: bool,
    window_size: tuple[int, int] | None,
) -> None:
    del top

    target_bounds = _fit_macos_window_bounds(
        window.region,
        maximize=maximize,
        window_size=window_size,
    )
    if target_bounds is None:
        return

    scale = get_display_scale_factor_for_rect(
        target_bounds.left,
        target_bounds.top,
        target_bounds.left + target_bounds.width,
        target_bounds.top + target_bounds.height,
    )
    current_bounds = _macos_pixel_region_to_points(window.region, scale)
    if current_bounds == target_bounds:
        return

    _set_macos_console_window_bounds(target_bounds, title=title)


def _fit_macos_window_bounds(
    region: CaptureRegion,
    *,
    maximize: bool,
    window_size: tuple[int, int] | None,
) -> CaptureRegion | None:
    scale = get_display_scale_factor_for_rect(
        region.left,
        region.top,
        region.left + region.width,
        region.top + region.height,
    )
    current_bounds = _macos_pixel_region_to_points(region, scale)
    screen = get_display_bounds_for_rect(
        current_bounds.left,
        current_bounds.top,
        current_bounds.left + current_bounds.width,
        current_bounds.top + current_bounds.height,
    )
    if screen is None:
        return None

    preferred_size: tuple[int, int] | None = None
    if window_size is not None:
        preferred_size = (
            max(int(round(window_size[0] / scale)), 1),
            max(int(round(window_size[1] / scale)), 1),
        )
    elif maximize:
        preferred_size = (screen.width, screen.height)

    return fit_region_in_screen(current_bounds, screen, preferred_size=preferred_size)


def _macos_pixel_region_to_points(
    region: CaptureRegion, scale: float
) -> CaptureRegion:
    return CaptureRegion(
        int(round(region.left / scale)),
        int(round(region.top / scale)),
        max(int(round(region.width / scale)), 1),
        max(int(round(region.height / scale)), 1),
    )


def _get_macos_console_window() -> WindowInfo | None:
    return _get_macos_console_window_for_title()


def _wait_for_macos_console_window(
    *, title: str | None = None, timeout_seconds: float = 2.0
) -> WindowInfo | None:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        window = _get_macos_console_window_for_title(
            title=title,
            allow_front_fallback=False,
        )
        if window is not None:
            return window
        time.sleep(0.1)

    return _get_macos_console_window_for_title(title=title, allow_front_fallback=True)


def _get_macos_console_window_for_title(
    *, title: str | None = None, allow_front_fallback: bool = True
) -> WindowInfo | None:
    app_name = _macos_terminal_app_name()
    if app_name is None:
        return None

    tty_path = _current_tty_path()
    queries: list[list[str]] = []
    if tty_path:
        queries.append(_macos_window_query_lines(app_name, tty_path=tty_path))
    if title:
        queries.append(_macos_window_query_lines(app_name, title=title))
    if allow_front_fallback:
        queries.append(_macos_front_window_query_lines(app_name))

    for query in queries:
        output = _run_osascript(query)
        window = _parse_macos_window(output)
        if window is not None:
            return window
    return None


def _parse_macos_window(output: str | None) -> WindowInfo | None:
    if not output:
        return None

    parts = output.split("|", 4)
    if len(parts) != 5:
        return None

    try:
        left, top, right, bottom = (float(part.strip()) for part in parts[1:])
    except ValueError:
        return None

    scale = get_display_scale_factor_for_rect(left, top, right, bottom)
    width = max(int(round((right - left) * scale)), 0)
    height = max(int(round((bottom - top) * scale)), 0)
    if width <= 0 or height <= 0:
        return None

    region = CaptureRegion(
        int(round(left * scale)),
        int(round(top * scale)),
        width,
        height,
    )
    return WindowInfo(0, parts[0], region)


def _current_tty_path() -> str | None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            continue
        if not os.isatty(fd):
            continue
        try:
            return os.ttyname(fd) # type: ignore
        except OSError:
            continue
    return None


def _macos_window_query_lines(
    app_name: str,
    *,
    tty_path: str | None = None,
    title: str | None = None,
) -> list[str]:
    if tty_path:
        if app_name == "iTerm":
            return [
                f"set targetTty to {_applescript_string(tty_path)}",
                f'tell application "{app_name}"',
                'if (count of windows) = 0 then return ""',
                "repeat with aWindow in windows",
                "repeat with aTab in tabs of aWindow",
                "repeat with aSession in sessions of aTab",
                "if tty of aSession is equal to targetTty then",
                "set boundsList to bounds of aWindow",
                "set windowName to name of aWindow",
                'return windowName & "|" & (item 1 of boundsList as text) & "|" & (item 2 of boundsList as text) & "|" & (item 3 of boundsList as text) & "|" & (item 4 of boundsList as text)',
                "end if",
                "end repeat",
                "end repeat",
                "end repeat",
                'return ""',
                "end tell",
            ]
        return [
            f"set targetTty to {_applescript_string(tty_path)}",
            f'tell application "{app_name}"',
            'if (count of windows) = 0 then return ""',
            "repeat with aWindow in windows",
            "repeat with aTab in tabs of aWindow",
            "if tty of aTab is equal to targetTty then",
            "set boundsList to bounds of aWindow",
            "set windowName to name of aWindow",
            'return windowName & "|" & (item 1 of boundsList as text) & "|" & (item 2 of boundsList as text) & "|" & (item 3 of boundsList as text) & "|" & (item 4 of boundsList as text)',
            "end if",
            "end repeat",
            "end repeat",
            'return ""',
            "end tell",
        ]

    if title is None:
        return _macos_front_window_query_lines(app_name)

    return [
        f"set targetTitle to {_applescript_string(title)}",
        f'tell application "{app_name}"',
        'if (count of windows) = 0 then return ""',
        "repeat with aWindow in windows",
        "if name of aWindow is equal to targetTitle then",
        "set boundsList to bounds of aWindow",
        "set windowName to name of aWindow",
        'return windowName & "|" & (item 1 of boundsList as text) & "|" & (item 2 of boundsList as text) & "|" & (item 3 of boundsList as text) & "|" & (item 4 of boundsList as text)',
        "end if",
        "end repeat",
        'return ""',
        "end tell",
    ]


def _macos_front_window_query_lines(app_name: str) -> list[str]:
    return [
        f'tell application "{app_name}"',
        'if (count of windows) = 0 then return ""',
        "set frontBounds to bounds of front window",
        "set windowName to name of front window",
        'return windowName & "|" & (item 1 of frontBounds as text) & "|" & (item 2 of frontBounds as text) & "|" & (item 3 of frontBounds as text) & "|" & (item 4 of frontBounds as text)',
        "end tell",
    ]


def _set_macos_console_window_bounds(
    bounds: CaptureRegion,
    *,
    title: str | None = None,
) -> None:
    app_name = _macos_terminal_app_name()
    if app_name is None:
        return

    tty_path = _current_tty_path()
    queries: list[list[str]] = []
    if tty_path:
        queries.append(
            _macos_set_window_bounds_lines(app_name, bounds, tty_path=tty_path)
        )
    if title:
        queries.append(_macos_set_window_bounds_lines(app_name, bounds, title=title))
    queries.append(_macos_set_window_bounds_lines(app_name, bounds))

    for query in queries:
        if _run_osascript(query):
            return


def _macos_set_window_background_opaque_lines(
    app_name: str,
    *,
    tty_path: str | None = None,
    title: str | None = None,
) -> list[str]:
    if app_name == "iTerm":
        return _macos_set_iterm_background_opaque_lines(
            tty_path=tty_path,
            title=title,
        )
    return _macos_set_terminal_background_opaque_lines(
        tty_path=tty_path,
        title=title,
    )


def _macos_set_terminal_background_opaque_lines(
    *,
    tty_path: str | None = None,
    title: str | None = None,
) -> list[str]:
    if tty_path:
        return [
            f"set targetTty to {_applescript_string(tty_path)}",
            'tell application "Terminal"',
            'if (count of windows) = 0 then return ""',
            "repeat with aWindow in windows",
            "repeat with aTab in tabs of aWindow",
            "if tty of aTab is equal to targetTty then",
            "set targetTab to aTab",
            "set currentBackgroundColor to background color of targetTab",
            "set background color of targetTab to currentBackgroundColor",
            'return "ok"',
            "end if",
            "end repeat",
            "end repeat",
            'return ""',
            "end tell",
        ]

    if title is None:
        return [
            'tell application "Terminal"',
            'if (count of windows) = 0 then return ""',
            "set targetTab to selected tab of front window",
            "set currentBackgroundColor to background color of targetTab",
            "set background color of targetTab to currentBackgroundColor",
            'return "ok"',
            "end tell",
        ]

    return [
        f"set targetTitle to {_applescript_string(title)}",
        'tell application "Terminal"',
        'if (count of windows) = 0 then return ""',
        "repeat with aWindow in windows",
        "if name of aWindow is equal to targetTitle then",
        "set targetTab to selected tab of aWindow",
        "set currentBackgroundColor to background color of targetTab",
        "set background color of targetTab to currentBackgroundColor",
        'return "ok"',
        "end if",
        "end repeat",
        'return ""',
        "end tell",
    ]


def _macos_set_iterm_background_opaque_lines(
    *,
    tty_path: str | None = None,
    title: str | None = None,
) -> list[str]:
    if tty_path:
        return [
            f"set targetTty to {_applescript_string(tty_path)}",
            'tell application "iTerm"',
            'if (count of windows) = 0 then return ""',
            "repeat with aWindow in windows",
            "repeat with aTab in tabs of aWindow",
            "repeat with aSession in sessions of aTab",
            "if tty of aSession is equal to targetTty then",
            "set transparency of aSession to 0",
            'return "ok"',
            "end if",
            "end repeat",
            "end repeat",
            "end repeat",
            'return ""',
            "end tell",
        ]

    if title is None:
        return [
            'tell application "iTerm"',
            'if (count of windows) = 0 then return ""',
            "set transparency of current session of current window to 0",
            'return "ok"',
            "end tell",
        ]

    return [
        f"set targetTitle to {_applescript_string(title)}",
        'tell application "iTerm"',
        'if (count of windows) = 0 then return ""',
        "repeat with aWindow in windows",
        "if name of aWindow is equal to targetTitle then",
        "set transparency of current session of aWindow to 0",
        'return "ok"',
        "end if",
        "end repeat",
        'return ""',
        "end tell",
    ]


def _macos_set_window_bounds_lines(
    app_name: str,
    bounds: CaptureRegion,
    *,
    tty_path: str | None = None,
    title: str | None = None,
) -> list[str]:
    bounds_list = (
        "{"
        f"{bounds.left}, {bounds.top}, "
        f"{bounds.left + bounds.width}, {bounds.top + bounds.height}"
        "}"
    )
    if tty_path:
        if app_name == "iTerm":
            return [
                f"set targetTty to {_applescript_string(tty_path)}",
                f"set targetBounds to {bounds_list}",
                f'tell application "{app_name}"',
                'if (count of windows) = 0 then return ""',
                "repeat with aWindow in windows",
                "repeat with aTab in tabs of aWindow",
                "repeat with aSession in sessions of aTab",
                "if tty of aSession is equal to targetTty then",
                "set bounds of aWindow to targetBounds",
                'return "ok"',
                "end if",
                "end repeat",
                "end repeat",
                "end repeat",
                'return ""',
                "end tell",
            ]
        return [
            f"set targetTty to {_applescript_string(tty_path)}",
            f"set targetBounds to {bounds_list}",
            f'tell application "{app_name}"',
            'if (count of windows) = 0 then return ""',
            "repeat with aWindow in windows",
            "repeat with aTab in tabs of aWindow",
            "if tty of aTab is equal to targetTty then",
            "set bounds of aWindow to targetBounds",
            'return "ok"',
            "end if",
            "end repeat",
            "end repeat",
            'return ""',
            "end tell",
        ]

    if title is None:
        return [
            f"set targetBounds to {bounds_list}",
            f'tell application "{app_name}"',
            'if (count of windows) = 0 then return ""',
            "set bounds of front window to targetBounds",
            'return "ok"',
            "end tell",
        ]

    return [
        f"set targetTitle to {_applescript_string(title)}",
        f"set targetBounds to {bounds_list}",
        f'tell application "{app_name}"',
        'if (count of windows) = 0 then return ""',
        "repeat with aWindow in windows",
        "if name of aWindow is equal to targetTitle then",
        "set bounds of aWindow to targetBounds",
        'return "ok"',
        "end if",
        "end repeat",
        'return ""',
        "end tell",
    ]


def _applescript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _macos_terminal_app_name() -> str | None:
    program = os.environ.get("TERM_PROGRAM", "")
    if program == "Apple_Terminal":
        return "Terminal"
    if program in {"iTerm.app", "iTerm2"}:
        return "iTerm"
    return None


def _run_osascript(lines: list[str]) -> str | None:
    command = ["osascript"]
    for line in lines:
        command.extend(["-e", line])

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()
