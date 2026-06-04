from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from demo_video_recorder import CLIDemoRecorder, TTSBackend
from demo_video_recorder.cli import (
    _WORKER_ENV,
    _WORKER_LOG_ENV,
)
from demo_video_recorder.types import CaptureRegion, WindowInfo
from demo_video_recorder.tts import SynthesizedAudio


def test_cli_output_helpers_capture_stdout_and_stderr(tmp_path) -> None:
    app = tmp_path / "interactive_app.py"
    app.write_text(
        "\n".join(
            [
                "import sys",
                "print('ready', flush=True)",
                "print('warning from stderr', file=sys.stderr, flush=True)",
                "value = input('Input> ')",
                "print(f'echo: {value}', flush=True)",
            ]
        ),
        encoding="utf-8",
    )

    recorder = CLIDemoRecorder(tmp_path / "demo.mp4", typed_character_delay=0)
    recorder.run([sys.executable, str(app)], interactive=True)
    recorder.expect_output("ready", stream="stdout")
    recorder.expect_output("warning from stderr", stream="stderr")
    recorder.expect_output("Input>")

    marker = recorder.mark_output()
    recorder.input("hello", wait_after=0)
    match = recorder.expect_regex(r"echo: (?P<value>\w+)", since=marker)

    assert match.group("value") == "hello"
    assert recorder.check_output("echo: hello", since=marker)
    assert "warning from stderr" in recorder.output_text("stderr")

    assert recorder.stop_app() == 0


