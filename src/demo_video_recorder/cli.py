"""CLI-oriented recorder helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import subprocess
import sys
import threading
import time
from typing import Mapping, Sequence

from demo_video_recorder.core import Command, DemoVideoRecorder
from demo_video_recorder.errors import ProcessError, RecordingError
from demo_video_recorder import windowing


_WORKER_ENV = "DEMO_VIDEO_RECORDER_TERMINAL_WORKER"
_WORKER_LOG_ENV = "DEMO_VIDEO_RECORDER_WORKER_LOG"


class _Tee:
    def __init__(self, *streams: object) -> None:
        self.streams = streams
        self.encoding = getattr(streams[0], "encoding", "utf-8") if streams else "utf-8"

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)  # type: ignore[attr-defined]
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()  # type: ignore[attr-defined]


@dataclass
class _ManagedCLIProcess:
    process: subprocess.Popen[str]
    output: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    reader: threading.Thread | None = None

    def append(self, text: str) -> None:
        with self.lock:
            self.output.append(text)

    def text(self) -> str:
        with self.lock:
            return "".join(self.output)


class CLIDemoRecorder(DemoVideoRecorder):
    """Recorder specialized for command-line demos."""

    def __init__(
        self,
        output_path: str | Path,
        *,
        typed_character_delay: float = 0.018,
        command_lead_seconds: float = 0.0,
        prompt: str = "> ",
        **kwargs: object,
    ) -> None:
        super().__init__(output_path, **kwargs)
        self.typed_character_delay = typed_character_delay
        self.command_lead_seconds = command_lead_seconds
        self.prompt = prompt
        self.active_process: _ManagedCLIProcess | None = None

    def open_terminal(
        self,
        *,
        title: str | None = None,
        top: bool = False,
        maximize: bool = True,
        start_recording: bool = True,
        new_window: bool = False,
        script_path: str | Path | None = None,
        extra_args: Sequence[str] | None = None,
        wait_for_worker: bool = True,
    ) -> "CLIDemoRecorder":
        """Prepare the terminal window and optionally start capture.

        On Windows, ``new_window=True`` re-runs the current script in a dedicated
        console. The parent process waits for that worker and exits with the same
        code; the worker continues through the rest of the user's script.
        """

        self._install_worker_log()

        if new_window and os.name == "nt" and os.environ.get(_WORKER_ENV) != "1":
            return_code = self._run_in_new_windows_console(
                script_path=script_path,
                extra_args=extra_args,
                wait=wait_for_worker,
            )
            raise SystemExit(return_code)

        terminal_title = title or f"Demo Video Recorder {os.getpid()}"
        window = windowing.configure_current_console(
            title=terminal_title,
            maximize=maximize,
            top=top,
        )
        if window is not None:
            self.capture_window = window
            self.capture_region = window.region

        if start_recording:
            self.start_recording(region=self.capture_region)
        return self

    def run(
        self,
        command: Command,
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        interactive: bool = False,
        command_label: str | None = None,
        shell: bool | None = None,
        check: bool = True,
        timeout: float | None = None,
        reveal_command: bool = True,
    ) -> int | subprocess.Popen[str]:
        """Run a command, streaming output into the recorded terminal."""

        if self.active_process is not None:
            raise ProcessError("A CLI process is already active. Call stop_app() first.")

        label = command_label or self._command_to_label(command)
        if reveal_command:
            self._type_line(label, prefix=self.prompt)
            if self.command_lead_seconds > 0:
                time.sleep(self.command_lead_seconds)

        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            shell=isinstance(command, str) if shell is None else shell,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
        )
        managed = _ManagedCLIProcess(process)
        managed.reader = threading.Thread(
            target=self._stream_process_output,
            args=(managed,),
            daemon=True,
        )
        managed.reader.start()

        if interactive:
            self.active_process = managed
            return process

        return_code = process.wait(timeout=timeout)
        if managed.reader is not None:
            managed.reader.join(timeout=2)
        if check and return_code != 0:
            raise ProcessError(f"Command exited with code {return_code}: {label}")
        return return_code

    def input(
        self,
        text: str,
        *,
        enter: bool = True,
        delay: float | None = None,
        wait_after: float = 0.25,
    ) -> "CLIDemoRecorder":
        """Type into the active CLI app and send the same text to stdin."""

        managed = self._require_active_process()
        if managed.process.stdin is None:
            raise ProcessError("The active process does not accept stdin.")

        char_delay = self.typed_character_delay if delay is None else delay
        for character in text:
            sys.stdout.write(character)
            sys.stdout.flush()
            managed.process.stdin.write(character)
            managed.process.stdin.flush()
            if char_delay > 0:
                time.sleep(char_delay)

        if enter:
            sys.stdout.write("\n")
            sys.stdout.flush()
            managed.process.stdin.write("\n")
            managed.process.stdin.flush()

        if wait_after > 0:
            time.sleep(wait_after)
        return self

    def wait_for_output(self, text: str, *, timeout_seconds: float = 10.0) -> "CLIDemoRecorder":
        managed = self._require_active_process()
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            if text in managed.text():
                return self
            if managed.process.poll() is not None and text in managed.text():
                return self
            time.sleep(0.05)

        raise ProcessError(f"Timed out waiting for CLI output: {text!r}")

    def stop_app(self, *, timeout_seconds: float = 5.0) -> int | None:
        if self.active_process is None:
            return None

        managed = self.active_process
        self.active_process = None
        process = managed.process

        if process.stdin is not None and process.poll() is None:
            try:
                process.stdin.close()
            except OSError:
                pass

        if process.poll() is None:
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    raise RecordingError("The CLI app did not stop cleanly.")

        if managed.reader is not None:
            managed.reader.join(timeout=2)
        return process.returncode

    def close(self) -> None:
        self.stop_app()
        super().close()

    def _run_in_new_windows_console(
        self,
        *,
        script_path: str | Path | None,
        extra_args: Sequence[str] | None,
        wait: bool,
    ) -> int:
        if os.name != "nt":
            raise RecordingError("new_window=True is currently implemented for Windows only.")

        script = Path(script_path or sys.argv[0]).resolve()
        if not script.exists():
            raise RecordingError(f"Cannot open terminal worker for missing script: {script}")

        args = [sys.executable, str(script), *(extra_args if extra_args is not None else sys.argv[1:])]
        env = os.environ.copy()
        env[_WORKER_ENV] = "1"
        env[_WORKER_LOG_ENV] = str(self.output_path.with_suffix(".worker.log").resolve())
        env["PYTHONUNBUFFERED"] = "1"
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        process = subprocess.Popen(args, cwd=os.getcwd(), env=env, creationflags=creationflags)
        if not wait:
            return 0
        return process.wait()

    def _type_line(self, text: str, *, prefix: str = "") -> None:
        sys.stdout.write("\n")
        sys.stdout.write(prefix)
        sys.stdout.flush()
        for character in text:
            sys.stdout.write(character)
            sys.stdout.flush()
            if self.typed_character_delay > 0:
                time.sleep(self.typed_character_delay)
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _stream_process_output(self, managed: _ManagedCLIProcess) -> None:
        stream = managed.process.stdout
        if stream is None:
            return

        while True:
            chunk = stream.read(1)
            if chunk == "":
                break
            managed.append(chunk)
            sys.stdout.write(chunk)
            sys.stdout.flush()

    def _require_active_process(self) -> _ManagedCLIProcess:
        if self.active_process is None:
            raise ProcessError("No active CLI app. Start one with run(..., interactive=True).")
        return self.active_process

    def _command_to_label(self, command: Command) -> str:
        if isinstance(command, str):
            return command
        return subprocess.list2cmdline([str(part) for part in command])

    def _install_worker_log(self) -> None:
        log_path = os.environ.get(_WORKER_LOG_ENV)
        if not log_path or isinstance(sys.stdout, _Tee):
            return

        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_file = Path(log_path).open("a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.stdout, log_file)  # type: ignore[assignment]
        sys.stderr = _Tee(sys.stderr, log_file)  # type: ignore[assignment]
