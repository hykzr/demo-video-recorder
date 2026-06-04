# Agent Guide

Use `demo-video-recorder` when the user asks for an automated demo video of a project.

## What It Is

`demo-video-recorder` is a Python library for scripted demo capture. It records terminal or app windows to MP4, burns subtitles into the video, and can optionally synthesize narration audio with TTS. It is meant for used as utils in project-specific recording scripts

## Availability Check

Do this before writing or running a recording script:

1. Check the local environment first.
   - Look for a Python project and its preferred runner: `pyproject.toml`, `uv.lock`, `.venv`, `requirements*.txt`.
   - Prefer the project's own environment over the system Python: `.venv/bin/python`, `uv run`, or the repo's existing task runner.
2. Verify `demo-video-recorder` is available in that environment.
   - In a normal consumer project, confirm the import works from the active environment.
   - Useful checks:
     - `python -c "import demo_video_recorder"`
3. Verify global recording dependencies.
   - `ffmpeg -version`
   - `ffprobe -version`
4. On macOS, also verify subtitle burn-in support.
   - Run `ffmpeg -hide_banner -filters | rg subtitles`
   - Stop and tell the user if the active `ffmpeg` build does not expose the `subtitles` filter (`libass`).
   - Note: if ffmpeg-full is installed, the library can auto pick it up even if the ffmpeg in PATH does not have libass, so please try `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` first if it exists
5. On macOS, verify Screen Recording permission before capture.
   - Prefer the library helpers: `check_screen_recording_access(prompt=True)` or `open_terminal(check_access=True)`.
   - Stop and tell the user if access is still rejected after the prompt.
6. If the demo needs narration audio, verify the TTS path too.
   - Confirm the chosen backend is importable and usable in the active environment.
   - For `EdgeTTSBackend`, a simple preflight is `python -c "import edge_tts"`.
   - Use `list_speakers()` before recording when you need to inspect available voices.

## Workflow

1. Inspect the target project first. Identify the workflow that demonstrate the main features and anything else required from the user.
2. Create a recording script, usually `record_demo.py`, that imports the recorder.
3. Prefer `CLIDemoRecorder` for terminal apps and `DemoVideoRecorder` for GUI or browser windows.
4. Record to `out/<project>-demo.mp4`, or the required location by user; if unspecified, keep generated output out of source control.
5. Follow the user's prompt first for speed, pauses, tone, and coverage. If they do not specify speed, use `DEFAULTS` from the library.
6. Follow the user's requested tone when given. Otherwise use a human live-demo style: natural, somewhat casual or lightly humorous, but still accurate and comprehensive. Unless otherwise specified, the subject should be `I` or `we`, not "the recorder", "the tool", or similar detached phrasing.
7. Use `explain()` before or after each visible action so the final video has useful burned subtitles, and spoken narration too when TTS is configured.
8. For interactive CLI apps, read the app output and react to it. Do not hardcode brittle input if the app is stateful or nondeterministic.
9. Run the script yourself. First run a fast smoke test, then fix timing, startup, focus, and input issues until the demo completes cleanly.
10. Check the actual video output, not just the script exit code.
    - Use `ffprobe` to confirm the file exists, has non-zero duration, and has the expected dimensions.
    - Extract representative frames with `ffmpeg`, read those images, and verify the video is not blank, cropped, or missing subtitles.
    - If the user did not already request a window size, use those extracted frames to choose an optimal terminal or app window size for readability before the final pass.
11. Record the final production demo once the interaction and framing are stable.
12. Unless otherwise specified, you do not need to create a full CLI entry point and all parameters in your recorder script; hardcoded script values are fine. Optional args are still fine when they help repeated testing.
13. If you use TTS, pick the speaker before recording starts. Follow the user's instructions when they specify a voice; otherwise choose one that fits the project's theme and audience.
14. TTS generation may be slow enough to show up as dead air in the capture. For pre-determined or longer narration, pre-synthesize it first with `synthesize_explanation_audio()`, then pass that prepared result into `explain(prepared_explanation)`.
15. For any true, previously unknown bugs from the project to demo, please inform the user and let them decide to fix it or hide it in the demo. You do not need to demo the features that is explicitly stated as not implemented, placebo, not within scope of current development phase, have unfixed issues unless explicitly asked to

## Defaults

Use these unless the user asked for something else:

```python
from demo_video_recorder import DEFAULTS

DEFAULTS.words_per_minute       # 170
DEFAULTS.min_pause_seconds      # 2.0
DEFAULTS.command_lead_seconds   # 0.0
DEFAULTS.typed_character_delay  # 0.018
DEFAULTS.capture_framerate      # 15
DEFAULTS.video_scale_width      # 1280
```

