# Agent Guide

Use `demo-video-recorder` when the user asks for an automated demo video of a project.

## Workflow

1. Inspect the project first. Identify the smallest workflow that proves the app works.
2. Create a short recording script, usually `record_demo.py`, that imports the recorder.
3. Prefer `CLIDemoRecorder` for terminal apps and `DemoVideoRecorder` for GUI or browser windows.
4. Record to `out/<project>-demo.mp4`, or the required location by user; if unspecified, keep generated output out of source control.
5. Follow the user's prompt first for speed, pauses, tone, and coverage. If they do not specify speed, use `DEFAULTS` from the library.
6. Follow the user's requested tone when given. Otherwise use a human live-demo style: natural, somewhat casual or lightly humorous, but still accurate and comprehensive. Unless otherwise specified, your subject should be I or we instead of "the recorder", "the tool".
7. Use `explain()` before or after each visible action so the final video has useful burned subtitles, and spoken narration too when TTS is configured.
8. Run the script yourself. First run a fast smoke test, fix timing, app startup, and input issues until the demo completes. You must check breaking and unintended exceptions or errors during recording, and if the actual video output is not blank and has subtitles.
9. Record the final production demo once the interaction is stable.
10. Stop and tell the user when a global dependency is missing, especially `ffmpeg` or `ffprobe`. On macOS, burned subtitles also require an `ffmpeg` build with the `subtitles` filter (`libass`) (e.g. ffmpeg-full), not the default Homebrew core formula.
11. Unless otherwise specified, you do not need to create a full cli entry point and all parameters in your recorder script, just hard code them in script is fine. You can still have optional args if you need to change it frequently during testing
12. If you use TTS, pick the speaker before recording starts. Follow the user's instructions when they specify a voice; otherwise choose one that fits the project's theme and audience. Use `list_speakers()` on the backend when you need to inspect available voices.
13. TTS generation may be slow enough to show up as dead air in the capture, for pre-determined and long text, pre-synthesize it first with `synthesize_explanation_audio()` or the backend's `synthesize()`, then pass that audio into `explain(..., audio=prepared_audio)`.

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
- `recorder.synthesize_explanation_audio("...")` to prepare a clip ahead of time
- `recorder.explain("...", audio=prepared_audio)` to reuse pre-generated narration without blocking capture

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
from demo_video_recorder import CLIDemoRecorder, DEFAULTS


def main():
    r = CLIDemoRecorder("out/demo.mp4", **DEFAULTS.recorder_kwargs())
    try:
        r.open_terminal(title="Project Demo", top=True, start_recording=True)
        r.explain("Let's take this for a real spin and react to what the app tells us.")
        r.run(["python", "app.py"], interactive=True, command_label="python app.py")
        r.expect_output(">")
        marker = r.mark_output()
        r.input("help")
        r.expect_output("Commands", since=marker)
        r.explain("The help output confirms the available actions.")
        r.input("quit")
        r.stop_app()
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

For a dedicated Windows recording window, pass `new_window=True` to `open_terminal()`.
The parent process will rerun the same script in a new console, wait for it, and exit.

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

Keep demos short and clean. Seed test data when determinism matters; when the user wants randomness or live behavior, react to the app output instead of pretending the result is fixed.
