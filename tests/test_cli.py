from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from demo_video_recorder import CLIDemoRecorder
from demo_video_recorder.cli import _WORKER_ENV, _WORKER_LOG_ENV


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
