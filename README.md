# demo-video-recorder

Scriptable demo video recording for Python agents and humans.

`demo-video-recorder` helps you write small Python scripts that drive a CLI, browser UI, or native app window and turn that interaction into an MP4. It handles screen or browser capture, subtitle timing, optional burned-in subtitles, and optional narration audio through TTS.

It is especially useful when a coding agent needs to inspect a project, write a deterministic `record_demo.py`, react to app output, and produce a clean demo video without hand-recording the workflow.

## Install

```bash
pip install demo-video-recorder
```

With uv:

```bash
uv add demo-video-recorder
```

Recording depends on `ffmpeg` and `ffprobe` being available:

```bash
ffmpeg -version
ffprobe -version
```

For browser demos, install the Playwright browser binaries once in the environment where you installed the package:

```bash
python -m playwright install chromium
```

Linux capture is not implemented yet. Windows capture uses `gdigrab`; macOS capture uses `avfoundation`. `WebUIRecorder` defaults to Playwright video capture, so headless browser demos do not need macOS Screen Recording permission unless you explicitly use `video_backend="ffmpeg"`.

## macOS Notes

On macOS, the first real screen recording (except playwright recording for webui apps) may require granting Screen Recording permission to Terminal, iTerm, your IDE, or whichever Python host runs the script. You can preflight this from Python:

```python
from demo_video_recorder import check_screen_recording_access

result = check_screen_recording_access(prompt=True)
print(result)
```

High-quality burned subtitles require an `ffmpeg` build with the `subtitles` filter, which depends on `libass`. If your active `ffmpeg` does not support it, install a libass-enabled build such as `ffmpeg-full` and put it on `PATH`:

```bash
brew install ffmpeg-full
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
ffmpeg -hide_banner -filters | rg subtitles
```

## Quick Start: CLI Demo

```python
from demo_video_recorder import CLIDemoRecorder


def main():
    r = CLIDemoRecorder("out/cli-demo.mp4")
    try:
        r.open_terminal(
            title="CLI Demo",
            window_size=(1200, 900),
            start_recording=True,
            clear=True,
        )
        r.explain("We'll run the app and use its help command.")
        r.run(["python", "app.py"], interactive=True, command_label="python app.py")
        r.expect_output(">")
        r.input("help")
        r.expect_regex(r"Commands?:")
        r.explain("The app prints the available commands, so the demo can keep going from real output.")
        r.input("quit")
        r.stop_app()
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()


if __name__ == "__main__":
    main()
```

Useful CLI helpers:

- `open_terminal(...)`: configures the terminal and can start recording.
- `clear()`: clears the current terminal with `clear` or `cls`.
- `run(..., interactive=True)`: starts a CLI app and streams stdout/stderr to the recorded terminal.
- `input("text")`: types into the active CLI app.
- `expect_output("text")` and `expect_regex(r"...")`: wait for real app output.
- `mark_output()` and `output_since(marker)`: isolate output caused by one action.
- `explain("...")`: adds narration subtitles and optional spoken narration.
- `stop_recording()`: finalizes the MP4.

When `new_window=True` is used, the recorder re-runs the script in a dedicated terminal session. On Windows it opens a new console. On macOS it opens a new Terminal.app window and captures that window when bounds are available. Worker stdout and stderr are mirrored to `out/<name>.worker.log`.

## Quick Start: Web UI Demo

`WebUIRecorder` is built for browser demos. It defaults to Playwright's own page video recorder, which works in headless browser contexts and then passes the raw MP4 through the same subtitle and narration pipeline.

```python
from demo_video_recorder import SubtitleStyle, WebUIRecorder


def main():
    r = WebUIRecorder(
        "out/web-demo.mp4",
        headless=True,
        viewport=(1280, 720),
        subtitle_style=SubtitleStyle(
            font_name="Arial",
            font_size=12,
            primary_color="#ffffff",
            outline_color="#000000",
            outline=0.7,
            shadow=0,
            alignment="bottom_center",
            margin_vertical=20,
        ),
    )
    try:
        r.serve("dist", 8000)
        r.open_web("/")
        r.explain("The local web app is open.")
        r.find_input(label="Email address").fill("ada@example.com")
        r.find_select(label="Plan").select_option(label="Pro")
        r.find_input(label="Notes").select_clear_paste(
            0.5,
            "Interested in the Pro plan.",
        )
        r.find(role="button", name="Continue").click()
        r.find("main", text="Welcome").highlight()
        r.explain("The workflow is complete and the confirmation is visible.")
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()


if __name__ == "__main__":
    main()
```

Useful Web UI helpers:

