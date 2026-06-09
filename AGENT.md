# Agent Guide

Use `demo-video-recorder` when the user asks for an automated demo video of a project.

## What It Is

`demo-video-recorder` is a Python library for scripted demo capture. It records terminal or app windows to MP4, burns subtitles into the video, and can optionally synthesize narration audio with TTS. It is meant to be used as utilities in project-specific recording scripts.

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
   - For Web UI demos, also verify the Playwright browser binary you plan to use, usually with `python -m playwright install chromium` if Chromium has not been installed yet.
4. On macOS, also verify subtitle burn-in support.
   - Run `ffmpeg -hide_banner -filters | rg subtitles`
   - Stop and tell the user if the active `ffmpeg` build does not expose the `subtitles` filter (`libass`).
   - Note: if ffmpeg-full is installed, the library can auto pick it up even if the ffmpeg in PATH does not have libass, so please try `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` first if it exists
5. On macOS, verify Screen Recording permission before capture.
   - Prefer the library helpers: `check_screen_recording_access(prompt=True)` or `open_terminal(check_access=True)`.
   - Stop and tell the user if access is still rejected after the prompt.
6. Unless the user says otherwise, clear the terminal before the first recorded command after setup.
   - `open_terminal(clear=True)` now does this by default after title changes, window sizing, permission checks, and `start_recording`.
   - Use that first clear to wipe permission-check output or other setup noise that may still be visible when recording begins.
   - You usually do not need additional clears for later commands unless the user asked for them or the previous command spammed a lot of low-value output.
7. If the demo needs narration audio, verify the TTS path too.
   - Confirm the chosen backend is importable and usable in the active environment.
   - For `EdgeTTSBackend`, a simple preflight is `python -c "import edge_tts"`.
   - Use `list_speakers()` before recording when you need to inspect available voices.
   - Prefer Edge TTS for final narration. Use the native macOS/Windows backend only after Edge TTS fails for an unfixable reason such as repeated service-side `NoAudioReceived` or a network/service problem outside the project.

## Workflow

1. Inspect the target project first. Identify the workflow that demonstrates the main features and anything else required from the user.
2. Create a recording script, usually `record_demo.py`, that imports the recorder.
3. Prefer `CLIDemoRecorder` for terminal apps, `WebUIRecorder` for browser apps, and `DemoVideoRecorder` for native GUI windows.
4. Record to `out/<project>-demo.mp4`, or the required location by user; if unspecified, keep generated output out of source control.
5. Follow the user's prompt first for speed, pauses, tone, and coverage. If they do not specify speed, use `DEFAULTS` from the library.
6. Follow the user's requested tone when given. Otherwise use a human live-demo style: natural, somewhat casual or lightly humorous, but still accurate and comprehensive. Unless otherwise specified, the subject should be `I` or `we`, not "the recorder", "the tool", or similar detached phrasing.
7. Keep every narration cue short: at most 25 words, and short enough to burn as no more than 2 subtitle lines. It is fine to speak several short clips sequentially.
8. Use `explain()` before or after each visible action so the final video has useful burned subtitles, and spoken narration too when TTS is configured.
9. For interactive CLI apps, read the app output and react to it. Do not hardcode brittle input if the app is stateful or nondeterministic.
10. For Web UI apps, highlight important non-interactive results too, not only controls. After a click, scroll/highlight the confirmation, computed output, chart, table row, toast, or result panel so the viewer can see what changed.
11. Run the script yourself in stages.
    - First run a fast smoke test with TTS disabled and with animations/motion disabled or minimized.
    - Add script options such as `--smoke`, `--no-tts`, and `--no-animation` when that helps repeated testing.
    - In smoke/no-animation mode, use `FAST_SMOKE_TEST_DEFAULTS`, `typed_character_delay=0`, no Playwright `slow_mo_ms`, shorter waits, and `highlight=False` or shorter highlight durations where appropriate.
    - Fix timing, startup, focus, input, scrolling, and selector issues before enabling narration audio.
12. Monitor every smoke and final pass. If a step is waiting forever, interrupt, inspect logs/processes/output files, and fix the script. Be patient too: browser startup, app boot, ffmpeg burn-in, and TTS generation can legitimately take several minutes.
13. Check the actual video output, not just the script exit code.
    - Use `ffprobe` to confirm the file exists, has non-zero duration, and has the expected dimensions.
    - Extract representative frames with `ffmpeg`, read those images, and verify the video is not blank, cropped, or missing subtitles.
    - If the user did not already request a window size, use those extracted frames to choose an optimal terminal or app window size for readability before the final pass.