`FAST_SMOKE_TEST_DEFAULTS` is only for local smoke tests.

## TTS Notes

Useful helpers when narration audio is enabled:

- `EdgeTTSBackend(save_dir=..., speaker=..., speed=..., volume=...)`
- `tts.list_speakers()` to inspect available voices
- `recorder.synthesize_explanation_audio("...")` to prepare narration text plus audio ahead of time
- `recorder.explain(prepared_explanation)` to reuse pre-generated narration without blocking capture

## Output-Aware CLI Demos

Do not hardcode a brittle input script if the app is interactive. Read the app output and react to it.

Useful helpers:

- `expect_output("text", stream="combined" | "stdout" | "stderr")`
- `expect_regex(r"...")`, which returns a regex match object
- `mark_output()` before an action, then `output_since(marker)` afterward
- `check_output("text")` for immediate assertions
- `output_text("stdout")` and `output_text("stderr")` for debugging

When using `new_window=True`, the worker mirrors stdout and stderr to `out/<name>.worker.log`. If the worker exits with an error, the parent prints the log tail. Read that log, fix the recording script, and rerun.

## CLI Pattern

```python
from demo_video_recorder import CLIDemoRecorder, DEFAULTS, EdgeTTSBackend


def main():
    tts = EdgeTTSBackend(
        save_dir="out/demo.tts",
        speaker="en-US-AvaNeural",
        speed="+0%",
        volume="+0%",
    )
    r = CLIDemoRecorder(
        "out/demo.mp4",
        tts=tts,
        **DEFAULTS.recorder_kwargs(),
    )
    try:
        r.open_terminal(
            title="Project Demo",
            top=True,
            window_size=(1400, 1000),
            start_recording=True,
        )
        intro = r.synthesize_explanation_audio(
            "Today we'll demonstrate our new app"
        )
        conclusion = r.synthesize_explanation_audio(
            "The help output the available actions. Thanks for watching"
        )
        r.explain(intro)
        r.run(["python", "app.py"], interactive=True, command_label="python app.py")
        r.expect_output(">")
        marker = r.mark_output()
        r.input("help")
        r.expect_output("Commands", since=marker)
        r.explain(conclusion)
        r.input("quit")
        r.stop_app()
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

If you do not need narration audio, omit `tts=` and pass plain strings to `explain()`.

For a dedicated recording window, pass `new_window=True` to `open_terminal()`. The parent process reruns the same script in a new terminal window, waits for it, and exits.

## GUI Pattern

```python
from demo_video_recorder import DemoVideoRecorder


def main():
    r = DemoVideoRecorder("out/gui-demo.mp4")
    try:
        r.open_app(["notepad.exe"], title_hint="Untitled - Notepad", capture_window=True)
        r.start_capture_window()
        r.explain("The app is open and ready for the first action.")
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

## Public API

This is the package-level public surface exported from `demo_video_recorder.__init__`.

### Recorders

```python
class DemoVideoRecorder(
    output_path,
    *,
    raw_video_path=None,
    subtitle_path=None,
    words_per_minute=DEFAULTS.words_per_minute,
    min_pause_seconds=DEFAULTS.min_pause_seconds,
    manual_pause=False,
    capture_framerate=DEFAULTS.capture_framerate,
    video_scale_width=DEFAULTS.video_scale_width,
    burn_subtitles=True,
    keep_raw=False,
    keep_tts_audio=False,
    ffmpeg="ffmpeg",
    ffprobe="ffprobe",
    draw_mouse=False,
    tts=None,
    narration_audio_path=None,
)
```

- `is_recording: bool`
- `open_app(command, *, cwd=None, env=None, title_hint=None, wait_for_window_seconds=10.0, activate=True, capture_window=False, shell=None) -> subprocess.Popen[bytes]`
- `select_window(title, *, exact=False, timeout_seconds=10.0, activate=True, top=False, maximize=False) -> WindowInfo`
- `start_capture_window(*, title=None, region=None, exact=False, timeout_seconds=10.0) -> DemoVideoRecorder`
- `start_recording(*, region=None) -> DemoVideoRecorder`
- `explain(text: str | SynthesizedExplanation, *, wait=True) -> DemoVideoRecorder`
- `synthesize_explanation_audio(text: str) -> SynthesizedExplanation`
- `wait(seconds: float) -> DemoVideoRecorder`
- `complete_explanation() -> DemoVideoRecorder`
- `stop_recording(*, burn=None) -> Path`
- `burn_subtitles(*, audio_path=None) -> Path`
- `render_narration_audio(output_path=None) -> Path`
- `ensure_screen_recording_access(*, prompt=True, timeout_seconds=30.0, print_status=True) -> bool`
- `copy_raw_to_output() -> Path`
- `close() -> None`
- Supports context-manager use: `with DemoVideoRecorder(...) as r: ...`

