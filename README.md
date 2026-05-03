# demo-video-recorder

Scriptable demo video recording for Python agents and humans. The package separates reusable recording primitives from project-specific demo steps, so an agent can inspect a project, write a small `record_demo.py`, and produce an MP4 with burned subtitles.

The current backend targets Windows first and uses the installed `ffmpeg` and `ffprobe` executables for screen capture, encoding, probing, and subtitle burn-in. The Python API is structured so macOS and Linux capture backends can be added later.

## Install

```powershell
uv sync
```

External tools required for recording:

```powershell
ffmpeg -version
ffprobe -version
```

## Quick Start

Record the bundled CLI example:

```powershell
uv run python record.py --new-window
```

The example app lives in `examples/guessing_game.py`; the recording script is `examples/record_guessing_game.py`.

## CLI Demo API

```python
from demo_video_recorder import CLIDemoRecorder


def main():
    r = CLIDemoRecorder("out/demo.mp4", words_per_minute=165)
    try:
        r.open_terminal(title="Demo", top=True, start_recording=True)
        r.show_explanation("Today we'll demo the main workflow.")
        r.run(["python", "app.py"], interactive=True, command_label="python app.py")
        r.wait_for_output(">")
        r.input("help")
        r.show_explanation("The app responds to typed input while subtitles explain the action.")
        r.input("quit")
        r.stop_app()
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

Useful methods:

- `open_terminal(...)`: configures the terminal and can start recording immediately.
- `run(..., interactive=True)`: starts a CLI app and streams stdout/stderr to the recorded terminal.
- `input("text")`: types into the active CLI app with a configurable typing delay.
- `wait_for_output("text")`: waits until expected app output appears.
- `show_explanation("...")`: adds narration subtitles and waits long enough to read them.
- `stop_recording()`: stops capture, trims subtitles to video duration, and burns subtitles into the final MP4.

## GUI or App Window API

Currently it can capture the app window, more controls will be added later

```python
from demo_video_recorder import DemoVideoRecorder


def main():
    r = DemoVideoRecorder("out/notepad-demo.mp4")
    try:
        r.open_app(["notepad.exe"], title_hint="Untitled - Notepad", capture_window=True)
        r.start_capture_window()
        r.show_explanation("Notepad is open and the window is being captured.")
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

## Agent Usage

See `AGENT.md` for instructions aimed at coding agents. The intended flow is:

1. Inspect the target project.
2. Write a small deterministic recording script.
3. Use `show_explanation()` around visible actions.
4. Run and fix the script until `out/<name>.mp4` is created.

## Publish Notes

Build locally with:

```powershell
uv build
```
