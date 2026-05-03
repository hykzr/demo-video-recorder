# Agent Guide

Use `demo-video-recorder` when the user asks for an automated demo video of a project.

## Workflow

1. Inspect the project first. Identify the smallest workflow that proves the app works.
2. Create a short recording script, usually `record_demo.py`, that imports the recorder.
3. Prefer `CLIDemoRecorder` for terminal apps and `DemoVideoRecorder` for GUI or browser windows.
4. Record to `out/<project>-demo.mp4`; keep generated output out of source control.
5. Use `show_explanation()` before or after each visible action so the final video has useful burned subtitles.
6. Run the script yourself. Fix timing, app startup, and input issues until the demo completes. You must check if the actual video output is not blank and with subtitle
7. Stop and tell the user when a global dependency is missing, especially `ffmpeg` or `ffprobe`.

## CLI Pattern

```python
from demo_video_recorder import CLIDemoRecorder


def main():
    r = CLIDemoRecorder("out/demo.mp4", words_per_minute=165)
    try:
        r.open_terminal(title="Project Demo", top=True, start_recording=True)
        r.show_explanation("Today we'll walk through the main CLI workflow.")
        r.run(["python", "app.py"], interactive=True, command_label="python app.py")
        r.wait_for_output(">")
        r.input("help")
        r.show_explanation("The help command shows the available actions.")
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
        r.show_explanation("The app is open and ready for the first action.")
    finally:
        r.close()
        if r.is_recording:
            r.stop_recording()
```

Keep demos short, deterministic, and clean. Seed test data inside the script when possible.