```python
class CLIDemoRecorder(
    output_path,
    *,
    typed_character_delay=DEFAULTS.typed_character_delay,
    command_lead_seconds=DEFAULTS.command_lead_seconds,
    prompt="> ",
    **kwargs,
)
```

- Inherits all `DemoVideoRecorder` methods.
- `open_terminal(*, title=None, top=False, maximize=False, window_size=None, start_recording=True, new_window=False, script_path=None, extra_args=None, wait_for_worker=True, check_access=None, access_timeout_seconds=30.0) -> CLIDemoRecorder`
- `run(command, *, cwd=None, env=None, interactive=False, command_label=None, shell=None, check=True, timeout=None, reveal_command=True) -> int | subprocess.Popen[str]`
- `input(text: str, *, enter=True, delay=None, wait_after=0.25) -> CLIDemoRecorder`
- `output_text(stream="combined") -> str`
- `mark_output(stream="combined") -> OutputMarker`
- `output_since(marker, stream="combined") -> str`
- `check_output(text: str, *, stream="combined", since=0) -> bool`
- `wait_for_output(text: str, *, timeout_seconds=10.0, stream="combined", since=0) -> CLIDemoRecorder`
- `expect_output(text: str, *, timeout_seconds=10.0, stream="combined", since=0) -> str`
- `wait_for_regex(pattern, *, timeout_seconds=10.0, stream="combined", since=0, flags=0) -> re.Match[str]`
- `expect_regex(pattern, *, timeout_seconds=10.0, stream="combined", since=0, flags=0) -> re.Match[str]`
- `stop_app(*, timeout_seconds=5.0) -> int | None`
- `close() -> None`

### TTS

```python
class TTSBackend(*, save_dir, ffprobe="ffprobe")
```

- `synthesize(text: str) -> SynthesizedAudio`
- `cleanup() -> None`
- `list_speakers() -> list[str]`
- `save_audio(text: str) -> Path` (abstract)

```python
class EdgeTTSBackend(
    *,
    save_dir,
    speaker="en-US-AvaNeural",
    speed="+0%",
    volume="+0%",
    ffprobe="ffprobe",
)
```

- Inherits `TTSBackend`.
- `save_audio(text: str) -> Path`
- `list_speakers() -> list[str]`

### Functions

```python
check_screen_recording_access(
    *,
    prompt=True,
    timeout_seconds=30.0,
    poll_interval_seconds=0.25,
) -> ScreenRecordingAccessResult
```

### Defaults and Value Types

```python
class RecorderDefaults(
    words_per_minute=170,
    min_pause_seconds=2.0,
    command_lead_seconds=0.0,
    typed_character_delay=0.018,
    capture_framerate=15,
    video_scale_width=1280,
)
```

- `recorder_kwargs() -> dict[str, int | float]`
- `DEFAULTS = RecorderDefaults()`
- `FAST_SMOKE_TEST_DEFAULTS = RecorderDefaults(words_per_minute=900, min_pause_seconds=0.75, typed_character_delay=0.004)`

```python
class CaptureRegion(left: int, top: int, width: int, height: int)
```

- `validate() -> CaptureRegion`
- `size_arg: str`

```python
class WindowInfo(hwnd: int, title: str, region: CaptureRegion)
class OutputMarker(combined: int, stdout: int, stderr: int)
class ScreenRecordingAccessResult(granted: bool, prompted: bool, status: str)
class SynthesizedAudio(path: Path, duration_seconds: float)
class SynthesizedExplanation(text: str, audio: SynthesizedAudio)
class NarrationClip(text: str, path: Path, start_seconds: float, duration_seconds: float)
```

- `OutputMarker.position(stream_name) -> int`

### Errors

```python
class DemoVideoRecorderError(RuntimeError)
class DependencyMissingError(DemoVideoRecorderError)
class RecordingError(DemoVideoRecorderError)
class WindowNotFoundError(DemoVideoRecorderError)
class ProcessError(DemoVideoRecorderError)
```

Keep demos short and clean. Seed test data when determinism matters; when the user wants randomness or live behavior, react to the app output instead of pretending the result is fixed.