14. Record the final production demo once the interaction and framing are stable.
15. Do not remove the recording script unless the user explicitly asks. Keep it so the explanation, selectors, timing, and demo logic can be polished in later passes.
16. Unless otherwise specified, you do not need to create a full CLI entry point and all parameters in your recorder script; hardcoded script values are fine. Optional args are still fine when they help repeated testing.
17. If you use TTS, pick the speaker before recording starts. Follow the user's instructions when they specify a voice; otherwise choose one that fits the project's theme and audience.
18. TTS generation may be slow enough to show up as dead air in the capture. For pre-determined narration, pre-synthesize it before the visible interaction starts with `synthesize_if_tts_enabled()` when TTS is optional, or `synthesize_explanation_audio()` when TTS is required, then pass that prepared result into `explain(prepared_explanation)`.
19. For many narration clips, use the async variants before recording starts so clips can be prepared while the app is still outside the captured timeline. Use `cache=True` on the TTS backend to reuse previously generated clips across reruns.
20. For any true, previously unknown bugs from the project to demo, please inform the user and let them decide to fix it or hide it in the demo. You do not need to demo features that are explicitly stated as not implemented, placebo, not within scope of the current development phase, or known to have unfixed issues unless explicitly asked to.

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

- `EdgeTTSBackend(save_dir=..., speaker=..., speed=..., volume=..., cache=True)` for final narration with reusable clips
- `NativeTTSBackend(save_dir=..., speaker=..., cache=True)` to select macOS `say` or Windows SAPI when Edge TTS has an unfixable failure
- `MacOSTTSBackend(save_dir=..., speaker=..., words_per_minute=..., cache=True)` for explicit macOS native TTS
- `WindowsTTSBackend(save_dir=..., speaker=..., rate=..., volume=..., cache=True)` for explicit Windows native TTS
- `tts.list_speakers()` to inspect available voices
- `recorder.synthesize_if_tts_enabled("...")` to prepare narration when TTS is enabled and return plain text otherwise
- `recorder.synthesize_explanation_audio("...")` to prepare narration text plus audio ahead of time
- `await recorder.synthesize_if_tts_enabled_async("...")` or `await recorder.synthesize_explanation_audio_async("...")` to prepare clips from async code
- `recorder.prepare_cues(lines, async_tts=True)` to prepare several clips before capture without duplicating helper code
- `await recorder.prepare_cues_async(lines)` when already inside async code
- `recorder.explain(prepared_explanation)` to reuse pre-generated narration without blocking capture

Prefer this loop:

1. Smoke test with no TTS.
2. Finalize selectors, scrolling, highlights, and result framing.
3. Pre-synthesize cached TTS clips before capture.
4. Record the final narrated pass.

Example pre-synthesis:

```python
intro, conclusion = recorder.prepare_cues(
    [
        "Let's run a fast walkthrough.",
        "The final result is now visible.",
    ],
    async_tts=True,
)
```

If Edge TTS fails, read the full exception. The backend reports speaker, speed, volume, text length, output path, and the original error type/message. First check whether the issue is a bad voice/parameter, missing network access, or a transient service failure. Only switch to `NativeTTSBackend`, `MacOSTTSBackend`, or `WindowsTTSBackend` after the Edge issue is clearly unfixable for the recording run.

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
        speaker="en-US-AvaMultilingualNeural",
        speed="+0%",
        volume="+0%",
        cache=True,
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
            clear=True,
        )
        intro = r.synthesize_if_tts_enabled("Today we'll demonstrate our new app.")
        conclusion = r.synthesize_if_tts_enabled(
            "The help output shows the available actions."
        )
        r.explain(intro)
        r.run(["python", "app.py"], interactive=True, command_label="python app.py")
        r.expect_output(">")
        marker = r.mark_output()
        r.input("help")
        r.expect_output("Commands", since=marker)
        r.explain(conclusion)
        r.explain("That gives us a clean stopping point.")
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

## Web UI Pattern

Use `WebUIRecorder` for browser demos. It defaults to Playwright's built-in page video recorder, so it works well in headless mode and does not need macOS Screen Recording permission unless you explicitly choose `video_backend="ffmpeg"`.

