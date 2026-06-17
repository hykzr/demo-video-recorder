"""Core recorder API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import asyncio
from pathlib import Path
import shutil
import platform
import subprocess
import time
from typing import Callable, Sequence, overload

from demo_video_recorder.backends import FfmpegCaptureBackend
from demo_video_recorder.defaults import DEFAULTS
from demo_video_recorder.errors import RecordingError
from demo_video_recorder.macos import check_screen_recording_access
from demo_video_recorder.subtitles import (
    CueDisplay,
    SubtitleStyleLike,
    SubtitleWriter,
    subtitle_style_to_force_style,
)
from demo_video_recorder.tts import (
    NarrationClip,
    SynthesizedExplanation,
    TTSBackend,
)
from demo_video_recorder.types import CaptureRegion, WindowInfo
from demo_video_recorder import windowing

Command = str | Sequence[str]
PreparedCue = str | SynthesizedExplanation
CAPTURE_SYNC_THRESHOLD_SECONDS = 0.05


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
        keep_tts_audio: bool = False,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        draw_mouse: bool = False,
        subtitle_style: SubtitleStyleLike = None,
        tts: TTSBackend | None = None,
        narration_audio_path: str | Path | None = None,
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
        self.subtitle_style = subtitle_style_to_force_style(subtitle_style)
        self.keep_raw = keep_raw
        self.keep_tts_audio = keep_tts_audio
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
            subtitle_style=self.subtitle_style,
        )
        self.tts = tts
        self.narration_audio_path = (
            Path(narration_audio_path)
            if narration_audio_path is not None
            else self.output_path.with_name(f"{self.output_path.stem}.narration.m4a")
        )
        self._narration_clips: list[NarrationClip] = []
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
        self,
        *,
        region: CaptureRegion | None = None,
        clear: bool = False,
    ) -> "DemoVideoRecorder":
        """Start screen capture and reset subtitle timing."""

        if region is not None:
            self.capture_region = region

        self._before_start_recording(clear=clear)
        self.subtitles.reset_file()
        self._narration_clips = []
        self.capture.start(region=self.capture_region)
        self.capture.wait_until_ready()
        self.subtitles.start_clock()
        return self

    def _before_start_recording(self, *, clear: bool) -> None:
        del clear

    def explain(
        self,
        text: str | SynthesizedExplanation,
        *,
        wait: bool = True,
    ) -> "DemoVideoRecorder":
        """Add narration text that will be burned as subtitles."""

        if isinstance(text, SynthesizedExplanation):
            resolved_text = text.text
            clip = text.audio
        else:
            resolved_text = text
            clip = None

        if self.tts is None and clip is None:
            self.subtitles.add_cue(resolved_text, wait=wait)
            return self

        start_seconds = self.subtitles.open_cue(resolved_text)
        if start_seconds is None:
            return self

        if clip is None:
            if self.tts is None:
                raise RecordingError(
                    "Narration audio was requested, but no TTS backend is configured."
                )
            clip = self.tts.synthesize(resolved_text)
        self._narration_clips.append(
            NarrationClip(
                text=resolved_text.strip(),
                path=clip.path,
                start_seconds=start_seconds,
                duration_seconds=clip.duration_seconds,
            )
        )
        if wait:
            self.subtitles.wait_for_display(
                CueDisplay(start_seconds + clip.duration_seconds)
            )
        return self

    def synthesize_explanation_audio(self, text: str) -> SynthesizedExplanation:
        """Prepare narration text and audio ahead of a later ``explain()`` call."""

        if self.tts is None:
            raise RecordingError("Narration audio was requested, but TTS is disabled.")
        trimmed = text.strip()
        return SynthesizedExplanation(text=trimmed, audio=self.tts.synthesize(trimmed))

    async def synthesize_explanation_audio_async(
        self, text: str
    ) -> SynthesizedExplanation:
        """Async variant of ``synthesize_explanation_audio()``."""

        if self.tts is None:
            raise RecordingError("Narration audio was requested, but TTS is disabled.")
        trimmed = text.strip()
        return SynthesizedExplanation(
            text=trimmed,
            audio=await self.tts.synthesize_async(trimmed),
        )

    def synthesize_if_tts_enabled(self, text: str) -> str | SynthesizedExplanation:
        """Pre-synthesize narration only when a TTS backend is configured."""

        trimmed = text.strip()
        if self.tts is None:
            return trimmed
        return self.synthesize_explanation_audio(trimmed)

    async def synthesize_if_tts_enabled_async(
        self, text: str
    ) -> str | SynthesizedExplanation:
        """Async variant of ``synthesize_if_tts_enabled()``."""

        trimmed = text.strip()
        if self.tts is None:
            return trimmed
        return await self.synthesize_explanation_audio_async(trimmed)

    def prepare_cues(
        self,
        lines: Mapping[str, str],
        *,
        async_tts: bool = False,
    ) -> dict[str, PreparedCue]:
        """Prepare multiple narration cues before recording starts.

        Pass a named mapping such as ``{"intro": "..."}``; positional cue
        lists are intentionally unsupported because they are easy to misalign.

        With ``async_tts=False`` this prepares cues one at a time. With
        ``async_tts=True`` it runs the async variant concurrently with
        ``asyncio.run()``. If called from existing async code, use
        ``await recorder.prepare_cues_async(...)`` instead.
        """

        if not isinstance(lines, Mapping):
            raise TypeError("prepare_cues() requires a mapping of cue names to text.")

        if async_tts:
            return asyncio.run(self.prepare_cues_async(lines))

        return {
            name: self.synthesize_if_tts_enabled(line) for name, line in lines.items()
        }

    async def prepare_cues_async(
        self,
        lines: Mapping[str, str],
    ) -> dict[str, PreparedCue]:
        """Prepare multiple narration cues concurrently before recording starts."""

        if not isinstance(lines, Mapping):
            raise TypeError(
                "prepare_cues_async() requires a mapping of cue names to text."
            )

        names = list(lines)
        prepared = await asyncio.gather(
            *(self.synthesize_if_tts_enabled_async(lines[name]) for name in names)
        )
        return dict(zip(names, prepared))

    def cue_duration_seconds(self, cue: PreparedCue) -> float:
        """Return the display/audio duration for a prepared narration cue."""

        if isinstance(cue, SynthesizedExplanation):
            return cue.audio.duration_seconds
        return self.subtitles.read_delay_seconds(cue)

    @overload
    def explain_during(
        self,
        cues: PreparedCue,
        action: Callable[[], None],
        *,
        tail_seconds: float = 0.25,
    ) -> "DemoVideoRecorder": ...

    @overload
    def explain_during(
        self,
        cues: Sequence[PreparedCue],
        action: Callable[[], None],
        *,
        tail_seconds: float = 0.25,
    ) -> "DemoVideoRecorder": ...

    def explain_during(
        self,
        cues: PreparedCue | Sequence[PreparedCue],
        action: Callable[[], None],
        *,
        tail_seconds: float = 0.25,
    ) -> "DemoVideoRecorder":
        """Run an action while one or more prepared cues are narrated.

        The first cue starts before ``action`` and the recorder waits out the
        remaining cue duration before moving on. Extra cues, if provided, are
        displayed afterward so the next visible action cannot race ahead.
        """

        cue_list: list[PreparedCue]
        if isinstance(cues, (str, SynthesizedExplanation)):
            cue_list = [cues]
        else:
            cue_list = list(cues)

        if not cue_list:
            action()
            return self

        first = cue_list[0]
        started_at = self.subtitles.elapsed_seconds()
        self.explain(first, wait=False)
        try:
            action()
        except Exception:
            self.complete_explanation()
            raise

        remaining = self.cue_duration_seconds(first) - (
            self.subtitles.elapsed_seconds() - started_at
        )
        if remaining > 0:
            self.wait(remaining + tail_seconds)
        elif tail_seconds > 0:
            self.wait(tail_seconds)
        self.complete_explanation()

        for cue in cue_list[1:]:
            self.explain(cue)
            self.complete_explanation()
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
        timeline_end_seconds = self.subtitles.elapsed_seconds()
        if self.capture.is_recording:
            self.capture.stop()

        if self.raw_video_path.exists():
            duration = self._align_timeline_to_capture_duration(
                timeline_end_seconds=timeline_end_seconds,
            )
            self.subtitles.trim_to_duration(duration)

        should_burn = self.burn_subtitles_by_default if burn is None else burn
        narration_audio_path = self._render_narration_audio()
        if should_burn:
            final_path = self.burn_subtitles(audio_path=narration_audio_path)
        else:
            if narration_audio_path is not None:
                self.output_path.parent.mkdir(parents=True, exist_ok=True)
                burn_kwargs: dict[str, object] = {"audio_path": narration_audio_path}
                if self.subtitle_style is not None:
                    burn_kwargs["subtitle_style"] = self.subtitle_style
                self.capture.burn_subtitles(
                    self.subtitle_path,
                    self.output_path,
                    **burn_kwargs,
                )
                final_path = self.output_path
            else:
                final_path = self.raw_video_path

        if (
            final_path != self.raw_video_path
            and not self.keep_raw
            and self.raw_video_path.exists()
        ):
            self.raw_video_path.unlink(missing_ok=True)
        self._cleanup_narration_artifacts()

        return final_path

    def burn_subtitles(self, *, audio_path: str | Path | None = None) -> Path:
        """Burn the current SRT file into the raw recording."""

        burn_kwargs: dict[str, object] = {"audio_path": audio_path}
        if self.subtitle_style is not None:
            burn_kwargs["subtitle_style"] = self.subtitle_style
        return self.capture.burn_subtitles(
            self.subtitle_path,
            self.output_path,
            **burn_kwargs,
        )

    def render_narration_audio(self, output_path: str | Path | None = None) -> Path:
        """Render the synthesized narration timeline without screen capture."""

        if self.tts is None and not self._narration_clips:
            raise RecordingError("Narration audio was requested, but TTS is disabled.")
        if not self._narration_clips:
            raise RecordingError("No narration clips were generated.")

        if not self.subtitles.is_started:
            self.subtitles.start_clock()
        self.subtitles.complete_cue()

        target_path = (
            Path(output_path)
            if output_path is not None
            else self.output_path.with_suffix(".m4a")
        )
        final_path = self.capture.render_narration_audio(
            self._narration_clips,
            target_path,
        )
        if not self.keep_tts_audio and self.tts is not None:
            self.tts.cleanup()
        return final_path

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

    def _render_narration_audio(self) -> Path | None:
        if not self._narration_clips:
            return None
        return self.capture.render_narration_audio(
            self._narration_clips,
            self.narration_audio_path,
        )

    def _cleanup_narration_artifacts(self) -> None:
        if self.keep_tts_audio or self.tts is None:
            return
        self.tts.cleanup()
        self.narration_audio_path.unlink(missing_ok=True)

    def _align_timeline_to_capture_duration(
        self,
        *,
        timeline_end_seconds: float,
    ) -> float:
        duration_seconds = self.capture.probe_duration_seconds()

        lag_seconds = duration_seconds - max(timeline_end_seconds, 0.0)
        if lag_seconds <= CAPTURE_SYNC_THRESHOLD_SECONDS:
            return duration_seconds

        self.capture.trim_leading_seconds(lag_seconds)
        return self.capture.probe_duration_seconds()
