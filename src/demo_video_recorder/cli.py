"""CLI-oriented recorder helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from typing import Literal, Mapping, Pattern, Sequence

from demo_video_recorder.core import Command, DemoVideoRecorder
from demo_video_recorder.defaults import DEFAULTS
from demo_video_recorder.errors import ProcessError, RecordingError
from demo_video_recorder import windowing

_WORKER_ENV = "DEMO_VIDEO_RECORDER_TERMINAL_WORKER"
_WORKER_LOG_ENV = "DEMO_VIDEO_RECORDER_WORKER_LOG"
_WORKER_STATUS_TIMEOUT_SECONDS = 120.0
OutputStream = Literal["combined", "stdout", "stderr"]


@dataclass(frozen=True)
class OutputMarker:
    combined: int
    stdout: int
    stderr: int

    def position(self, stream_name: OutputStream) -> int:
        if stream_name == "stdout":
            return self.stdout
        if stream_name == "stderr":
            return self.stderr
        return self.combined


OutputMarkerLike = int | OutputMarker


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
    combined_output: list[str] = field(default_factory=list)
    stdout_output: list[str] = field(default_factory=list)
    stderr_output: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    stdout_reader: threading.Thread | None = None
    stderr_reader: threading.Thread | None = None

    def append(self, stream_name: OutputStream, text: str) -> None:
        with self.lock:
            self.combined_output.append(text)
            if stream_name == "stdout":
                self.stdout_output.append(text)
            elif stream_name == "stderr":
                self.stderr_output.append(text)

    def text(self, stream_name: OutputStream = "combined") -> str:
        with self.lock:
            if stream_name == "stdout":
                return "".join(self.stdout_output)
            if stream_name == "stderr":
                return "".join(self.stderr_output)
            return "".join(self.combined_output)

    def length(self, stream_name: OutputStream = "combined") -> int:
        return len(self.text(stream_name))


class CLIDemoRecorder(DemoVideoRecorder):
    """Recorder specialized for command-line demos."""

    def __init__(
        self,
        output_path: str | Path,
        *,
        typed_character_delay: float = DEFAULTS.typed_character_delay,
        command_lead_seconds: float = DEFAULTS.command_lead_seconds,
        prompt: str = "> ",
        **kwargs: object,
    ) -> None:
        super().__init__(output_path, **kwargs)  # type: ignore
        self.typed_character_delay = typed_character_delay
        self.command_lead_seconds = command_lead_seconds
        self.prompt = prompt
        self.active_process: _ManagedCLIProcess | None = None
        self.last_process: _ManagedCLIProcess | None = None

    def open_terminal(
        self,
        *,
        title: str | None = None,
        top: bool = False,
        maximize: bool = False,
        window_size: tuple[int, int] | None = None,
        start_recording: bool = True,
        new_window: bool = False,
        script_path: str | Path | None = None,
        extra_args: Sequence[str] | None = None,
        wait_for_worker: bool = True,
        check_access: bool | None = None,
        access_timeout_seconds: float = 30.0,
        clear: bool = True,
    ) -> "CLIDemoRecorder":
        """Prepare the terminal window and optionally start capture.

        On Windows and macOS, ``new_window=True`` re-runs the current script in a
        dedicated terminal session. The parent process waits for that worker and
        exits with the same code; the worker continues through the rest of the
        user's script. When ``clear=True``, the terminal is cleared after setup
        and any recording start has completed.
        """

        self._install_worker_log()

        if new_window and os.environ.get(_WORKER_ENV) != "1":
            return_code = self._run_in_new_terminal_worker(
                title=title,
                script_path=script_path,
                extra_args=extra_args,
                wait=wait_for_worker,
            )
            raise SystemExit(return_code)

        terminal_title = title or f"Demo Video Recorder"
        self._configure_non_windows_terminal_title(terminal_title)
        window = windowing.configure_current_console(
            title=terminal_title,
            maximize=maximize,
            top=top,
            window_size=window_size,
        )
        if window is not None:
            self.capture_window = window
            self.capture_region = window.region

        if check_access is None:
            check_access = platform.system() == "Darwin" and start_recording
        if check_access:
            self.ensure_screen_recording_access(
                prompt=True,
                timeout_seconds=access_timeout_seconds,
                print_status=True,
            )

        if start_recording:
            self.start_recording(region=self.capture_region)
        if clear:
            self.clear()
        return self

    def clear(self) -> "CLIDemoRecorder":
        """Clear the visible terminal using the platform-native command."""

        command = "cls" if os.name == "nt" else "clear"
        if os.system(command) != 0 and os.name != "nt":
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
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
            raise ProcessError(
                "A CLI process is already active. Call stop_app() first."
            )

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
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
        )
        managed = _ManagedCLIProcess(process)
        managed.stdout_reader = threading.Thread(
            target=self._stream_process_output,
            args=(managed, "stdout"),
            daemon=True,
        )
        managed.stderr_reader = threading.Thread(
            target=self._stream_process_output,
            args=(managed, "stderr"),
            daemon=True,
        )
        managed.stdout_reader.start()
        managed.stderr_reader.start()
        self.last_process = managed

        if interactive:
            self.active_process = managed
            return process

        return_code = process.wait(timeout=timeout)
        self._join_readers(managed)
        if check and return_code != 0:
            output = managed.text("combined").strip()
            detail = f"\n\nOutput:\n{output}" if output else ""
            raise ProcessError(
                f"Command exited with code {return_code}: {label}{detail}"
            )
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

    def output_text(self, stream: OutputStream = "combined") -> str:
        """Return captured output from the active or most recent CLI process."""

        return self._require_known_process().text(stream)

    def mark_output(self, stream: OutputStream = "combined") -> OutputMarker:
        """Return a checkpoint for later ``output_since()`` calls."""

        managed = self._require_known_process()
        return OutputMarker(
            combined=managed.length("combined"),
            stdout=managed.length("stdout"),
            stderr=managed.length("stderr"),
        )

    def output_since(
        self, marker: OutputMarkerLike, stream: OutputStream = "combined"
    ) -> str:
        """Return captured output after a checkpoint."""

        return self.output_text(stream)[self._marker_position(marker, stream) :]

    def check_output(
        self,
        text: str,
        *,
        stream: OutputStream = "combined",
        since: OutputMarkerLike = 0,
    ) -> bool:
        """Check whether captured output contains text."""

        managed = self._require_known_process()
        return any(
            text in candidate
            for candidate in self._output_candidates(managed, stream, since)
        )

    def wait_for_output(
        self,
        text: str,
        *,
        timeout_seconds: float = 10.0,
        stream: OutputStream = "combined",
        since: OutputMarkerLike = 0,
    ) -> "CLIDemoRecorder":
        """Wait until captured stdout/stderr contains text."""

        managed = self._require_known_process()
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            if any(
                text in candidate
                for candidate in self._output_candidates(managed, stream, since)
            ):
                return self
            if managed.process.poll() is not None and any(
                text in candidate
                for candidate in self._output_candidates(managed, stream, since)
            ):
                return self
            time.sleep(0.05)

        captured = self.output_since(since, stream).strip()
        detail = f"\n\nCaptured {stream} output:\n{captured}" if captured else ""
        raise ProcessError(f"Timed out waiting for CLI output: {text!r}{detail}")

    def expect_output(
        self,
        text: str,
        *,
        timeout_seconds: float = 10.0,
        stream: OutputStream = "combined",
        since: OutputMarkerLike = 0,
    ) -> str:
        """Wait for text and return the matching output window."""

        self.wait_for_output(
            text, timeout_seconds=timeout_seconds, stream=stream, since=since
        )
        return self.output_since(since, stream)

    def wait_for_regex(
        self,
        pattern: str | Pattern[str],
        *,
        timeout_seconds: float = 10.0,
        stream: OutputStream = "combined",
        since: OutputMarkerLike = 0,
        flags: int = 0,
    ) -> re.Match[str]:
        """Wait until captured output matches a regular expression."""

        managed = self._require_known_process()
        compiled = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            for text in self._output_candidates(managed, stream, since):
                match = compiled.search(text)
                if match is not None:
                    return match
            if managed.process.poll() is not None:
                for text in self._output_candidates(managed, stream, since):
                    match = compiled.search(text)
                    if match is not None:
                        return match
            time.sleep(0.05)

        captured = self.output_since(since, stream).strip()
        detail = f"\n\nCaptured {stream} output:\n{captured}" if captured else ""
        raise ProcessError(
            f"Timed out waiting for CLI regex: {compiled.pattern!r}{detail}"
        )

    def expect_regex(
        self,
        pattern: str | Pattern[str],
        *,
        timeout_seconds: float = 10.0,
        stream: OutputStream = "combined",
        since: OutputMarkerLike = 0,
        flags: int = 0,
    ) -> re.Match[str]:
        """Alias for ``wait_for_regex()`` that reads well in demo scripts."""

        return self.wait_for_regex(
            pattern,
            timeout_seconds=timeout_seconds,
            stream=stream,
            since=since,
            flags=flags,
        )

    def stop_app(self, *, timeout_seconds: float = 5.0) -> int | None:
        if self.active_process is None:
            return None

        managed = self.active_process
        self.active_process = None
        self.last_process = managed
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

        self._join_readers(managed)
        return process.returncode

    def close(self) -> None:
        self.stop_app()
        super().close()

    def _run_in_new_terminal_worker(
        self,
        *,
        title: str | None,
        script_path: str | Path | None,
        extra_args: Sequence[str] | None,
        wait: bool,
    ) -> int:
        system = platform.system()
        if system == "Windows":
            return self._run_in_new_windows_console(
                title=title,
                script_path=script_path,
                extra_args=extra_args,
                wait=wait,
            )
        if system == "Darwin":
            return self._run_in_new_macos_terminal(
                title=title,
                script_path=script_path,
                extra_args=extra_args,
                wait=wait,
            )
        raise RecordingError(
            f"new_window=True is currently implemented for Windows and macOS only, not {system}."
        )

    def _run_in_new_windows_console(
        self,
        *,
        title: str | None,
        script_path: str | Path | None,
        extra_args: Sequence[str] | None,
        wait: bool,
    ) -> int:
        del title
        if os.name != "nt":
            raise RecordingError(
                "Windows terminal worker requested on a non-Windows host."
            )

        script = Path(script_path or sys.argv[0]).resolve()
        if not script.exists():
            raise RecordingError(
                f"Cannot open terminal worker for missing script: {script}"
            )

        args = [
            sys.executable,
            str(script),
            *(extra_args if extra_args is not None else sys.argv[1:]),
        ]
        env = os.environ.copy()
        env[_WORKER_ENV] = "1"
        env[_WORKER_LOG_ENV] = str(
            self.output_path.with_suffix(".worker.log").resolve()
        )
        env["PYTHONUNBUFFERED"] = "1"
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        process = subprocess.Popen(
            args, cwd=os.getcwd(), env=env, creationflags=creationflags
        )
        if not wait:
            return 0
        return_code = process.wait()
        if return_code != 0:
            self._print_worker_log_tail(Path(env[_WORKER_LOG_ENV]))
        return return_code

    def _run_in_new_macos_terminal(
        self,
        *,
        title: str | None,
        script_path: str | Path | None,
        extra_args: Sequence[str] | None,
        wait: bool,
    ) -> int:
        script = Path(script_path or sys.argv[0]).resolve()
        if not script.exists():
            raise RecordingError(
                f"Cannot open terminal worker for missing script: {script}"
            )

        args = [
            sys.executable,
            str(script),
            *(extra_args if extra_args is not None else sys.argv[1:]),
        ]
        env = os.environ.copy()
        env[_WORKER_ENV] = "1"
        env[_WORKER_LOG_ENV] = str(
            self.output_path.with_suffix(".worker.log").resolve()
        )
        env["PYTHONUNBUFFERED"] = "1"

        status_path = self.output_path.with_suffix(".worker.status")
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.unlink(missing_ok=True)
        launcher = self._write_macos_worker_script(
            title=title,
            args=args,
            env=env,
            cwd=Path.cwd(),
            status_path=status_path,
        )
        try:
            result = subprocess.run(
                ["open", "-a", "Terminal", str(launcher)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                detail = (result.stderr + "\n" + result.stdout).strip()
                raise RecordingError(f"Could not launch Terminal.app worker.\n{detail}")

            if not wait:
                return 0

            deadline = time.monotonic() + _WORKER_STATUS_TIMEOUT_SECONDS
            while not status_path.exists():
                if time.monotonic() >= deadline:
                    self._print_worker_log_tail(Path(env[_WORKER_LOG_ENV]))
                    raise RecordingError(
                        "Timed out waiting for the Terminal.app worker to finish."
                    )
                time.sleep(0.25)

            status_text = status_path.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
            return_code = int(status_text or "1")
            if return_code != 0:
                self._print_worker_log_tail(Path(env[_WORKER_LOG_ENV]))
            return return_code
        finally:
            status_path.unlink(missing_ok=True)

    def _write_macos_worker_script(
        self,
        *,
        title: str | None,
        args: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        status_path: Path,
    ) -> Path:
        fd, raw_path = tempfile.mkstemp(
            prefix="demo-video-recorder-", suffix=".command"
        )
        os.close(fd)
        script_path = Path(raw_path)

        exports = [
            f"export {key}={shlex.quote(value)}"
            for key, value in env.items()
            if key in {_WORKER_ENV, _WORKER_LOG_ENV, "PYTHONUNBUFFERED"}
        ]
        title_line = ""
        if title:
            safe_title = title.replace("\\", "\\\\").replace("'", "'\"'\"'")
            title_line = f"printf '\\033]0;{safe_title}\\007'\n"

        lines = [
            "#!/bin/zsh",
            *exports,
            (
                f"cd {shlex.quote(str(cwd))} || "
                f"{{ printf '%s' '1' > {shlex.quote(str(status_path))}; exit 1; }}"
            ),
            title_line.rstrip("\n"),
            f"{shlex.join([str(part) for part in args])}",
            "exit_code=$?",
            f"printf '%s' \"$exit_code\" > {shlex.quote(str(status_path))}",
            'rm -f -- "$0"',
            'exit "$exit_code"',
        ]
        text = "\n".join(line for line in lines if line) + "\n"
        script_path.write_text(text, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    def _configure_non_windows_terminal_title(self, title: str) -> None:
        if os.name == "nt":
            return
        if not title:
            return
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()

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

    def _stream_process_output(
        self,
        managed: _ManagedCLIProcess,
        stream_name: OutputStream,
    ) -> None:
        stream = (
            managed.process.stdout
            if stream_name == "stdout"
            else managed.process.stderr
        )
        if stream is None:
            return

        while True:
            chunk = stream.read(1)
            if chunk == "":
                break
            managed.append(stream_name, chunk)
            output_stream = sys.stdout if stream_name == "stdout" else sys.stderr
            output_stream.write(chunk)
            output_stream.flush()

    def _require_active_process(self) -> _ManagedCLIProcess:
        if self.active_process is None:
            raise ProcessError(
                "No active CLI app. Start one with run(..., interactive=True)."
            )
        return self.active_process

    def _require_known_process(self) -> _ManagedCLIProcess:
        if self.active_process is not None:
            return self.active_process
        if self.last_process is not None:
            return self.last_process
        raise ProcessError("No CLI process has been started yet.")

    def _join_readers(self, managed: _ManagedCLIProcess) -> None:
        for reader in (managed.stdout_reader, managed.stderr_reader):
            if reader is not None:
                reader.join(timeout=2)

    def _marker_position(self, marker: OutputMarkerLike, stream: OutputStream) -> int:
        if isinstance(marker, OutputMarker):
            return marker.position(stream)
        return marker

    def _output_candidates(
        self,
        managed: _ManagedCLIProcess,
        stream: OutputStream,
        marker: OutputMarkerLike,
    ) -> list[str]:
        if stream != "combined":
            return [managed.text(stream)[self._marker_position(marker, stream) :]]

        return [
            managed.text("combined")[self._marker_position(marker, "combined") :],
            managed.text("stdout")[self._marker_position(marker, "stdout") :],
            managed.text("stderr")[self._marker_position(marker, "stderr") :],
        ]

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

    def _print_worker_log_tail(
        self, log_path: Path, *, max_chars: int = 12_000
    ) -> None:
        if not log_path.exists():
            return

        text = log_path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[-max_chars:]
        sys.stderr.write(
            f"\nRecording worker failed. Log tail from {log_path}:\n{text}\n"
        )
        sys.stderr.flush()