```python
from demo_video_recorder import WebUIRecorder


def main():
    r = WebUIRecorder("out/web-demo.mp4", headless=True, viewport=(1280, 720))
    try:
        r.serve("dist", 8000)
        r.open_web("/")
        r.explain("The app is open in a browser.")
        r.find("input", placeholder="Email").fill("ada@example.com")
        r.find(role="button", name="Continue").click()
        r.find("main", text="Welcome").highlight()
        r.explain("The page confirms that the workflow completed.")
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

Useful helpers:

- `serve(path, port=8000)` starts a static localhost server for a folder.
- `open_web("example.com")` opens a URL; bare domains become `https://...`; relative URLs use the served folder.
- `find(...)` is bs4-like and raises `WebElementNotFoundError` if no visible element is found.
- `find_optional(...)` returns `None` instead of raising.
- `find_all(...)` returns all matched elements.
- `find_input(...)` and `find_all_input(...)` restrict lookup to `input` and `textarea` controls.
- `find_select(...)` and `find_all_select(...)` restrict lookup to `select` controls.
- Element actions include `highlight()`, `click()`, `double_click()`, `hover()`, `wait()`, `text()`, and `attribute()`. Highlights smooth-scroll the target into view.
- Highlight non-interactive results after actions too: status text, generated answers, charts, tables, metrics, toasts, and result panels.
- Input/control actions include `fill()`, `type()`, `clear()`, `set_value()`, `set_range()`, `set_date()`, `set_color()`, `set_files()`, `press()`, `check()`, `uncheck()`, and `select_option()`.
- Prefer the specific visual actions for native controls: `select_option()` shows options, `set_date()` shows a calendar, `set_color()` shows color swatches, `set_range()` animates movement, and radio/checkbox checks highlight the containing field.
- Form actions include `submit()`.

Prefer robust selectors in this order: role and accessible name, label/placeholder/test id, then CSS selector. Use `find_optional()` when a conditional banner, modal, or toast may or may not appear.

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
- `synthesize_explanation_audio_async(text: str) -> SynthesizedExplanation`
- `synthesize_if_tts_enabled(text: str) -> str | SynthesizedExplanation`
- `synthesize_if_tts_enabled_async(text: str) -> str | SynthesizedExplanation`
- `prepare_cues(lines, *, async_tts=False) -> list[str | SynthesizedExplanation]`
- `prepare_cues_async(lines) -> list[str | SynthesizedExplanation]`
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
- `open_terminal(*, title=None, top=False, maximize=False, window_size=None, start_recording=True, new_window=False, script_path=None, extra_args=None, wait_for_worker=True, check_access=None, access_timeout_seconds=30.0, clear=True) -> CLIDemoRecorder`
- `clear() -> CLIDemoRecorder`
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

```python
class WebUIRecorder(
    output_path,
    *,
    browser="chromium",
    headless=True,
    viewport=(1280, 720),
    video_backend="playwright",
    slow_mo_ms=None,
    **kwargs,
)
```

- Inherits all `DemoVideoRecorder` methods.
- `serve(path, port=8000, *, host="127.0.0.1") -> str`
- `open_web(url=None, *, start_recording=True, wait_until="load", timeout_seconds=30.0, headless=None, viewport=None) -> WebUIRecorder`
- `find(name=None, attrs=None, *, text=None, string=None, selector=None, role=None, timeout_seconds=10.0, **kwargs) -> WebElement`
- `find_optional(name=None, attrs=None, *, text=None, string=None, selector=None, role=None, timeout_seconds=2.0, **kwargs) -> WebElement | None`
- `find_all(name=None, attrs=None, *, text=None, string=None, selector=None, role=None, **kwargs) -> list[WebElement]`
- `find_input(name=None, attrs=None, *, text=None, string=None, selector=None, role=None, timeout_seconds=10.0, **kwargs) -> WebInputElement`
- `find_all_input(name=None, attrs=None, *, text=None, string=None, selector=None, role=None, **kwargs) -> list[WebInputElement]`
- `find_select(name=None, attrs=None, *, text=None, string=None, selector=None, role=None, timeout_seconds=10.0, **kwargs) -> WebSelectElement`
- `find_all_select(name=None, attrs=None, *, text=None, string=None, selector=None, role=None, **kwargs) -> list[WebSelectElement]`
- `wait_for_url(url, *, timeout_seconds=10.0) -> WebUIRecorder`
- `stop_recording(*, burn=None) -> Path`
- `close() -> None`