def test_open_terminal_new_window_launches_macos_terminal(
    tmp_path, monkeypatch
) -> None:
    recorder = CLIDemoRecorder(tmp_path / "demo.mp4", typed_character_delay=0)
    captured: dict[str, list[str]] = {}

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
    ) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("demo_video_recorder.cli.platform.system", lambda: "Darwin")
    monkeypatch.setattr("demo_video_recorder.cli.subprocess.run", fake_run)
    monkeypatch.delenv(_WORKER_ENV, raising=False)
    monkeypatch.delenv(_WORKER_LOG_ENV, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        recorder.open_terminal(
            title="Mac Demo",
            new_window=True,
            wait_for_worker=False,
            start_recording=False,
            script_path=__file__,
        )

    assert exc_info.value.code == 0
    assert captured["command"][:3] == ["open", "-a", "Terminal"]

    launcher = Path(captured["command"][3])
    launcher_text = launcher.read_text(encoding="utf-8")
    assert "DEMO_VIDEO_RECORDER_TERMINAL_WORKER=1" in launcher_text
    assert "DEMO_VIDEO_RECORDER_WORKER_LOG" in launcher_text
    assert "Mac Demo" in launcher_text
    assert "exit_code=$?" in launcher_text
    assert sys.executable in launcher_text
    launcher.unlink(missing_ok=True)


def test_cli_tts_flow_writes_final_subtitles_and_cleans_up(
    tmp_path, monkeypatch
) -> None:
    app = tmp_path / "timed_app.py"
    app.write_text(
        "\n".join(
            [
                "import time",
                "print('ready', flush=True)",
                "value = input('Input1> ')",
                "print(f'first: {value}', flush=True)",
                "time.sleep(0.05)",
                "other = input('Input2> ')",
                "print(f'second: {other}', flush=True)",
                "print('done', flush=True)",
            ]
        ),
        encoding="utf-8",
    )

    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def start(self, recorder: CLIDemoRecorder) -> None:
            self.now = 0.0
            recorder.subtitles._clock_started_at = 0.0

        def elapsed(self) -> float:
            return self.now

        def wait_until(self, display_until_seconds: float) -> None:
            self.now = display_until_seconds

    class FakeTTS(TTSBackend):
        def __init__(self, *, save_dir: Path) -> None:
            super().__init__(save_dir=save_dir)
            self.durations = {
                "Intro line": 1.2,
                "First reaction": 0.8,
                "Second reaction": 1.1,
            }

        def save_audio(self, text: str) -> Path:
            path = self.save_dir / f"{text.lower().replace(' ', '-')}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return path

        def synthesize(self, text: str) -> SynthesizedAudio:
            return SynthesizedAudio(
                self.save_audio(text),
                self.durations[text],
            )

    tts = FakeTTS(save_dir=tmp_path / "tts")
    recorder = CLIDemoRecorder(
        tmp_path / "demo.mp4",
        typed_character_delay=0,
        command_lead_seconds=0,
        tts=tts,
    )
    clock = FakeClock()

    class FakeCaptureProcess:
        def poll(self) -> None:
            return None

    created_clip_paths: list[Path] = []
    render_calls: list[Path] = []
    burned: dict[str, Path | None] = {}

    def fake_start(*, region=None) -> None:
        del region
        recorder.capture.process = FakeCaptureProcess()  # type: ignore
        recorder.raw_video_path.write_bytes(b"raw-video")

    def fake_stop(*, timeout_seconds: float = 20.0) -> None:
        del timeout_seconds
        recorder.capture.process = None

    def fake_render_narration_audio(clips, output_path):
        created_clip_paths.extend(clip.path for clip in clips)
        render_calls.append(Path(output_path))
        for clip in clips:
            assert clip.path.exists()
        Path(output_path).write_bytes(b"mixed-audio")
        return Path(output_path)

    def fake_burn_subtitles(subtitle_path, output_path, *, audio_path=None):
        burned["subtitle_path"] = Path(subtitle_path)
        burned["audio_path"] = Path(audio_path) if audio_path is not None else None
        Path(output_path).write_bytes(b"final-video")
        return Path(output_path)

    monkeypatch.setattr(recorder.capture, "start", fake_start)
    monkeypatch.setattr(recorder.capture, "wait_until_ready", lambda: None)
    monkeypatch.setattr(recorder.capture, "stop", fake_stop)
    monkeypatch.setattr(
        recorder.capture,
        "probe_duration_seconds",
        lambda media_path=None: 3.1 if media_path is None else 1.0,
    )
    monkeypatch.setattr(
        recorder.capture,
        "render_narration_audio",
        fake_render_narration_audio,
    )
    monkeypatch.setattr(recorder.capture, "burn_subtitles", fake_burn_subtitles)
    monkeypatch.setattr(
        recorder.subtitles, "start_clock", lambda: clock.start(recorder)
    )
    monkeypatch.setattr(recorder.subtitles, "elapsed_seconds", clock.elapsed)
    monkeypatch.setattr(
        recorder.subtitles,
        "wait_for_display",
        lambda cue: (
            clock.wait_until(cue.display_until_seconds) if cue is not None else None
        ),
    )

    prepared_explanation = recorder.synthesize_explanation_audio("Second reaction")

    recorder.start_recording()
    recorder.explain("Intro line")
    recorder.run([sys.executable, str(app)], interactive=True, reveal_command=False)
    recorder.expect_output("ready")
    recorder.expect_output("Input1>")
    recorder.explain("First reaction")
    recorder.input("hello", wait_after=0)
    recorder.expect_output("first: hello")
    recorder.expect_output("Input2>")
    recorder.explain(prepared_explanation)
    recorder.input("bye", wait_after=0)
    recorder.expect_output("second: bye")
    recorder.expect_output("done")

    assert recorder.stop_app() == 0
    final_path = recorder.stop_recording()

    assert final_path == tmp_path / "demo.mp4"
    assert final_path.read_bytes() == b"final-video"
    assert created_clip_paths == [
        tmp_path / "tts" / "intro-line.mp3",
        tmp_path / "tts" / "first-reaction.mp3",
        tmp_path / "tts" / "second-reaction.mp3",
    ]
    assert render_calls == [recorder.narration_audio_path]
    assert burned["audio_path"] == recorder.narration_audio_path
    assert recorder.raw_video_path.exists() is False
    assert recorder.narration_audio_path.exists() is False
    assert tts.save_dir.exists() is False
    assert recorder.subtitle_path.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,200\n"
        "Intro line\n"
        "\n"
        "2\n"
        "00:00:01,200 --> 00:00:02,000\n"
        "First reaction\n"
        "\n"
        "3\n"
        "00:00:02,000 --> 00:00:03,100\n"
        "Second reaction\n"
    )


def test_open_terminal_passes_custom_window_size_to_windowing(
    tmp_path, monkeypatch
) -> None:
    recorder = CLIDemoRecorder(tmp_path / "demo.mp4", typed_character_delay=0)
    captured: dict[str, object] = {}

    def fake_configure_current_console(**kwargs):
        captured.update(kwargs)
        return WindowInfo(1, "Demo Video Recorder", CaptureRegion(10, 20, 800, 600))

    monkeypatch.setattr(
        "demo_video_recorder.cli.windowing.configure_current_console",
        fake_configure_current_console,
    )
    monkeypatch.setattr(recorder, "start_recording", lambda *, region=None: None)

    recorder.open_terminal(
        start_recording=False,
        window_size=(800, 600),
    )

    assert captured["window_size"] == (800, 600)
    assert recorder.capture_region == CaptureRegion(10, 20, 800, 600)