- `serve(path, port=8000)`: serves a static folder over localhost.
- `open_web(url=None)`: opens a URL. Bare domains become `https://...`; relative paths use the served folder.
- `find(...)`: bs4-style visible element lookup.
- `find_optional(...)`: returns `None` instead of raising when an element is absent.
- `find_input(...)`: finds `input` and `textarea` controls.
- `find_select(...)`: finds `select` controls.
- Element methods include `highlight()`, `smooth_scroll()`, `click()`, `double_click()`, `hover()`, `wait()`, `text()`, `attribute()`, and `copy_text()`.
- Use `WebUIRecorder(..., scroll_duration_ms=600, action_pause_seconds=0.25)` to control smooth-scroll speed and add a natural pause after visible browser actions. Scrolling works through nested scroll containers, which is useful for app shells such as Streamlit.
- `element.copy_text()` copies text from a non-input element, such as a `code` block, without selecting the whole page.
- Input methods include `fill()`, `type()`, `clear()`, `edit_text()`, `select_text()`, `select_all()`, `clear_selection()`, `copy()`, `cut()`, `paste()`, `select_clear()`, `select_paste()`, `select_clear_paste()`, `set_range()`, `set_date()`, `set_color()`, `set_files()`, `press()`, `check()`, `uncheck()`, and `select_option()`.
- Use `edit_text()` when you want a correction to look human: it finds the smallest text changes, presses Backspace for removed characters, then types inserted text. Use `select_text(...)` for visible mouse-drag selection, or `select_clear_paste(0.5, "replacement text")` for clipboard-style demos with pauses between selection, clearing, and pasting.

`find()` accepts Beautiful Soup style names and attrs plus Playwright-friendly selectors:

```python
r.find("button", text="Save")
r.find("input", {"name": "email"})
r.find("input", _class="field-control")
r.find(selector="[data-testid='submit']")
r.find(role="button", name="Continue")
r.find(label="Email address").fill("ada@example.com")
```

Prefer robust selectors in this order: role and accessible name, label or placeholder, test id, then CSS selector.

## Quick Start: Native App Window

```python
from demo_video_recorder import DemoVideoRecorder


def main():
    r = DemoVideoRecorder("out/app-demo.mp4")
    try:
        r.open_app(["notepad.exe"], title_hint="Untitled - Notepad", capture_window=True)
        r.start_capture_window()
        r.explain("The app window is open and being captured.")
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()


if __name__ == "__main__":
    main()
```

## Narration Audio

Add `EdgeTTSBackend` when you want spoken narration in addition to subtitles:

```python
from demo_video_recorder import CLIDemoRecorder, EdgeTTSBackend

tts = EdgeTTSBackend(
    save_dir="out/demo.tts",
    speaker="en-US-AvaMultilingualNeural",
    speed="+0%",
    volume="+0%",
    cache=True,
)

r = CLIDemoRecorder("out/demo.mp4", tts=tts)
```

When TTS is enabled, `explain()` uses the generated audio duration instead of estimating from word count. If synthesis latency would show up as dead air in the capture, pre-generate longer narration:

```python
prepared = r.synthesize_if_tts_enabled(
    "This narration is prepared before the visible interaction begins."
)
r.explain(prepared)
```

For several known cues, prepare named cues on the recorder instead of retyping async glue. `prepare_cues()` intentionally accepts a mapping, not a positional list, so revised demos do not silently shift every later cue:

```python
cues = r.prepare_cues(
    {
        "intro": "The app is open.",
        "finish": "The result is now visible.",
    },
    async_tts=True,
)
r.explain(cues["intro"])
```

Do not pass positional cue lists to `prepare_cues()`. Use a `dict[str, str]` and refer to cues by name.

When an action should happen while narration is playing, use `explain_during()`:

```python
r.explain_during(
    cues["finish"],
    lambda: r.find("main", text="Done").highlight(),
)
```

List available Edge voices:

```python
from demo_video_recorder import EdgeTTSBackend

tts = EdgeTTSBackend(save_dir="out/voices")
print("\n".join(tts.list_speakers()))
```

If Edge TTS repeatedly fails for a service or network reason, you can fall back
to native OS speech on macOS or Windows:

```python
from demo_video_recorder import NativeTTSBackend

tts = NativeTTSBackend(save_dir="out/demo.tts", cache=True)
```

## Subtitle Styling

Burned subtitles use ffmpeg's `subtitles` filter. Pass `subtitle_style` to any recorder to set the libass `force_style` values used for burn-in:

```python
from demo_video_recorder import DemoVideoRecorder, SubtitleStyle

r = DemoVideoRecorder(
    "out/demo.mp4",
    subtitle_style=SubtitleStyle(
        font_name="Arial",
        font_size=12,
        primary_color="#ffffff",
        outline_color="#000000",
        border_style=1,
        outline=0.7,
        shadow=0,
        alignment="bottom_center",
        margin_vertical=20,
    ),
)
```

`SubtitleStyle` accepts CSS hex colors such as `#ffffff` and converts them to ASS colors for ffmpeg. You can also pass a mapping with Python-style keys, ASS keys, or a raw `force_style` string if you need a setting not exposed as a field.

## Defaults

```python
from demo_video_recorder import DEFAULTS, FAST_SMOKE_TEST_DEFAULTS

DEFAULTS.words_per_minute          # 170
DEFAULTS.min_pause_seconds         # 2.0
DEFAULTS.command_lead_seconds      # 0.0
DEFAULTS.typed_character_delay     # 0.018
DEFAULTS.capture_framerate         # 15
DEFAULTS.video_scale_width         # 1280
```

Use `FAST_SMOKE_TEST_DEFAULTS` for quick local script checks, not polished final videos.

## FOR AI AGENT: PLEASE READ

This package ships a complete guide for coding agents. Before writing a recording script, read it from the installed package:

```bash
python -c "import importlib.resources as r; print((r.files('demo_video_recorder') / 'AGENT.md').read_text())"
```

The guide covers environment checks, macOS permissions, subtitle support, CLI and Web UI recording patterns, output-aware interactions, TTS pre-synthesis, and final video verification.
