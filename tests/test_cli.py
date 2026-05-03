from __future__ import annotations

import sys

from demo_video_recorder import CLIDemoRecorder


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
