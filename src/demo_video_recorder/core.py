"""Core recorder API."""

from __future__ import annotations

from pathlib import Path
import shutil
import platform
import subprocess
import time
from typing import Mapping, Sequence

from demo_video_recorder.backends import FfmpegCaptureBackend
from demo_video_recorder.defaults import DEFAULTS
from demo_video_recorder.errors import RecordingError
from demo_video_recorder.macos import check_screen_recording_access
from demo_video_recorder.subtitles import SubtitleWriter
from demo_video_recorder.types import CaptureRegion, WindowInfo
from demo_video_recorder import windowing

Command = str | Sequence[str]


class DemoVideoRecorder:
    """Reusable recorder for app demos.

    The class owns three separate concerns: finding/opening apps, recording a
    capture region, and writing/burning narration subtitles.
    """

    def __init__(
        self,
        output_path: str | Path,
        *,
        raw_video_path: str | Path | None = None,
        subtitle_path: str | Path | None = None,
        words_per_minute: int = DEFAULTS.words_per_minute,
        min_pause_seconds: float = DEFAULTS.min_pause_seconds,
        manual_pause: bool = False,
        capture_framerate: int = DEFAULTS.capture_framerate,
        video_scale_width: int | None = DEFAULTS.video_scale_width,
        burn_subtitles: bool = True,
        keep_raw: bool = False,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        draw_mouse: bool = False,
    ) -> None:
        self.output_path = Path(output_path)
        self.raw_video_path = (
            Path(raw_video_path)
            if raw_video_path is not None
            else self.output_path.with_name(f"{self.output_path.stem}.raw.mp4")
        )
        self.subtitle_path = (
            Path(subtitle_path)
            if subtitle_path is not None
            else self.output_path.with_suffix(".srt")
        )
        self.burn_subtitles_by_default = burn_subtitles
        self.keep_raw = keep_raw
        self.subtitles = SubtitleWriter(
            self.subtitle_path,
            words_per_minute=words_per_minute,
            min_pause_seconds=min_pause_seconds,
            manual_pause=manual_pause,
        )
        self.capture = FfmpegCaptureBackend(
            self.raw_video_path,
            framerate=capture_framerate,
            scale_width=video_scale_width,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            draw_mouse=draw_mouse,
        )
        self.capture_window: WindowInfo | None = None
        self.capture_region: CaptureRegion | None = None
        self.opened_processes: list[subprocess.Popen[bytes]] = []

    @property
    def is_recording(self) -> bool:
        return self.capture.is_recording

    def open_app(
        self,
        command: Command,
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        title_hint: str | None = None,
        wait_for_window_seconds: float = 10.0,
        activate: bool = True,
        capture_window: bool = False,
        shell: bool | None = None,
    ) -> subprocess.Popen[bytes]:
        """Open an application and optionally select its window for capture."""

        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            shell=isinstance(command, str) if shell is None else shell,
        )
        self.opened_processes.append(process)

        if title_hint:
            window = self.select_window(
                title_hint,
                timeout_seconds=wait_for_window_seconds,
                activate=activate,
            )
            if capture_window:
                self.capture_window = window
                self.capture_region = window.region

        return process

    def select_window(
        self,
        title: str,
        *,
        exact: bool = False,
        timeout_seconds: float = 10.0,
        activate: bool = True,
        top: bool = False,
        maximize: bool = False,
    ) -> WindowInfo:
        """Find a visible desktop window and store it as the capture target."""

        window = windowing.find_window(
            title, exact=exact, timeout_seconds=timeout_seconds
        )
        if activate:
            windowing.activate_window(window.hwnd, maximize=maximize, top=top)
            time.sleep(0.2)
            refreshed_region = windowing.get_window_region(window.hwnd)
            if refreshed_region is not None:
                window = WindowInfo(window.hwnd, window.title, refreshed_region)

        self.capture_window = window
        self.capture_region = window.region
        return window

    def start_capture_window(
        self,
        *,
        title: str | None = None,
        region: CaptureRegion | None = None,
        exact: bool = False,
        timeout_seconds: float = 10.0,
    ) -> "DemoVideoRecorder":
        """Start recording a selected window or explicit region."""

        if region is not None:
            self.capture_region = region
        elif title is not None:
            self.select_window(title, exact=exact, timeout_seconds=timeout_seconds)

        return self.start_recording(region=self.capture_region)

    def start_recording(
        self, *, region: CaptureRegion | None = None
    ) -> "DemoVideoRecorder":
        """Start screen capture and reset subtitle timing."""

        if region is not None:
            self.capture_region = region

        self.subtitles.reset_file()
        self.capture.start(region=self.capture_region)
        self.capture.wait_until_ready()
        self.subtitles.start_clock()
        return self

    def show_explanation(self, text: str, *, wait: bool = True) -> "DemoVideoRecorder":
        """Add narration text that will be burned as subtitles."""

        self.subtitles.add_cue(text, wait=wait)
        return self

    def wait(self, seconds: float) -> "DemoVideoRecorder":
        time.sleep(seconds)
        return self

    def complete_explanation(self) -> "DemoVideoRecorder":
        self.subtitles.complete_cue()
        return self

    def stop_recording(self, *, burn: bool | None = None) -> Path:
        """Stop capture and return the final video path."""

        self.subtitles.complete_cue()
        if self.capture.is_recording:
            self.capture.stop()

        if self.raw_video_path.exists():
            duration = self.capture.probe_duration_seconds()
            self.subtitles.trim_to_duration(duration)

        should_burn = self.burn_subtitles_by_default if burn is None else burn
        if should_burn:
            final_path = self.burn_subtitles()
        else:
            final_path = self.raw_video_path

        if should_burn and not self.keep_raw and self.raw_video_path.exists():
            self.raw_video_path.unlink(missing_ok=True)

        return final_path

    def burn_subtitles(self) -> Path:
        """Burn the current SRT file into the raw recording."""

        return self.capture.burn_subtitles(self.subtitle_path, self.output_path)

    def ensure_screen_recording_access(
        self,
        *,
        prompt: bool = True,
        timeout_seconds: float = 30.0,
        print_status: bool = True,
    ) -> bool:
        """Check and optionally request macOS Screen Recording permission."""

        result = check_screen_recording_access(
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )
        if print_status and platform.system() == "Darwin":
            print(f"Screen recording access status: {result.status}")

        if result.granted:
            return True

        raise RecordingError(
            "Screen recording access was not granted for this app. "
            "Grant Screen Recording permission in System Settings, then rerun the command."
        )

    def close(self) -> None:
        """Close child applications and finish the current subtitle cue."""

        self.subtitles.complete_cue()
        for process in list(self.opened_processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            self.opened_processes.remove(process)

    def __enter__(self) -> "DemoVideoRecorder":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def copy_raw_to_output(self) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.raw_video_path, self.output_path)
        return self.output_path
