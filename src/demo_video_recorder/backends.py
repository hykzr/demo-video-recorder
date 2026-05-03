"""Capture and encoding backends."""

from __future__ import annotations

from pathlib import Path
import platform
import shutil
import subprocess
import time

from demo_video_recorder.errors import DependencyMissingError, RecordingError
from demo_video_recorder.types import CaptureRegion


class FfmpegCaptureBackend:
    """Record a screen region and burn subtitles using ffmpeg."""

    def __init__(
        self,
        raw_video_path: str | Path,
        *,
        framerate: int = 15,
        scale_width: int | None = 1280,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        draw_mouse: bool = False,
        crf: int = 24,
        preset: str = "veryfast",
    ) -> None:
        self.raw_video_path = Path(raw_video_path)
        self.framerate = framerate
        self.scale_width = scale_width
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.draw_mouse = draw_mouse
        self.crf = crf
        self.preset = preset
        self.process: subprocess.Popen[str] | None = None

    @property
    def is_recording(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def ensure_available(self) -> None:
        missing = [name for name in (self.ffmpeg, self.ffprobe) if shutil.which(name) is None]
        if missing:
            joined = ", ".join(missing)
            raise DependencyMissingError(f"Missing external dependency: {joined}")

    def start(self, *, region: CaptureRegion | None = None) -> None:
        if self.is_recording:
            raise RecordingError("Capture is already running.")

        self.ensure_available()
        self.raw_video_path.parent.mkdir(parents=True, exist_ok=True)
        system = platform.system()

        if system != "Windows":
            raise RecordingError(
                f"The ffmpeg backend currently supports Windows gdigrab only, not {system}."
            )

        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "gdigrab",
            "-draw_mouse",
            "1" if self.draw_mouse else "0",
            "-framerate",
            str(self.framerate),
        ]

        if region is not None:
            region.validate()
            command.extend(
                [
                    "-offset_x",
                    str(region.left),
                    "-offset_y",
                    str(region.top),
                    "-video_size",
                    region.size_arg,
                ]
            )

        command.extend(
            [
                "-i",
                "desktop",
                "-c:v",
                "libx264",
                "-preset",
                self.preset,
                "-crf",
                str(self.crf),
            ]
        )

        filters = []
        if self.scale_width and self.scale_width > 0:
            filters.append(f"scale={self.scale_width}:-2")
        filters.append("format=yuv420p")
        command.extend(["-vf", ",".join(filters), str(self.raw_video_path.resolve())])

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.raw_video_path.parent),
        )

    def wait_until_ready(self, *, timeout_seconds: float = 15.0) -> None:
        if self.process is None:
            raise RecordingError("Capture has not been started.")

        deadline = time.monotonic() + timeout_seconds
        started_at = time.monotonic()
        last_size = -1
        saw_growth = False

        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break

            if self.raw_video_path.exists():
                size = self.raw_video_path.stat().st_size
                if size > 65_536:
                    return
                if last_size >= 0 and size > last_size:
                    saw_growth = True
                if size > 0 and (saw_growth or time.monotonic() - started_at >= 0.75):
                    return
                last_size = size

            time.sleep(0.1)

        stdout, stderr = self._process_output_if_exited()
        detail = (stderr + "\n" + stdout).strip()
        raise RecordingError(f"ffmpeg did not start writing the recording in time.\n{detail}")

    def stop(self, *, timeout_seconds: float = 20.0) -> None:
        if self.process is None:
            return

        process = self.process
        self.process = None

        if process.poll() is None:
            if process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.write("q\n")
                    process.stdin.flush()
                except OSError:
                    process.terminate()
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                raise RecordingError("ffmpeg capture did not stop cleanly.") from exc

        stdout, stderr = process.communicate(timeout=5)
        if process.returncode != 0:
            detail = (stderr + "\n" + stdout).strip()
            raise RecordingError(f"ffmpeg capture failed.\n{detail}")

    def probe_duration_seconds(self) -> float:
        self.ensure_available()
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(self.raw_video_path),
        ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RecordingError(f"ffprobe failed.\n{result.stderr.strip()}")

        try:
            duration = float(result.stdout.strip().splitlines()[0])
        except (IndexError, ValueError) as exc:
            raise RecordingError(f"Could not parse ffprobe duration: {result.stdout!r}") from exc
        if duration < 0:
            raise RecordingError(f"Invalid ffprobe duration: {duration}")
        return duration

    def burn_subtitles(self, subtitle_path: str | Path, output_path: str | Path) -> Path:
        self.ensure_available()
        subtitle_path = Path(subtitle_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not subtitle_path.exists() or not subtitle_path.read_text(encoding="utf-8").strip():
            shutil.copy2(self.raw_video_path, output_path)
            return output_path

        temp_subtitle = self.raw_video_path.parent / "__demo_video_recorder_subtitles.srt"
        shutil.copy2(subtitle_path, temp_subtitle)

        try:
            command = [
                self.ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                self.raw_video_path.name,
                "-vf",
                f"subtitles={temp_subtitle.name}",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path.resolve()),
            ]
            result = subprocess.run(
                command,
                cwd=str(self.raw_video_path.parent),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                detail = (result.stderr + "\n" + result.stdout).strip()
                raise RecordingError(f"ffmpeg subtitle burn failed.\n{detail}")
        finally:
            temp_subtitle.unlink(missing_ok=True)

        return output_path

    def _process_output_if_exited(self) -> tuple[str, str]:
        if self.process is None:
            return "", ""

        if self.process.poll() is None:
            return "", ""

        stdout, stderr = self.process.communicate(timeout=1)
        return stdout or "", stderr or ""
