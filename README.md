# demo-video-recorder

Scriptable demo video recording for Python agents and humans. The package separates reusable recording primitives from project-specific demo steps, so an agent can inspect a project, write a small `record_demo.py`, react to CLI output, and produce an MP4 with burned subtitles and optional narration audio.

The built-in backend uses the installed `ffmpeg` and `ffprobe` executables for screen capture, encoding, probing, subtitle burn-in, and narration audio muxing. Windows capture uses `gdigrab`; macOS capture uses `avfoundation`. Linux capture is not implemented yet.

## Install

```bash
uv sync
```

External tools required for recording:

```bash
ffmpeg -version
ffprobe -version
```

On macOS, high-quality burned subtitles require an `ffmpeg` build with the `subtitles` filter, which depends on `libass`. The default Homebrew `ffmpeg` formula does not include it. Install a libass-enabled build such as `ffmpeg-full`, then put it on `PATH`:

```bash
brew install ffmpeg-full
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
ffmpeg -hide_banner -filters | rg subtitles
```

On macOS, the first real recording attempt may require granting Screen Recording permission to Terminal, iTerm, or the Python host (IDE, VS Code) you run the script from. You can preflight that prompt without recording by running `uv run python mac_request_access.py`. Add `--new-window` to check Terminal.app specifically.

## Quick Start

Record the bundled CLI example:

```bash
uv run python record.py --new-window
```

Add narration audio with Edge TTS:

```bash
uv run python record.py --new-window --tts
```

Print the available Edge TTS speakers:

```bash
uv run python record.py --list-speakers
```

Test only the narration path without opening a new terminal window or recording the screen:

```bash
uv run python record.py --audio-only
```

On macOS, `record.py` defaults to `--check-access`, which requests Screen Recording permission before capture starts and stops early if access is still denied.

The example app lives in `examples/guessing_game.py`; the recording script is `examples/record_guessing_game.py`.
The example intentionally uses a random secret number, so the recorder reads the app output and chooses guesses from the hints instead of replaying fixed inputs.

## Defaults

The built-in defaults mirror the original PowerShell script:

```python
from demo_video_recorder import DEFAULTS

DEFAULTS.words_per_minute          # 170
DEFAULTS.min_pause_seconds         # 2.0
DEFAULTS.command_lead_seconds      # 0.0
DEFAULTS.typed_character_delay     # 0.018
DEFAULTS.capture_framerate         # 15
DEFAULTS.video_scale_width         # 1280
```

Use `FAST_SMOKE_TEST_DEFAULTS` for quick local script checks, not polished final videos.

## CLI Demo API

```python
from demo_video_recorder import CLIDemoRecorder
from demo_video_recorder import EdgeTTSBackend


def main():
    tts = EdgeTTSBackend(
        save_dir="out/demo.tts",
        speaker="en-US-AvaNeural",
        speed="+0%",
        volume="+0%",
    )
    r = CLIDemoRecorder("out/demo.mp4", words_per_minute=165, tts=tts)
    try:
        r.open_terminal(
            title="Demo",
            top=True,
            window_size=(1200, 1200),
            start_recording=True,
            clear=True,
        )
        prepared = r.synthesize_explanation_audio(
            "The app responds to typed input while subtitles explain the action."
        )
        r.explain("Today we'll demo the main workflow.")
        r.run(["python", "app.py"], interactive=True, command_label="python app.py")
        r.expect_output(">")
        marker = r.mark_output()
        r.input("help")
        r.expect_regex(r"Commands?:", since=marker)
        r.explain(prepared)
        r.input("quit")
        r.stop_app()
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

Useful methods:

- `open_terminal(...)`: configures the terminal and can start recording immediately.
- `clear()`: clears the current terminal with `clear` or `cls`.
- `run(..., interactive=True)`: starts a CLI app and streams stdout/stderr to the recorded terminal.
- `input("text")`: types into the active CLI app with a configurable typing delay.
- `expect_output("text")`: waits until expected app output appears.
- `expect_regex(r"...")`: waits for a regex match and returns the match object.
- `mark_output()` / `output_since(marker)`: isolate output caused by one action.
- `output_text("stdout")` and `output_text("stderr")`: inspect streams separately.
- `explain("...")`: adds narration subtitles and, when TTS is configured, also generates a spoken narration clip.
- `explain(prepared_explanation)`: reuses pre-generated narration text and audio without repeating the same string literal.
- `synthesize_explanation_audio("...")`: prepares a `SynthesizedExplanation` ahead of time so `explain()` does not need to wait on synthesis during capture.
- `EdgeTTSBackend.list_speakers()`: returns available Edge voices so you can choose one that fits the audience and tone.
- `stop_recording()`: stops capture, trims subtitles to video duration, and writes the final MP4 with subtitles and narration audio.
- `render_narration_audio()`: exports just the synthesized narration timeline, useful for `--audio-only` test runs.

When `new_window=True` is used, the recorder re-runs the script in a dedicated terminal session. On Windows it opens a new console; on macOS it opens a new Terminal.app window and captures that window instead of the whole display when bounds are available. Worker stdout and stderr are also mirrored to `out/<name>.worker.log`. If the worker fails, the parent process prints the log tail so the recording script is easier to debug.

Platform notes for terminal window control:

- Windows supports `maximize`, `top=True`, and `window_size=(w, h)` for the recorder-managed console window.
- macOS now applies `maximize` and `window_size=(w, h)` as a best-effort resize for Terminal.app and iTerm windows by scripting their window bounds.
- macOS does not currently support persistent `top=True` / always-on-top behavior. The recorder can bring the terminal to the front, but Terminal.app and iTerm do not expose a portable AppleScript API for keeping a normal window above all other apps.

When TTS is enabled, `explain()` uses the real generated audio length instead of the word-count estimate. If synthesis latency could show up in the capture, pre-generate the clip and pass it straight into `explain(prepared_explanation)`. Intermediate per-line clips are removed after the final output unless `keep_tts_audio=True`.

## GUI or App Window API

Currently it can capture the app window, more controls will be added later

```python
from demo_video_recorder import DemoVideoRecorder


def main():
    r = DemoVideoRecorder("out/notepad-demo.mp4")
    try:
        r.open_app(["notepad.exe"], title_hint="Untitled - Notepad", capture_window=True)
        r.start_capture_window()
        r.explain("Notepad is open and the window is being captured.")
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

## Agent Usage

See `AGENT.md` for instructions aimed at coding agents. The intended flow is:

1. Inspect the target project.
2. Write a small deterministic recording script.
3. Use `explain()` around visible actions.
4. Run and fix the script until `out/<name>.mp4` is created.

## Publish Notes

Build locally with:

```bash
uv build
```