```python
class WebElement
```

- `highlight(*, duration_ms=700, scope="element") -> WebElement`
- `wait(*, state="visible", timeout_seconds=10.0) -> WebElement`
- `click(*, button="left", click_count=1, timeout_seconds=10.0, highlight=True) -> WebElement`
- `double_click(*, timeout_seconds=10.0, highlight=True) -> WebElement`
- `hover(*, timeout_seconds=10.0) -> WebElement`
- `text(*, timeout_seconds=10.0) -> str`
- `attribute(name, *, timeout_seconds=10.0) -> str | None`
- `find(...)`, `find_optional(...)`, `find_all(...)`, `find_input(...)`, `find_all_input(...)`, `find_select(...)`, and `find_all_select(...)` scoped to that element.

```python
class WebInputElement(WebElement)
```

- `fill(value, *, timeout_seconds=10.0, highlight=True) -> WebInputElement`
- `type(text, *, delay_ms=None, timeout_seconds=10.0, highlight=True) -> WebInputElement`
- `clear(*, timeout_seconds=10.0, highlight=True) -> WebInputElement`
- `set_value(value, *, highlight=True, duration_ms=800) -> WebInputElement`
- `set_range(value, *, duration_ms=800, highlight=True) -> WebInputElement`
- `set_date(value, *, preview_ms=900, highlight=True) -> WebInputElement`
- `set_color(value, *, preview_ms=900, highlight=True) -> WebInputElement`
- `set_files(files, *, timeout_seconds=10.0, highlight=True) -> WebInputElement`
- `press(key, *, timeout_seconds=10.0) -> WebInputElement`
- `check(*, timeout_seconds=10.0, highlight=True) -> WebInputElement`
- `uncheck(*, timeout_seconds=10.0, highlight=True) -> WebInputElement`
- `select_option(value=None, *, label=None, index=None, timeout_seconds=10.0, highlight=True) -> WebInputElement`

```python
class WebSelectElement(WebInputElement)
```

- `select_option(value=None, *, label=None, index=None, timeout_seconds=10.0, highlight=True) -> WebSelectElement`

```python
class WebFormElement(WebElement)
```

- `submit(*, highlight=True) -> WebFormElement`

### TTS

```python
class TTSBackend(*, save_dir, ffprobe="ffprobe", cache=False)
```

- `synthesize(text: str) -> SynthesizedAudio`
- `synthesize_async(text: str) -> SynthesizedAudio`
- `cleanup() -> None`
- `list_speakers() -> list[str]`
- `save_audio(text: str) -> Path` (abstract)

```python
class EdgeTTSBackend(
    *,
    save_dir,
    speaker="en-US-AvaMultilingualNeural",
    speed="+0%",
    volume="+0%",
    ffprobe="ffprobe",
    cache=False,
)
```

- Inherits `TTSBackend`.
- `save_audio(text: str) -> Path`
- `list_speakers() -> list[str]`

```python
NativeTTSBackend(*, save_dir, speaker=None, ffprobe="ffprobe", cache=False, **kwargs)
```

- Returns `MacOSTTSBackend` on macOS and `WindowsTTSBackend` on Windows.
- Raises `DependencyMissingError` on other platforms.

```python
class MacOSTTSBackend(
    *,
    save_dir,
    speaker=None,
    words_per_minute=None,
    ffprobe="ffprobe",
    command="say",
    cache=False,
)
```

- Inherits `TTSBackend`.
- Uses the macOS `say` command.
- `save_audio(text: str) -> Path`
- `list_speakers() -> list[str]`

```python
class WindowsTTSBackend(
    *,
    save_dir,
    speaker=None,
    rate=0,
    volume=100,
    ffprobe="ffprobe",
    command="powershell.exe",
    cache=False,
)
```

- Inherits `TTSBackend`.
- Uses native Windows SAPI through PowerShell.
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
class WebElement
class WebInputElement(WebElement)
class WebFormElement(WebElement)
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
class WebElementNotFoundError(DemoVideoRecorderError)
```

Keep demos short and clean. Seed test data when determinism matters; when the user wants randomness or live behavior, react to the app output instead of pretending the result is fixed.
